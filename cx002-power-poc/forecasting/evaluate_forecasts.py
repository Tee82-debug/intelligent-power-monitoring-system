import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk


PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / "collector.env"

load_dotenv(ENV_FILE)

ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")

FORECAST_INDEX = os.getenv(
    "FORECAST_HISTORY_INDEX",
    "capstone-cx002-power-forecast",
)

EVALUATION_INDEX = os.getenv(
    "FORECAST_EVALUATION_INDEX",
    "capstone-cx002-forecast-evaluation",
)

ACTUAL_INDEX = os.getenv(
    "FORECAST_ACTUAL_INDEX",
    "capstone-cx002-node-metrics",
)

NODE_NAME = os.getenv(
    "FORECAST_NODE_NAME",
    "cx-002",
)

EVALUATION_DELAY_MINUTES = int(
    os.getenv("FORECAST_EVALUATION_DELAY_MINUTES", "10")
)

LOOKBACK_DAYS = int(
    os.getenv("FORECAST_EVALUATION_LOOKBACK_DAYS", "7")
)

BUCKET_MINUTES = int(
    os.getenv("FORECAST_EVALUATION_INTERVAL_MINUTES", "5")
)

PAGE_SIZE = int(
    os.getenv("FORECAST_EVALUATION_PAGE_SIZE", "500")
)

MIN_ACTUAL_SAMPLES = int(
    os.getenv("FORECAST_MIN_ACTUAL_SAMPLES", "5")
)

ACTUAL_POWER_FIELD = "actual_power_watts"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc_datetime(value: str) -> datetime:
    timestamp = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(timezone.utc)


def get_client() -> Elasticsearch:
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
        request_timeout=120,
    )

    forecast_count = client.count(
        index=FORECAST_INDEX
    )["count"]

    print(
        "Elasticsearch connection successful. "
        f"Historical forecasts: {forecast_count}"
    )

    return client


def load_due_forecasts(
    client: Elasticsearch,
) -> list[dict[str, Any]]:
    """
    Find forecast documents whose forecast time has passed
    and which have not yet been evaluated.
    """
    cutoff = utc_now() - timedelta(
        minutes=EVALUATION_DELAY_MINUTES
    )

    lower_bound = utc_now() - timedelta(
        days=LOOKBACK_DAYS
    )

    records: list[dict[str, Any]] = []
    search_after: list[Any] | None = None

    query = {
        "bool": {
            "filter": [
                {
                    "range": {
                        "forecast_time": {
                            "gte": lower_bound.isoformat(),
                            "lte": cutoff.isoformat(),
                        }
                    }
                },
                {
                    "term": {
                        "node_name": NODE_NAME
                    }
                },
            ],
            "must_not": [
                {
                    "term": {
                        "is_evaluated": True
                    }
                }
            ],
        }
    }

    while True:
        search_body: dict[str, Any] = {
            "index": FORECAST_INDEX,
            "size": PAGE_SIZE,
            "query": query,
            "_source": [
                "forecast_run_id",
                "forecast_time",
                "generated_at",
                "node_name",
                "model_name",
                "model_version",
                "forecast_step",
                "horizon_minutes",
                "predicted_power_watts",
                "prediction_lower",
                "prediction_upper",
            ],
            "sort": [
                {
                    "forecast_time": {
                        "order": "asc",
                        "unmapped_type": "date",
                    }
                }
            ],
        }

        if search_after is not None:
            search_body["search_after"] = search_after

        response = client.search(**search_body)
        hits = response.get("hits", {}).get("hits", [])

        if not hits:
            break

        for hit in hits:
            records.append(
                {
                    "_id": hit["_id"],
                    "_source": hit.get("_source", {}),
                }
            )

        search_after = hits[-1].get("sort")

        print(
            f"Loaded {len(records)} due forecast records"
        )

        if len(hits) < PAGE_SIZE:
            break

    return records


def get_actual_power(
    client: Elasticsearch,
    forecast_time: datetime,
) -> tuple[float | None, int]:
    """
    Average raw actual-power readings over the forecast's
    five-minute interval.
    """
    bucket_end = forecast_time + timedelta(
        minutes=BUCKET_MINUTES
    )

    query = {
        "bool": {
            "filter": [
                {
                    "range": {
                        "@timestamp": {
                            "gte": forecast_time.isoformat(),
                            "lt": bucket_end.isoformat(),
                        }
                    }
                },
                {
                    "exists": {
                        "field": ACTUAL_POWER_FIELD
                    }
                },
            ]
        }
    }

    response = client.search(
        index=ACTUAL_INDEX,
        size=0,
        query=query,
        aggs={
            "actual_average": {
                "avg": {
                    "field": ACTUAL_POWER_FIELD
                }
            },
            "actual_samples": {
                "value_count": {
                    "field": ACTUAL_POWER_FIELD
                }
            },
        },
    )

    aggregations = response.get("aggregations", {})

    actual_value = (
        aggregations
        .get("actual_average", {})
        .get("value")
    )

    sample_count = int(
        aggregations
        .get("actual_samples", {})
        .get("value", 0)
    )

    if actual_value is None:
        return None, sample_count

    return float(actual_value), sample_count


