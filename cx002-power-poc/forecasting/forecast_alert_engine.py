from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from elasticsearch import Elasticsearch


PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / "collector.env"

load_dotenv(
    dotenv_path=ENV_FILE,
    override=True,
)

ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")

LATEST_FORECAST_INDEX = os.getenv(
    "FORECAST_LATEST_INDEX",
    "capstone-cx002-power-forecast-latest",
)

EVALUATION_INDEX = os.getenv(
    "FORECAST_EVALUATION_INDEX",
    "capstone-cx002-forecast-evaluation",
)

ALERT_INDEX = os.getenv(
    "FORECAST_ALERT_INDEX",
    "capstone-cx002-forecast-alerts",
)

NODE_NAME = os.getenv(
    "FORECAST_NODE_NAME",
    "cx-002",
)

CAPACITY_WARNING = float(
    os.getenv("FORECAST_CAPACITY_WARNING_PERCENT", "60")
)

CAPACITY_CRITICAL = float(
    os.getenv("FORECAST_CAPACITY_CRITICAL_PERCENT", "90")
)

ACCURACY_WARNING = float(
    os.getenv("FORECAST_ACCURACY_WARNING_PERCENT", "90")
)

ACCURACY_CRITICAL = float(
    os.getenv("FORECAST_ACCURACY_CRITICAL_PERCENT", "85")
)

COVERAGE_WARNING = float(
    os.getenv("FORECAST_COVERAGE_WARNING_PERCENT", "80")
)

COVERAGE_CRITICAL = float(
    os.getenv("FORECAST_COVERAGE_CRITICAL_PERCENT", "70")
)

