import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from prophet import Prophet


PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / "collector.env"
MODEL_DIR = PROJECT_DIR / "forecasting" / "models"

load_dotenv(ENV_FILE)

ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")

TRAINING_INDEX = os.getenv(
    "FORECAST_DATA_INDEX",
    "capstone-cx002-forecast-data",
)

RESULT_INDEX = os.getenv(
    "FORECAST_RESULT_INDEX",
    "capstone-cx002-power-forecast",
)
LATEST_INDEX = os.getenv(
    "FORECAST_LATEST_INDEX",
    "capstone-cx002-power-forecast-latest",
)

TARGET_FIELD = os.getenv(
    "FORECAST_TARGET_FIELD",
    "actual_power_watts",
)

NODE_NAME = os.getenv(
    "FORECAST_NODE_NAME",
    "cx-002",
)

MIN_SAMPLE_COUNT = int(
    os.getenv("FORECAST_MIN_SAMPLE_COUNT", "10")
)

TRAINING_DAYS = int(
    os.getenv("FORECAST_TRAINING_DAYS", "37")
)

FORECAST_INTERVAL_MINUTES = int(
    os.getenv("FORECAST_INTERVAL_MINUTES", "5")
)

FORECAST_HORIZON_HOURS = int(
    os.getenv("FORECAST_HORIZON_HOURS", "24")
)

CONFIDENCE_INTERVAL = float(
    os.getenv("FORECAST_CONFIDENCE_INTERVAL", "0.95")
)

CHANGEPOINT_PRIOR_SCALE = float(
    os.getenv(
        "FORECAST_CHANGEPOINT_PRIOR_SCALE",
        "0.05",
    )
)

SEASONALITY_PRIOR_SCALE = float(
    os.getenv(
        "FORECAST_SEASONALITY_PRIOR_SCALE",
        "10.0",
    )
)

MODEL_NAME = os.getenv(
    "FORECAST_MODEL_NAME",
    "Prophet",
)

MODEL_VERSION = os.getenv(
    "FORECAST_MODEL_VERSION",
    "v1.0",
)

SCENARIO_MODE_ENABLED = (
    os.getenv("FORECAST_SCENARIO_MODE", "false")
    .strip()
    .lower()
    in {"true", "1", "yes", "on"}
)

CAPACITY_LIMIT_WATTS = float(
    os.getenv("CIRCUIT_CAPACITY_WATTS", "1440")
)

MODERATE_THRESHOLD = float(
    os.getenv(
        "FORECAST_MODERATE_THRESHOLD_PERCENT",
        "60",
    )
)

HIGH_THRESHOLD = float(
    os.getenv(
        "FORECAST_HIGH_THRESHOLD_PERCENT",
        "80",
    )
)

CRITICAL_THRESHOLD = float(
    os.getenv(
        "FORECAST_CRITICAL_THRESHOLD_PERCENT",
        "95",
    )
)

PAGE_SIZE = 1000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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

    response = client.count(index=TRAINING_INDEX)

    print(
        "Elasticsearch connection successful. "
        f"Training documents: {response['count']}"
    )

    return client


