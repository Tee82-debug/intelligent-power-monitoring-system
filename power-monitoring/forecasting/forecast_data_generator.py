import os
import sys
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk


BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

load_dotenv(os.path.join(BASE_DIR, "collector.env"))


ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")

SOURCE_INDEX = os.getenv(
    "FORECAST_SOURCE_INDEX",
    "capstone-cx002-node-metrics",
)

DESTINATION_INDEX = os.getenv(
    "FORECAST_DATA_INDEX",
    "capstone-cx002-forecast-data",
)

NODE_NAME = os.getenv(
    "FORECAST_NODE_NAME",
    "cx-002",
)

AGGREGATION_INTERVAL = os.getenv(
    "FORECAST_AGGREGATION_INTERVAL",
    "5m",
)

TRAINING_DAYS = int(
    os.getenv("FORECAST_TRAINING_DAYS", "37")
)

COMPOSITE_PAGE_SIZE = int(
    os.getenv("FORECAST_BATCH_SIZE", "500")
)


def utc_now() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def safe_float(
    value: Any,
    default: float | None = None,
) -> float | None:
    """Convert an Elasticsearch aggregation value to float."""
    try:
        if value is None:
            return default

        return round(float(value), 6)

    except (TypeError, ValueError):
        return default


def get_client() -> Elasticsearch:
    """Create and validate the Elasticsearch client."""
    if not ES_ENDPOINT:
        raise ValueError(
            "ES_ENDPOINT is missing from collector.env"
        )

    if not ES_API_KEY:
        raise ValueError(
            "ES_API_KEY is missing from collector.env"
        )

    client = Elasticsearch(
        ES_ENDPOINT,
        api_key=ES_API_KEY,
        request_timeout=60,
    )

    try:
        response = client.count(
            index=SOURCE_INDEX
        )

        print(
            "Elasticsearch connection successful. "
            f"Source documents: {response['count']}"
        )

    except Exception as error:
        raise ConnectionError(
            "Elasticsearch connection test failed: "
            f"{type(error).__name__}: {error}"
        ) from error

    return client