EVALUATION_WINDOW_HOURS = int(
    os.getenv("FORECAST_ALERT_EVALUATION_WINDOW_HOURS", "24")
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_client() -> Elasticsearch:
    if not ES_ENDPOINT:
        raise ValueError("ES_ENDPOINT is missing.")

    if not ES_API_KEY:
        raise ValueError("ES_API_KEY is missing.")

    client = Elasticsearch(
        ES_ENDPOINT,
        api_key=ES_API_KEY,
        request_timeout=120,
    )

    client.count(index=LATEST_FORECAST_INDEX)

    print("Elasticsearch connection successful.")

    return client


def get_latest_forecast_summary(
    client: Elasticsearch,
) -> dict[str, Any]:
    response = client.search(
        index=LATEST_FORECAST_INDEX,
        size=1,
        sort=[
            {
                "generated_at": {
                    "order": "desc"
                }
            }
        ],
        _source=[
            "forecast_run_id",
            "model_version",
        ],
        aggs={
            "peak_capacity": {
                "max": {
                    "field":
                        "predicted_capacity_utilization_percent"
                }
            }
        },
    )

    hits = response.get("hits", {}).get("hits", [])

    if not hits:
        raise ValueError(
            "No latest forecast documents were found."
        )

    source = hits[0].get("_source", {})

    return {
        "forecast_run_id": source.get("forecast_run_id"),
        "model_version": source.get("model_version"),
        "peak_capacity": (
            response
            .get("aggregations", {})
            .get("peak_capacity", {})
            .get("value")
        ),
    }


def get_evaluation_summary(
    client: Elasticsearch,
) -> dict[str, float | None]:
    lower_bound = (
        utc_now()
        - timedelta(hours=EVALUATION_WINDOW_HOURS)
    )

    response = client.search(
        index=EVALUATION_INDEX,
        size=0,
        query={
            "range": {
                "forecast_time": {
                    "gte": lower_bound.isoformat(),
                    "lte": utc_now().isoformat(),
                }
            }
        },
        aggs={
            "average_accuracy": {
                "avg": {
                    "field": "forecast_accuracy_percent"
                }
            },
            "interval_coverage": {
                "avg": {
                    "field": "within_prediction_interval"
                }
            },
            "evaluated_points": {
                "value_count": {
                    "field": "actual_power_watts"
                }
            },
        },
    )

    aggregations = response.get("aggregations", {})

    coverage_fraction = (
        aggregations
        .get("interval_coverage", {})
        .get("value")
    )

    coverage_percent = (
        coverage_fraction * 100
        if coverage_fraction is not None
        else None
    )

    return {
        "average_accuracy": (
            aggregations
            .get("average_accuracy", {})
            .get("value")
        ),
        "coverage_percent": coverage_percent,
        "evaluated_points": (
            aggregations
            .get("evaluated_points", {})
            .get("value", 0)
        ),
    }


def upsert_alert(
    client: Elasticsearch,
    *,
    alert_key: str,
    alert_type: str,
    alert_name: str,
    category: str,
    severity: str,
    risk_level: str,
    metric: str,
    observed_value: float,
    threshold: float,
    value_unit: str,
    message: str,
    forecast_run_id: str | None,
    model_version: str | None,
    source_index: str,
) -> None:
    now = utc_now().isoformat()

    document = {
        "@timestamp": now,
        "alert_key": alert_key,
        "alert_type": alert_type,
        "alert_name": alert_name,
        "category": category,
        "severity": severity,
        "risk_level": risk_level,
        "lifecycle_status": "OPEN",
        "node_name": NODE_NAME,
        "metric": metric,
        "observed_value": round(observed_value, 6),
        "threshold": threshold,
        "value_unit": value_unit,
        "message": message,
        "forecast_run_id": forecast_run_id,
        "model_version": model_version,
        "last_seen_at": now,
        "source_index": source_index,
        "source": "ttg_forecast_alert_engine",
    }

    script = {
        "source": """
            ctx._source['@timestamp'] = params.now;
            ctx._source.last_seen_at = params.now;
            ctx._source.observed_value = params.value;
            ctx._source.threshold = params.threshold;
            ctx._source.message = params.message;
            ctx._source.severity = params.severity;
            ctx._source.risk_level = params.risk_level;
            ctx._source.lifecycle_status = 'OPEN';
            ctx._source.occurrence_count =
                (ctx._source.occurrence_count ?: 0) + 1;
        """,
        "params": {
            "now": now,
            "value": round(observed_value, 6),
            "threshold": threshold,
            "message": message,
            "severity": severity,
            "risk_level": risk_level,
        },
    }

    document["opened_at"] = now
    document["occurrence_count"] = 1

    client.update(
        index=ALERT_INDEX,
        id=alert_key,
        script=script,
        upsert=document,
        scripted_upsert=True,
        refresh=False,
    )

    print(
        f"Alert OPEN: {alert_name} "
        f"({observed_value:.2f}{value_unit})"
    )

def resolve_alert(
    client: Elasticsearch,
    *,
    alert_key: str,
    observed_value: float,
    resolution_message: str,
) -> None:
    now = utc_now().isoformat()

    response = client.options(
        ignore_status=404
    ).get(
        index=ALERT_INDEX,
        id=alert_key,
    )

    if not response.get("found"):
        return

    current_status = (
        response
        .get("_source", {})
        .get("lifecycle_status")
    )

    if current_status == "RESOLVED":
        return

    client.update(
        index=ALERT_INDEX,
        id=alert_key,
        doc={
            "@timestamp": now,
            "lifecycle_status": "RESOLVED",
            "resolved_at": now,
            "resolved_by": "ttg_forecast_alert_engine",
            "resolution_reason": resolution_message,
            "observed_value": round(observed_value, 6),
            "last_seen_at": now,
        },
        refresh=False,
    )

    print(
        f"Alert RESOLVED: {alert_key} "
        f"({observed_value:.2f})"
    )

def evaluate_capacity(
    client: Elasticsearch,
    summary: dict[str, Any],
) -> None:
    value = summary.get("peak_capacity")

    if value is None:
        print("Capacity alert skipped: no value.")
        return

    if value >= CAPACITY_CRITICAL:
        resolve_alert(
            client,
            alert_key=f"{NODE_NAME}:forecast:capacity:warning",
            observed_value=value,
            resolution_message=(
                "Warning alert superseded by critical "
                "forecast-capacity alert."
            ),
        )

        upsert_alert(
            client,
            alert_key=f"{NODE_NAME}:forecast:capacity:critical",
            alert_type="FORECAST_CAPACITY_CRITICAL",
            alert_name="Critical Forecast Capacity",
            category="FORECAST_CAPACITY",
            severity="CRITICAL",
            risk_level="CRITICAL",
            metric="predicted_capacity_utilization_percent",
            observed_value=value,
            threshold=CAPACITY_CRITICAL,
            value_unit="%",
            message=(
                f"Forecast peak capacity for {NODE_NAME} "
                f"is {value:.2f}%, above the "
                f"{CAPACITY_CRITICAL:.2f}% critical threshold."
            ),
            forecast_run_id=summary.get("forecast_run_id"),
            model_version=summary.get("model_version"),
            source_index=LATEST_FORECAST_INDEX,
        )

    elif value >= CAPACITY_WARNING:
        upsert_alert(
            client,
            alert_key=f"{NODE_NAME}:forecast:capacity:warning",
            alert_type="FORECAST_CAPACITY_WARNING",
            alert_name="Forecast Capacity Warning",
            category="FORECAST_CAPACITY",
            severity="WARNING",
            risk_level="HIGH",
            metric="predicted_capacity_utilization_percent",
            observed_value=value,
            threshold=CAPACITY_WARNING,
            value_unit="%",
            message=(
                f"Forecast peak capacity for {NODE_NAME} "
                f"is {value:.2f}%, above the "
                f"{CAPACITY_WARNING:.2f}% warning threshold."
            ),
            forecast_run_id=summary.get("forecast_run_id"),
            model_version=summary.get("model_version"),
            source_index=LATEST_FORECAST_INDEX,
        )

    else:
        print(
            "Forecast capacity is normal: "
            f"{value:.2f}%"
        )

        resolve_alert(
            client,
            alert_key=f"{NODE_NAME}:forecast:capacity:warning",
            observed_value=value,
            resolution_message=(
                f"Forecast peak capacity returned to "
                f"{value:.2f}%, below the warning threshold."
            ),
        )

        resolve_alert(
            client,
            alert_key=f"{NODE_NAME}:forecast:capacity:critical",
            observed_value=value,
            resolution_message=(
                f"Forecast peak capacity returned to "
                f"{value:.2f}%, below the critical threshold."
            ),
        )


def evaluate_accuracy(
    client: Elasticsearch,
    summary: dict[str, float | None],
    forecast_summary: dict[str, Any],
) -> None:
    value = summary.get("average_accuracy")

    if value is None:
        print(
            "Accuracy alert skipped: "
            "no evaluated data."
        )
        return

    if value < ACCURACY_CRITICAL:
        severity = "CRITICAL"
        risk_level = "CRITICAL"
        threshold = ACCURACY_CRITICAL

    elif value < ACCURACY_WARNING:
        severity = "WARNING"
        risk_level = "HIGH"
        threshold = ACCURACY_WARNING

    else:
        print(
            "Forecast accuracy is healthy: "
            f"{value:.2f}%"
        )

        resolve_alert(
            client,
            alert_key=(
                f"{NODE_NAME}:forecast:accuracy"
            ),
            observed_value=value,
            resolution_message=(
                "Average forecast accuracy recovered "
                f"to {value:.2f}%, meeting the "
                f"{ACCURACY_WARNING:.2f}% "
                "healthy threshold."
            ),
        )

        return

    upsert_alert(
        client,
        alert_key=(
            f"{NODE_NAME}:forecast:accuracy"
        ),
        alert_type=(
            "FORECAST_ACCURACY_DEGRADATION"
        ),
        alert_name=(
            "Forecast Accuracy Degradation"
        ),
        category="MODEL_PERFORMANCE",
        severity=severity,
        risk_level=risk_level,
        metric="forecast_accuracy_percent",
        observed_value=value,
        threshold=threshold,
        value_unit="%",
        message=(
            f"Average forecast accuracy for "
            f"{NODE_NAME} is {value:.2f}%, below "
            f"the {threshold:.2f}% threshold."
        ),
        forecast_run_id=forecast_summary.get(
            "forecast_run_id"
        ),
        model_version=forecast_summary.get(
            "model_version"
        ),
        source_index=EVALUATION_INDEX,
    )

def evaluate_coverage(
    client: Elasticsearch,
    summary: dict[str, float | None],
    forecast_summary: dict[str, Any],
) -> None:
    value = summary.get("coverage_percent")

    if value is None:
        print("Coverage alert skipped: no evaluated data.")
        return

    if value < COVERAGE_CRITICAL:
        severity = "CRITICAL"
        risk_level = "CRITICAL"
        threshold = COVERAGE_CRITICAL

    elif value < COVERAGE_WARNING:
        severity = "WARNING"
        risk_level = "HIGH"
        threshold = COVERAGE_WARNING

    else:
        print(
            "Prediction interval coverage is healthy: "
            f"{value:.2f}%"
        )


        resolve_alert(
            client,
            alert_key=(
                f"{NODE_NAME}:forecast:interval-coverage"
            ),
            observed_value=value,
            resolution_message=(
                f"Prediction interval coverage recovered to "
                f"{value:.2f}%, meeting the "
                f"{COVERAGE_WARNING:.2f}% healthy threshold."
            ),
        )

        return

    upsert_alert(
        client,
        alert_key=f"{NODE_NAME}:forecast:interval-coverage",
        alert_type="FORECAST_INTERVAL_COVERAGE_LOW",
        alert_name="Low Prediction Interval Coverage",
        category="MODEL_CALIBRATION",
        severity=severity,
        risk_level=risk_level,
        metric="prediction_interval_coverage_percent",
        observed_value=value,
        threshold=threshold,
        value_unit="%",
        message=(
            f"Prediction interval coverage for {NODE_NAME} "
            f"is {value:.2f}%, below the "
            f"{threshold:.2f}% threshold."
        ),
        forecast_run_id=forecast_summary.get("forecast_run_id"),
        model_version=forecast_summary.get("model_version"),
        source_index=EVALUATION_INDEX,
    )


def main() -> None:
    try:
        print("Starting TTG forecast alert engine")

        client = get_client()

        forecast_summary = get_latest_forecast_summary(
            client
        )

        evaluation_summary = get_evaluation_summary(
            client
        )

        print(
            "Peak forecast capacity: "
            f"{forecast_summary['peak_capacity']:.2f}%"
        )

        print(
            "Average forecast accuracy: "
            f"{evaluation_summary['average_accuracy']:.2f}%"
        )

        print(
            "Prediction interval coverage: "
            f"{evaluation_summary['coverage_percent']:.2f}%"
        )

        print(
            "Evaluated points in window: "
            f"{int(evaluation_summary['evaluated_points'])}"
        )

        evaluate_capacity(
            client,
            forecast_summary,
        )

        evaluate_accuracy(
            client,
            evaluation_summary,
            forecast_summary,
        )

        evaluate_coverage(
            client,
            evaluation_summary,
            forecast_summary,
        )

        print("Forecast alert evaluation completed.")

    except KeyboardInterrupt:
        print("Forecast alert engine stopped.")

    except Exception as error:
        print(
            "Forecast alert engine failed: "
            f"{type(error).__name__}: {error}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