def load_training_data(
    client: Elasticsearch,
) -> pd.DataFrame:
    """
    Load forecast training points using search_after pagination.
    """
    records: list[dict[str, Any]] = []
    search_after: list[Any] | None = None

    query = {
        "bool": {
            "filter": [
                {
                    "term": {
                        "node_name.keyword": NODE_NAME
                    }
                },
                {
                    "term": {
                        "record_type.keyword":
                            "FORECAST_TRAINING_POINT"
                    }
                },
                {
                    "range": {
                        "sample_count": {
                            "gte": MIN_SAMPLE_COUNT
                        }
                    }
                },
                {
                    "range": {
                        "@timestamp": {
                            "gte": f"now-{TRAINING_DAYS}d",
                            "lt": (
                                f"now-"
                                f"{FORECAST_INTERVAL_MINUTES}m"
                            ),
                        }
                    }
                },
                {
                    "exists": {
                        "field": TARGET_FIELD
                    }
                },
            ]
        }
    }

    while True:
        search_args: dict[str, Any] = {
            "index": TRAINING_INDEX,
            "size": PAGE_SIZE,
            "query": query,
            "_source": [
                "@timestamp",
                TARGET_FIELD,
                "sample_count",
            ],
            "sort": [
                {
                    "@timestamp": {
                        "order": "asc",
                        "unmapped_type": "date",
                    }
                },
            ],
        }

        if search_after is not None:
            search_args["search_after"] = search_after

        response = client.search(**search_args)
        hits = response.get("hits", {}).get("hits", [])

        if not hits:
            break

        for hit in hits:
            source = hit.get("_source", {})

            records.append(
                {
                    "ds": source.get("@timestamp"),
                    "y": source.get(TARGET_FIELD),
                    "sample_count": source.get(
                        "sample_count",
                        0,
                    ),
                }
            )

        search_after = hits[-1].get("sort")

        print(
            f"Loaded {len(records)} training records"
        )

        if len(hits) < PAGE_SIZE:
            break

    if not records:
        raise ValueError(
            "No training records matched the configured filters."
        )

    frame = pd.DataFrame(records)

    frame["ds"] = pd.to_datetime(
        frame["ds"],
        utc=True,
        errors="coerce",
    )

    frame["y"] = pd.to_numeric(
        frame["y"],
        errors="coerce",
    )

    frame = frame.dropna(subset=["ds", "y"])
    frame = frame.drop_duplicates(
        subset=["ds"],
        keep="last",
    )
    frame = frame.sort_values("ds").reset_index(drop=True)

    # Prophet expects timezone-naive timestamps.
    frame["ds"] = frame["ds"].dt.tz_convert(None)

    # Electrical power cannot be negative.
    frame = frame[frame["y"] >= 0].copy()

    if len(frame) < 288:
        raise ValueError(
            "Fewer than 288 valid five-minute points remain. "
            "At least approximately 24 hours is required."
        )

    return frame[["ds", "y"]]


def describe_training_data(frame: pd.DataFrame) -> None:
    interval_differences = (
        frame["ds"]
        .sort_values()
        .diff()
        .dropna()
        .dt.total_seconds()
        .div(60)
    )

    print()
    print("Training dataset summary")
    print(f"Points: {len(frame)}")
    print(f"Start: {frame['ds'].min()}")
    print(f"End: {frame['ds'].max()}")
    print(f"Minimum power: {frame['y'].min():.3f} W")
    print(f"Maximum power: {frame['y'].max():.3f} W")
    print(f"Average power: {frame['y'].mean():.3f} W")

    if not interval_differences.empty:
        print(
            "Median interval: "
            f"{interval_differences.median():.2f} minutes"
        )


def train_model(frame: pd.DataFrame) -> Prophet:
    model = Prophet(
        growth="linear",
        interval_width=CONFIDENCE_INTERVAL,
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=False,
        seasonality_mode="additive",
        changepoint_prior_scale=CHANGEPOINT_PRIOR_SCALE,
        seasonality_prior_scale=SEASONALITY_PRIOR_SCALE,
    )

    model.fit(frame)

    return model


def save_model(
    model: Prophet,
    forecast_run_id: str,
) -> Path:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    latest_path = MODEL_DIR / "prophet_power_latest.pkl"
    versioned_path = (
        MODEL_DIR
        / f"prophet_power_{forecast_run_id}.pkl"
    )

    joblib.dump(model, versioned_path)
    joblib.dump(model, latest_path)

    return versioned_path


def create_forecast(
    model: Prophet,
    training_frame: pd.DataFrame,
) -> pd.DataFrame:
    periods = (
        FORECAST_HORIZON_HOURS
        * 60
        // FORECAST_INTERVAL_MINUTES
    )

    future = model.make_future_dataframe(
        periods=periods,
        freq=f"{FORECAST_INTERVAL_MINUTES}min",
        include_history=False,
    )

    forecast = model.predict(future)

    output = forecast[
        [
            "ds",
            "yhat",
            "yhat_lower",
            "yhat_upper",
        ]
    ].copy()

    output["yhat"] = output["yhat"].clip(lower=0)
    output["yhat_lower"] = (
        output["yhat_lower"].clip(lower=0)
    )
    output["yhat_upper"] = (
        output["yhat_upper"].clip(lower=0)
    )

    output["training_start"] = training_frame["ds"].min()
    output["training_end"] = training_frame["ds"].max()
    output["training_points"] = len(training_frame)

    return output