def calculate_metrics(
    predicted: float,
    actual: float,
    lower: float,
    upper: float,
) -> dict[str, Any]:
    signed_error = actual - predicted
    absolute_error = abs(signed_error)
    squared_error = signed_error ** 2

    percentage_error: float | None = None

    if abs(actual) > 1e-9:
        percentage_error = (
            absolute_error / abs(actual)
        ) * 100

    denominator = abs(actual) + abs(predicted)

    symmetric_percentage_error: float | None = None

    if denominator > 1e-9:
        symmetric_percentage_error = (
            2 * absolute_error / denominator
        ) * 100

    if percentage_error is None:
        forecast_accuracy = None
    else:
        forecast_accuracy = max(
            0.0,
            100.0 - percentage_error,
        )

    within_interval = lower <= actual <= upper


    return {
        "signed_error_watts": round(
            signed_error,
            6,
        ),
        "absolute_error_watts": round(
            absolute_error,
            6,
        ),
        "squared_error": round(
            squared_error,
            6,
        ),
        "percentage_error": (
            round(percentage_error, 6)
            if percentage_error is not None
            else None
        ),
        "symmetric_percentage_error": (
            round(symmetric_percentage_error, 6)
            if symmetric_percentage_error is not None
            else None
        ),
        "forecast_accuracy_percent": (
            round(forecast_accuracy, 6)
            if forecast_accuracy is not None
            else None
        ),
        "within_prediction_interval":
            within_interval,
    }


def build_actions(
    client: Elasticsearch,
    forecasts: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    int,
]:
    update_actions: list[dict[str, Any]] = []
    evaluation_actions: list[dict[str, Any]] = []

    skipped = 0
    evaluated_at = utc_now()

    for item in forecasts:
        forecast_id = item["_id"]
        source = item["_source"]

        forecast_time_value = source.get(
            "forecast_time"
        )

        if not forecast_time_value:
            skipped += 1
            continue

        forecast_time = to_utc_datetime(
            forecast_time_value
        )

        actual_power, sample_count = get_actual_power(
            client,
            forecast_time,
        )

        if (
            actual_power is None
            or sample_count < MIN_ACTUAL_SAMPLES
        ):
            skipped += 1
            continue

        predicted = float(
            source.get("predicted_power_watts", 0)
        )

        lower = float(
            source.get("prediction_lower", predicted)
        )

        upper = float(
            source.get("prediction_upper", predicted)
        )

        metrics = calculate_metrics(
            predicted,
            actual_power,
            lower,
            upper,
        )

        update_document = {
            "actual_power_watts": round(
                actual_power,
                6,
            ),
            "actual_sample_count": sample_count,
            "is_evaluated": True,
            "evaluated_at": evaluated_at.isoformat(),
            "evaluation_status": "EVALUATED",
            **metrics,
        }

        update_actions.append(
            {
                "_op_type": "update",
                "_index": FORECAST_INDEX,
                "_id": forecast_id,
                "doc": update_document,
            }
        )

        evaluation_document = {
            "@timestamp": forecast_time.isoformat(),
            "forecast_document_id": forecast_id,
            "forecast_run_id": source.get(
                "forecast_run_id"
            ),
            "forecast_time": forecast_time.isoformat(),
            "evaluated_at": evaluated_at.isoformat(),
            "node_name": source.get(
                "node_name",
                NODE_NAME,
            ),
            "model_name": source.get(
                "model_name",
                "Prophet",
            ),
            "model_version": source.get(
                "model_version",
                "unknown",
            ),
            "forecast_step": source.get(
                "forecast_step"
            ),
            "horizon_minutes": source.get(
                "horizon_minutes"
            ),
            "predicted_power_watts": predicted,
            "prediction_lower": lower,
            "prediction_upper": upper,
            "actual_power_watts": round(
                actual_power,
                6,
            ),
            "actual_sample_count": sample_count,
            "evaluation_status": "EVALUATED",
            "source_forecast_index": FORECAST_INDEX,
            "source_actual_index": ACTUAL_INDEX,
            "source": "ttg_forecast_evaluator",
            **metrics,
        }

        evaluation_actions.append(
            {
                "_op_type": "index",
                "_index": EVALUATION_INDEX,
                "_id": forecast_id,
                "_source": evaluation_document,
            }
        )

    return (
        update_actions,
        evaluation_actions,
        skipped,
    )


