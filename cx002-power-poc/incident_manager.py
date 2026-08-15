import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from elasticsearch import Elasticsearch


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "collector.env"))

ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")

EVENT_INDEX = os.getenv(
    "ALERT_LOG_INDEX",
    "capstone-cx002-alert-logs-v2",
)
INCIDENT_INDEX = os.getenv(
    "INCIDENT_INDEX",
    "capstone-cx002-incidents",
)

INTERVAL_SECONDS = int(
    os.getenv("INCIDENT_MANAGER_INTERVAL_SECONDS", "15")
)
BATCH_SIZE = int(
    os.getenv("INCIDENT_MANAGER_BATCH_SIZE", "100")
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_client() -> Elasticsearch:
    if not ES_ENDPOINT:
        raise ValueError("ES_ENDPOINT is missing from collector.env")

    if not ES_API_KEY:
        raise ValueError("ES_API_KEY is missing from collector.env")

    return Elasticsearch(
        ES_ENDPOINT,
        api_key=ES_API_KEY,
    )


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def get_unprocessed_events(es: Elasticsearch) -> list[dict]:
    response = es.search(
        index=EVENT_INDEX,
        size=BATCH_SIZE,
        sort=[
            {
                "@timestamp": {
                    "order": "asc",
                    "unmapped_type": "date",
                }
            }
        ],
        query={
            "bool": {
                "filter": [
                    {
                        "term": {
                            "notification_type": "ANOMALY_ALERT"
                        }
                    },
                    {
                        "exists": {
                            "field": "alert_key"
                        }
                    },
                ],
                "must_not": [
                    {
                        "term": {
                            "incident_processed": True
                        }
                    }
                ],
            }
        },
    )

    return response.get("hits", {}).get("hits", [])


def find_active_incident(
    es: Elasticsearch,
    alert_key: str,
) -> dict | None:
    response = es.search(
        index=INCIDENT_INDEX,
        size=1,
        sort=[
            {
                "last_seen_at": {
                    "order": "desc",
                    "unmapped_type": "date",
                }
            }
        ],
        query={
            "bool": {
                "filter": [
                    {
                        "term": {
                            "alert_key": alert_key
                        }
                    },
                    {
                        "terms": {
                            "lifecycle_status": [
                                "OPEN",
                                "ACKNOWLEDGED",
                            ]
                        }
                    },
                ]
            }
        },
    )

    hits = response.get("hits", {}).get("hits", [])
    return hits[0] if hits else None


def create_incident(
    es: Elasticsearch,
    event_id: str,
    source: dict,
) -> str:
    incident_id = str(uuid.uuid4())

    event_timestamp = (
        source.get("@timestamp")
        or source.get("opened_at")
        or utc_now()
    )

    observed_value = safe_float(
        source.get(
            "observed_value",
            source.get("value_numeric"),
        )
    )
    anomaly_score = safe_float(source.get("anomaly_score"))

    incident = {
        "@timestamp": event_timestamp,
        "incident_id": incident_id,
        "alert_key": source.get("alert_key"),
        "lifecycle_status": "OPEN",
        "severity": source.get("severity", "WARNING"),
        "risk_level": source.get("risk_level", "WARNING"),
        "category": source.get("category", "UNKNOWN"),
        "metric": source.get("metric", ""),
        "metric_display": source.get(
            "metric_display",
            source.get("metric", ""),
        ),
        "value_unit": source.get("value_unit", ""),
        "node_name": source.get("node_name", "cx-002"),
        "namespace": source.get("namespace"),
        "pod_name": source.get("pod_name"),
        "resource_type": source.get("resource_type"),
        "resource_name": source.get("resource_name"),
        "first_seen_at": event_timestamp,
        "last_seen_at": event_timestamp,
        "opened_at": event_timestamp,
        "observed_value": observed_value,
        "latest_value": observed_value,
        "maximum_value": observed_value,
        "threshold_numeric": safe_float(
            source.get("threshold_numeric")
        ),
        "anomaly_score": anomaly_score,
        "latest_anomaly_score": anomaly_score,
        "maximum_anomaly_score": anomaly_score,
        "event_count": 1,
        "message": source.get("message", ""),
        "recommendation": source.get("recommendation", ""),
        "first_source_event_id": event_id,
        "latest_source_event_id": event_id,
        "source": "ttg_incident_manager",
        "last_updated_at": utc_now(),
    }

    es.index(
        index=INCIDENT_INDEX,
        id=incident_id,
        document=incident,
    )

    return incident_id


def update_incident(
    es: Elasticsearch,
    incident_hit: dict,
    event_id: str,
    source: dict,
) -> str:
    document_id = incident_hit["_id"]
    incident_id = incident_hit["_source"]["incident_id"]

    event_timestamp = (
        source.get("@timestamp")
        or source.get("opened_at")
        or utc_now()
    )

    latest_value = safe_float(
        source.get(
            "observed_value",
            source.get("value_numeric"),
        )
    )
    latest_score = safe_float(source.get("anomaly_score"))

    script = """
        ctx._source.event_count =
            (ctx._source.event_count == null ? 0 : ctx._source.event_count)
            + 1;

        ctx._source.last_seen_at = params.last_seen;
        ctx._source.last_updated_at = params.updated_at;
        ctx._source.latest_source_event_id = params.event_id;

        ctx._source.latest_value = params.latest_value;
        ctx._source.observed_value = params.latest_value;
        ctx._source.latest_anomaly_score = params.latest_score;

        if (ctx._source.maximum_value == null ||
            params.latest_value > ctx._source.maximum_value) {
            ctx._source.maximum_value = params.latest_value;
        }

        if (ctx._source.maximum_anomaly_score == null ||
            params.latest_score > ctx._source.maximum_anomaly_score) {
            ctx._source.maximum_anomaly_score = params.latest_score;
        }

        if (params.message != null && params.message.length() > 0) {
            ctx._source.message = params.message;
        }

        if (params.recommendation != null &&
            params.recommendation.length() > 0) {
            ctx._source.recommendation = params.recommendation;
        }

        if (params.severity == 'CRITICAL') {
            ctx._source.severity = 'CRITICAL';
        }

        if (params.risk_level == 'CRITICAL' ||
            params.risk_level == 'HIGH') {
            ctx._source.risk_level = params.risk_level;
        }
    """

    es.update(
        index=INCIDENT_INDEX,
        id=document_id,
        script={
            "lang": "painless",
            "source": script,
            "params": {
                "last_seen": event_timestamp,
                "updated_at": utc_now(),
                "event_id": event_id,
                "latest_value": latest_value,
                "latest_score": latest_score,
                "message": source.get("message", ""),
                "recommendation": source.get(
                    "recommendation",
                    "",
                ),
                "severity": source.get(
                    "severity",
                    "WARNING",
                ),
                "risk_level": source.get(
                    "risk_level",
                    "WARNING",
                ),
            },
        },
    )

    return incident_id


def mark_event_processed(
    es: Elasticsearch,
    event_id: str,
    incident_id: str,
) -> None:
    es.update(
        index=EVENT_INDEX,
        id=event_id,
        doc={
            "incident_id": incident_id,
            "incident_processed": True,
            "incident_processed_at": utc_now(),
        },
    )


def process_event(
    es: Elasticsearch,
    event: dict,
) -> str:
    event_id = event["_id"]
    source = event.get("_source", {})
    alert_key = source.get("alert_key")

    if not alert_key:
        raise ValueError(
            f"Event {event_id} has no alert_key."
        )

    active_incident = find_active_incident(
        es=es,
        alert_key=alert_key,
    )

    if active_incident:
        incident_id = update_incident(
            es=es,
            incident_hit=active_incident,
            event_id=event_id,
            source=source,
        )
        action = "updated"
    else:
        incident_id = create_incident(
            es=es,
            event_id=event_id,
            source=source,
        )
        action = "created"

    mark_event_processed(
        es=es,
        event_id=event_id,
        incident_id=incident_id,
    )

    return action


def run_cycle(es: Elasticsearch) -> None:
    events = get_unprocessed_events(es)

    created = 0
    updated = 0
    failed = 0

    for event in events:
        try:
            action = process_event(es, event)

            if action == "created":
                created += 1
            else:
                updated += 1

        except Exception as error:
            failed += 1
            print(
                f"Failed to process event "
                f"{event.get('_id')}: {error}"
            )

    print(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        f"events={len(events)} "
        f"created={created} "
        f"updated={updated} "
        f"failed={failed}"
    )


def main() -> None:
    try:
        es = get_client()

        print("Starting TTG Incident Manager")
        print(f"Event index: {EVENT_INDEX}")
        print(f"Incident index: {INCIDENT_INDEX}")
        print(f"Interval: {INTERVAL_SECONDS} seconds")

        while True:
            run_cycle(es)
            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("Incident Manager stopped.")

    except Exception as error:
        print(f"Incident Manager failed: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