def classify_forecast_status(
    capacity_utilization_percent: float,
) -> tuple[str, int]:
    """
    Classify forecast risk from predicted electrical-capacity utilization.

    Risk score:
        1 = LOW
        2 = MODERATE
        3 = HIGH
        4 = CRITICAL
    """
    if capacity_utilization_percent < 60:
        return "LOW", 1

    if capacity_utilization_percent < 80:
        return "MODERATE", 2

    if capacity_utilization_percent < 95:
        return "HIGH", 3

    return "CRITICAL", 4


def classify_demo_scenario(
    step_number: int,
    total_steps: int,
) -> tuple[str, int]:
    """
    Assign demonstration-only risk levels across the forecast horizon.

    Distribution:
        First 70%  = LOW
        Next 15%   = MODERATE
        Next 10%   = HIGH
        Final 5%   = CRITICAL
    """
    progress = step_number / total_steps

    if progress <= 0.70:
        return "LOW", 1

    if progress <= 0.85:
        return "MODERATE", 2

    if progress <= 0.95:
        return "HIGH", 3

    return "CRITICAL", 4

def build_forecast_actions(
    forecast: pd.DataFrame,
    forecast_run_id: str,
    generated_at: datetime,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    for step_number, row in enumerate(
        forecast.itertuples(index=False),
        start=1,
    ):
        forecast_time = pd.Timestamp(row.ds)

        if forecast_time.tzinfo is None:
            forecast_time = forecast_time.tz_localize("UTC")
        else:
            forecast_time = forecast_time.tz_convert("UTC")

        predicted = max(float(row.yhat), 0.0)
        lower = max(float(row.yhat_lower), 0.0)
        upper = max(float(row.yhat_upper), 0.0)

        capacity_utilization = (
            predicted / CAPACITY_LIMIT_WATTS * 100
            if CAPACITY_LIMIT_WATTS > 0
            else 0.0
        )

        status, risk_score = classify_forecast_status(capacity_utilization)

        if SCENARIO_MODE_ENABLED:
            scenario_status, scenario_risk_score = (
                classify_demo_scenario(
                    step_number,
                    len(forecast),
                )
            )
        else:
            scenario_status = status
            scenario_risk_score = risk_score

        horizon_minutes = (
            step_number * FORECAST_INTERVAL_MINUTES
        )

        document_id = (
            f"{forecast_run_id}-"
            f"{forecast_time.strftime('%Y%m%dT%H%M%SZ')}"
        )

        training_start = pd.Timestamp(
            row.training_start
        ).tz_localize("UTC")

        training_end = pd.Timestamp(
            row.training_end
        ).tz_localize("UTC")

        document = {
            "@timestamp": forecast_time.isoformat(),
            "forecast_time": forecast_time.isoformat(),
            "generated_at": generated_at.isoformat(),
            "forecast_run_id": forecast_run_id,
            "node_name": NODE_NAME,
            "metric": TARGET_FIELD,
            "metric_display": "Actual Power",
            "value_unit": "W",
            "predicted_power_watts": round(
                predicted,
                6,
            ),
            "prediction_lower": round(
                lower,
                6,
            ),
            "prediction_upper": round(
                upper,
                6,
            ),
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "interval_width": CONFIDENCE_INTERVAL,
            "changepoint_prior_scale": CHANGEPOINT_PRIOR_SCALE,
            "seasonality_prior_scale": SEASONALITY_PRIOR_SCALE,
            "forecast_horizon_hours":
                FORECAST_HORIZON_HOURS,
            "forecast_step": step_number,
            "horizon_minutes": horizon_minutes,
            "training_start": training_start.isoformat(),
            "training_end": training_end.isoformat(),
            "training_points": int(row.training_points),
            "capacity_limit_watts":
                CAPACITY_LIMIT_WATTS,
            "predicted_capacity_utilization_percent":
                round(capacity_utilization, 6),
            "forecast_status": status,
            "forecast_risk_score": risk_score,
            "scenario_status": scenario_status,
            "scenario_risk_score": scenario_risk_score,
            "scenario_mode_enabled": SCENARIO_MODE_ENABLED,
            "threshold_exceeded":
                status in {"HIGH", "CRITICAL"},
            "is_evaluated": False,
            "source_index": TRAINING_INDEX,
            "source": "ttg_prophet_forecast_engine",
        }

        actions.append(
            {
                "_op_type": "index",
                "_index": RESULT_INDEX,
                "_id": document_id,
                "_source": document,
            }
        )

    return actions

def build_latest_forecast_actions(
    history_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Build a second set of actions for the latest-forecast index.

    Fixed document IDs ensure that every new run replaces the
    previous 288 forecast points instead of creating duplicates.
    """
    latest_actions: list[dict[str, Any]] = []

    for action in history_actions:
        document = dict(action["_source"])
        step_number = int(document["forecast_step"])

        latest_document_id = (
            f"{NODE_NAME}-latest-step-{step_number:03d}"
        )

        latest_actions.append(
            {
                "_op_type": "index",
                "_index": LATEST_INDEX,
                "_id": latest_document_id,
                "_source": document,
            }
        )

    return latest_actions

def index_actions(
    client: Elasticsearch,
    actions: list[dict[str, Any]],
    label: str,
) -> int:
    success_count, errors = bulk(
        client,
        actions,
        raise_on_error=False,
        refresh=False,
    )

    if errors:
        print(
            f"{label} indexing returned "
            f"{len(errors)} error(s)."
        )

        for error in errors[:5]:
            print(error)

    return int(success_count)

def index_forecast(
    client: Elasticsearch,
    actions: list[dict[str, Any]],
    label: str,
) -> int:
    success_count, errors = bulk(
        client,
        actions,
        raise_on_error=False,
        refresh=False,
    )

    if errors:
        print(
            f"{label} indexing returned "
            f"{len(errors)} error(s)."
        )

        for error in errors[:5]:
            print(error)

    return int(success_count)


def main() -> None:
    try:
        print("Starting TTG Prophet forecasting engine")
        print(f"Training index: {TRAINING_INDEX}")
        print(f"Forecast index: {RESULT_INDEX}")
        print(f"Latest forecast index: {LATEST_INDEX}")
        print(f"Target field: {TARGET_FIELD}")
        print(f"Model version: {MODEL_VERSION}")
        print(
            "Confidence interval: "
            f"{CONFIDENCE_INTERVAL}"
        )
        print(
            "Changepoint prior scale: "
            f"{CHANGEPOINT_PRIOR_SCALE}"
        )
        print(
            "Seasonality prior scale: "
            f"{SEASONALITY_PRIOR_SCALE}"
        )

        client = get_client()

        training_frame = load_training_data(client)
        describe_training_data(training_frame)

        forecast_run_id = (
            utc_now()
            .strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex[:8]
        )

        print()
        print("Training Prophet model...")
        model = train_model(training_frame)
        print("Model training completed.")

        model_path = save_model(
            model,
            forecast_run_id,
        )

        print(f"Model saved to: {model_path}")

        forecast = create_forecast(
            model,
            training_frame,
        )

        generated_at = utc_now()

        history_actions = build_forecast_actions(
            forecast,
            forecast_run_id,
            generated_at,
        )

        latest_actions = build_latest_forecast_actions(
            history_actions
        )

        history_indexed_count = index_actions(
            client,
            history_actions,
            "Forecast history",
        )

        latest_indexed_count = index_actions(
            client,
            latest_actions,
            "Latest forecast",
        )

        print()
        print("Forecast generation completed")
        print(f"Forecast run ID: {forecast_run_id}")
        print(
            f"Forecast points created: {len(forecast)}"
        )
        print(
            "Historical forecast documents indexed: "
            f"{history_indexed_count}"
        )
        print(
            "Latest forecast documents indexed: "
            f"{latest_indexed_count}"
        )
        print(
            "Forecast start: "
            f"{forecast['ds'].min()}"
        )
        print(
            "Forecast end: "
            f"{forecast['ds'].max()}"
        )

    except KeyboardInterrupt:
        print("Forecasting engine stopped.")

    except Exception as error:
        print(
            "Prophet forecasting failed: "
            f"{type(error).__name__}: {error}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