def build_aggregation_query(
    after_key: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build a composite aggregation that generates one bucket
    for every fixed 5-minute period.
    """
    composite: dict[str, Any] = {
        "size": COMPOSITE_PAGE_SIZE,
        "sources": [
            {
                "bucket_time": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "fixed_interval": AGGREGATION_INTERVAL,
                        "order": "asc",
                    }
                }
            }
        ],
    }

    if after_key:
        composite["after"] = after_key

    return {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {
                        "range": {
                            "@timestamp": {
                                "gte": f"now-{TRAINING_DAYS}d",
                                "lte": "now",
                            }
                        }
                    },
                    {
                        "term": {
                           "node_name.keyword": NODE_NAME
                        }
                    },
                    {
                        "exists": {
                            "field": "actual_power_watts"
                        }
                    },
                ]
            }
        },
        "aggs": {
            "forecast_buckets": {
                "composite": composite,
                "aggs": {
                    "actual_power": {
                        "avg": {
                            "field": "actual_power_watts"
                        }
                    },
                    "estimated_power": {
                        "avg": {
                            "field": "estimated_node_power_watts"
                        }
                    },
                    "power_error": {
                        "avg": {
                            "field": "power_error_watts"
                        }
                    },
                    "estimation_accuracy": {
                        "avg": {
                            "field": (
                                "power_estimation_accuracy_percent"
                            )
                        }
                    },
                    "cpu_usage": {
                        "avg": {
                            "field": "cpu_usage_percent"
                        }
                    },
                    "memory_usage": {
                        "avg": {
                            "field": "memory_usage_percent"
                        }
                    },
                    "disk_usage": {
                        "avg": {
                            "field": "disk_usage_percent"
                        }
                    },
                    "swap_usage": {
                        "avg": {
                            "field": "swap_usage_percent"
                        }
                    },
                    "temperature": {
                        "avg": {
                            "field": "temperature_c"
                        }
                    },
                    "voltage": {
                        "avg": {
                            "field": "electrical_voltage"
                        }
                    },
                    "current": {
                        "avg": {
                            "field": "electrical_current_amps"
                        }
                    },
                    "load_1min": {
                        "avg": {
                            "field": "load_1min"
                        }
                    },
                    "load_5min": {
                        "avg": {
                            "field": "load_5min"
                        }
                    },
                    "load_15min": {
                        "avg": {
                            "field": "load_15min"
                        }
                    },
                },
            }
        },
    }


def milliseconds_to_iso(milliseconds: int) -> str:
    """Convert epoch milliseconds to a UTC ISO timestamp."""
    timestamp = datetime.fromtimestamp(
        milliseconds / 1000,
        tz=timezone.utc,
    )

    return timestamp.isoformat()


def interval_to_minutes(interval: str) -> int:
    """Convert an interval such as 5m or 1h into minutes."""
    interval = interval.strip().lower()

    if interval.endswith("m"):
        return int(interval[:-1])

    if interval.endswith("h"):
        return int(interval[:-1]) * 60

    raise ValueError(
        "Only minute and hour intervals are currently supported."
    )


def build_document(bucket: dict[str, Any]) -> dict[str, Any] | None:
    """Transform one aggregation bucket into a forecast-data record."""
    bucket_time = bucket.get("key", {}).get("bucket_time")

    if bucket_time is None:
        return None

    actual_power = safe_float(
        bucket.get("actual_power", {}).get("value")
    )

    if actual_power is None:
        return None

    bucket_start = milliseconds_to_iso(int(bucket_time))

    interval_minutes = interval_to_minutes(
        AGGREGATION_INTERVAL
    )

    bucket_end_dt = datetime.fromtimestamp(
        (int(bucket_time) / 1000)
        + (interval_minutes * 60),
        tz=timezone.utc,
    )

    return {
        "@timestamp": bucket_start,
        "bucket_start": bucket_start,
        "bucket_end": bucket_end_dt.isoformat(),
        "node_name": NODE_NAME,
        "actual_power_watts": actual_power,
        "estimated_node_power_watts": safe_float(
            bucket.get("estimated_power", {}).get("value")
        ),
        "power_error_watts": safe_float(
            bucket.get("power_error", {}).get("value")
        ),
        "power_estimation_accuracy_percent": safe_float(
            bucket.get("estimation_accuracy", {}).get("value")
        ),
        "cpu_usage_percent": safe_float(
            bucket.get("cpu_usage", {}).get("value")
        ),
        "memory_usage_percent": safe_float(
            bucket.get("memory_usage", {}).get("value")
        ),
        "disk_usage_percent": safe_float(
            bucket.get("disk_usage", {}).get("value")
        ),
        "swap_usage_percent": safe_float(
            bucket.get("swap_usage", {}).get("value")
        ),
        "temperature_c": safe_float(
            bucket.get("temperature", {}).get("value")
        ),
        "electrical_voltage": safe_float(
            bucket.get("voltage", {}).get("value")
        ),
        "electrical_current_amps": safe_float(
            bucket.get("current", {}).get("value")
        ),
        "load_1min": safe_float(
            bucket.get("load_1min", {}).get("value")
        ),
        "load_5min": safe_float(
            bucket.get("load_5min", {}).get("value")
        ),
        "load_15min": safe_float(
            bucket.get("load_15min", {}).get("value")
        ),
        "sample_count": int(bucket.get("doc_count", 0)),
        "aggregation_interval": AGGREGATION_INTERVAL,
        "source_index": SOURCE_INDEX,
        "record_type": "FORECAST_TRAINING_POINT",
        "source": "ttg_forecast_data_generator",
        "generated_at": utc_now(),
    }


def document_id(document: dict[str, Any]) -> str:
    """
    Generate a deterministic Elasticsearch ID.

    Re-running the script updates the same 5-minute record rather
    than inserting a duplicate.
    """
    timestamp = document["@timestamp"]

    normalized_timestamp = (
        timestamp
        .replace("-", "")
        .replace(":", "")
        .replace("+00:00", "Z")
    )

    return (
        f"{NODE_NAME}-"
        f"{AGGREGATION_INTERVAL}-"
        f"{normalized_timestamp}"
    )


def build_bulk_actions(
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prepare Elasticsearch bulk-index actions."""
    actions: list[dict[str, Any]] = []

    for document in documents:
        actions.append(
            {
                "_op_type": "index",
                "_index": DESTINATION_INDEX,
                "_id": document_id(document),
                "_source": document,
            }
        )

    return actions


def process_page(
    client: Elasticsearch,
    buckets: list[dict[str, Any]],
) -> tuple[int, int]:
    """Transform and index one page of composite buckets."""
    documents: list[dict[str, Any]] = []
    skipped = 0

    for bucket in buckets:
        document = build_document(bucket)

        if document is None:
            skipped += 1
            continue

        documents.append(document)

    if not documents:
        return 0, skipped

    success_count, errors = bulk(
        client,
        build_bulk_actions(documents),
        raise_on_error=False,
        refresh=False,
    )

    if errors:
        print(
            f"Bulk indexing returned {len(errors)} error(s)."
        )

        for error in errors[:5]:
            print(error)

    return int(success_count), skipped


def generate_forecast_data(
    client: Elasticsearch,
) -> None:
    """Read all composite pages and write the forecast dataset."""
    after_key: dict[str, Any] | None = None

    total_buckets = 0
    total_indexed = 0
    total_skipped = 0
    page_number = 0

    while True:
        page_number += 1

        query = build_aggregation_query(after_key)

        response = client.search(
            index=SOURCE_INDEX,
            body=query,
        )

        aggregation = (
            response
            .get("aggregations", {})
            .get("forecast_buckets", {})
        )

        buckets = aggregation.get("buckets", [])

        if not buckets:
            break

        indexed, skipped = process_page(
            client,
            buckets,
        )

        total_buckets += len(buckets)
        total_indexed += indexed
        total_skipped += skipped

        print(
            f"Page {page_number}: "
            f"buckets={len(buckets)}, "
            f"indexed={indexed}, "
            f"skipped={skipped}"
        )

        next_after_key = aggregation.get("after_key")

        if not next_after_key:
            break

        after_key = next_after_key

    print()
    print("Forecast data generation completed")
    print(f"Source index: {SOURCE_INDEX}")
    print(f"Destination index: {DESTINATION_INDEX}")
    print(f"Training window: {TRAINING_DAYS} days")
    print(f"Aggregation interval: {AGGREGATION_INTERVAL}")
    print(f"Total buckets read: {total_buckets}")
    print(f"Documents indexed: {total_indexed}")
    print(f"Buckets skipped: {total_skipped}")


def main() -> None:
    try:
        print("Starting TTG forecast data generator")
        print(f"Source index: {SOURCE_INDEX}")
        print(f"Destination index: {DESTINATION_INDEX}")
        print(f"Node: {NODE_NAME}")

        client = get_client()

        generate_forecast_data(client)

    except KeyboardInterrupt:
        print("Forecast data generator stopped.")

    except Exception as error:
        print(f"Forecast data generator failed: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
