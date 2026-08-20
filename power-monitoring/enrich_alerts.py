import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from elasticsearch import Elasticsearch


load_dotenv("collector.env")

ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")
ALERT_INDEX = "capstone-cx002-alert-logs-v2"


if not ES_ENDPOINT or not ES_API_KEY:
    raise ValueError("ES_ENDPOINT and ES_API_KEY must be configured.")


es = Elasticsearch(
    ES_ENDPOINT,
    api_key=ES_API_KEY
)


METRIC_METADATA = {
    "cpu_usage_percent": {
        "display": "CPU Usage",
        "unit": "%"
    },
    "memory_usage_percent": {
        "display": "Memory Usage",
        "unit": "%"
    },
    "disk_usage_percent": {
        "display": "Disk Usage",
        "unit": "%"
    },
    "memory_request_usage_percent": {
        "display": "Memory Request Usage",
        "unit": "%"
    },
    "memory_limit_usage_percent": {
        "display": "Memory Limit Usage",
        "unit": "%"
    },
    "cpu_request_usage_percent": {
        "display": "CPU Request Usage",
        "unit": "%"
    },
    "cpu_limit_usage_percent": {
        "display": "CPU Limit Usage",
        "unit": "%"
    },
    "temperature_c": {
        "display": "CPU Temperature",
        "unit": "°C"
    },
    "electrical_voltage": {
        "display": "Electrical Voltage",
        "unit": "V"
    },
    "electrical_current_amps": {
        "display": "Electrical Current",
        "unit": "A"
    },
    "actual_power_watts": {
        "display": "Actual Power",
        "unit": "W"
    },
    "estimated_node_power_watts": {
        "display": "Estimated Node Power",
        "unit": "W"
    },
    "power_error_watts": {
        "display": "Power Estimation Error",
        "unit": "W"
    },
    "power_estimation_accuracy_percent": {
        "display": "Power Estimation Accuracy",
        "unit": "%"
    },
    "restart_count_15m": {
        "display": "Pod Restarts in 15 Minutes",
        "unit": "restarts"
    },
    "oom_events_5m": {
        "display": "Out-of-Memory Events",
        "unit": "events"
    },
    "processes_blocked": {
        "display": "Blocked Processes",
        "unit": "processes"
    },
    "load_1min": {
        "display": "One-Minute System Load",
        "unit": ""
    },
    "cpu_throttled_seconds_per_sec": {
        "display": "CPU Throttling Rate",
        "unit": "seconds/second"
    }
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_unenriched_alerts():
    response = es.search(
        index=ALERT_INDEX,
        size=500,
        query={
            "bool": {
                "filter": [
                    {
                        "term": {
                            "notification_type": "ANOMALY_ALERT"
                        }
                    }
                ],
                "must_not": [
                    {
                        "exists": {
                            "field": "enriched_at"
                        }
                    }
                ]
            }
        }
    )

    return response.get("hits", {}).get("hits", [])


def build_resource_fields(source):
    pod_name = source.get("pod_name")
    node_name = source.get("node_name")
    entity_type = source.get("entity_type", "node")

    if pod_name:
        return {
            "resource_type": "Pod",
            "resource_name": pod_name
        }

    return {
        "resource_type": (
            entity_type.replace("_", " ").title()
            if entity_type
            else "Node"
        ),
        "resource_name": node_name or "Unknown"
    }


def enrich_alert(document_id, source):
    metric = source.get("metric", "")
    metadata = METRIC_METADATA.get(
        metric,
        {
            "display": metric.replace("_", " ").title(),
            "unit": ""
        }
    )

    update_document = {
        "metric_display": metadata["display"],
        "value_unit": metadata["unit"],
        "observed_value": source.get(
            "value_numeric",
            source.get("observed_value")
        ),
        "enriched_at": utc_now(),
        **build_resource_fields(source)
    }

    es.update(
        index=ALERT_INDEX,
        id=document_id,
        doc=update_document
    )


def main():
    alerts = get_unenriched_alerts()

    updated = 0

    for alert in alerts:
        document_id = alert.get("_id")
        source = alert.get("_source", {})

        if not document_id:
            continue

        enrich_alert(document_id, source)
        updated += 1

    print(f"Enriched {updated} alert documents.")


if __name__ == "__main__":
    main()