def execute_bulk(
    client: Elasticsearch,
    actions: list[dict[str, Any]],
    label: str,
) -> int:
    if not actions:
        return 0

    success_count, errors = bulk(
        client,
        actions,
        raise_on_error=False,
        refresh=False,
    )

    if errors:
        print(
            f"{label} returned {len(errors)} error(s)."
        )

        for error in errors[:5]:
            print(error)

    return int(success_count)


def print_summary(
    client: Elasticsearch,
) -> None:
    response = client.search(
        index=EVALUATION_INDEX,
        size=0,
        aggs={
            "evaluated_points": {
                "value_count": {
                    "field": "actual_power_watts"
                }
            },
            "mae": {
                "avg": {
                    "field": "absolute_error_watts"
                }
            },
            "mse": {
                "avg": {
                    "field": "squared_error"
                }
            },
            "mape": {
                "avg": {
                    "field": "percentage_error"
                }
            },
            "smape": {
                "avg": {
                    "field":
                        "symmetric_percentage_error"
                }
            },
            "interval_coverage": {
                "avg": {
                    "field":
                        "within_prediction_interval"
                }
            },
        },
    )

    aggregations = response.get(
        "aggregations",
        {},
    )

    evaluated_points = (
        aggregations
        .get("evaluated_points", {})
        .get("value", 0)
    )

    mae = (
        aggregations
        .get("mae", {})
        .get("value")
    )

    mse = (
        aggregations
        .get("mse", {})
        .get("value")
    )

    mape = (
        aggregations
        .get("mape", {})
        .get("value")
    )

    smape = (
        aggregations
        .get("smape", {})
        .get("value")
    )

    coverage_fraction = (
        aggregations
        .get("interval_coverage", {})
        .get("value")
    )

    rmse = (
        math.sqrt(mse)
        if mse is not None
        else None
    )

    coverage_percent = (
        coverage_fraction * 100
        if coverage_fraction is not None
        else None
    )

    print()
    print("Current evaluation summary")
    print(f"Evaluated points: {int(evaluated_points)}")

    print(
        "MAE: "
        f"{mae:.4f} W"
        if mae is not None
        else "MAE: N/A"
    )

    print(
        "RMSE: "
        f"{rmse:.4f} W"
        if rmse is not None
        else "RMSE: N/A"
    )

    print(
        "MAPE: "
        f"{mape:.2f}%"
        if mape is not None
        else "MAPE: N/A"
    )

    print(
        "sMAPE: "
        f"{smape:.2f}%"
        if smape is not None
        else "sMAPE: N/A"
    )

    print(
        "Prediction interval coverage: "
        f"{coverage_percent:.2f}%"
        if coverage_percent is not None
        else "Prediction interval coverage: N/A"
    )


def main() -> None:
    try:
        print("Starting TTG forecast evaluator")
        print(f"Forecast index: {FORECAST_INDEX}")
        print(f"Actual metrics index: {ACTUAL_INDEX}")
        print(f"Evaluation index: {EVALUATION_INDEX}")
        print(
            "Evaluation delay: "
            f"{EVALUATION_DELAY_MINUTES} minutes"
        )

        client = get_client()

        due_forecasts = load_due_forecasts(
            client
        )

        if not due_forecasts:
            print(
                "No due unevaluated forecast records found."
            )
            print_summary(client)
            return

        (
            update_actions,
            evaluation_actions,
            skipped_count,
        ) = build_actions(
            client,
            due_forecasts,
        )

        updated_count = execute_bulk(
            client,
            update_actions,
            "Forecast updates",
        )

        indexed_count = execute_bulk(
            client,
            evaluation_actions,
            "Evaluation indexing",
        )

        print()
        print("Forecast evaluation completed")
        print(
            f"Due forecasts read: "
            f"{len(due_forecasts)}"
        )
        print(
            f"Historical forecasts updated: "
            f"{updated_count}"
        )
        print(
            f"Evaluation documents indexed: "
            f"{indexed_count}"
        )
        print(
            f"Forecasts skipped: "
            f"{skipped_count}"
        )

        print_summary(client)

    except KeyboardInterrupt:
        print("Forecast evaluator stopped.")

    except Exception as error:
        print(
            "Forecast evaluation failed: "
            f"{type(error).__name__}: {error}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
