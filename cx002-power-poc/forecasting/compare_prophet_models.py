from __future__ import annotations

import itertools
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from prophet import Prophet
from prophet.diagnostics import cross_validation, performance_metrics


PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / "collector.env"
OUTPUT_DIR = PROJECT_DIR / "forecasting" / "model_comparison"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(ENV_FILE)

ES_ENDPOINT = os.getenv("ES_ENDPOINT")
ES_API_KEY = os.getenv("ES_API_KEY")

TRAINING_INDEX = os.getenv(
    "FORECAST_TRAINING_INDEX",
    "capstone-cx002-forecast-data",
)

NODE_NAME = os.getenv(
    "FORECAST_NODE_NAME",
    "cx-002",
)

TARGET_FIELD = os.getenv(
    "FORECAST_TARGET_FIELD",
    "actual_power_watts",
)

MODEL_COMPARISON_INDEX = os.getenv(
    "FORECAST_MODEL_COMPARISON_INDEX",
    "capstone-cx002-model-comparison",
)

TRAINING_DAYS = int(
    os.getenv("FORECAST_TRAINING_DAYS", "37")
)

MIN_SAMPLE_COUNT = int(
    os.getenv("FORECAST_MIN_SAMPLE_COUNT", "10")
)

PAGE_SIZE = 1000

INTERVAL_WIDTHS = [0.95, 0.99]
CHANGEPOINT_PRIOR_SCALES = [0.05, 0.10]
SEASONALITY_PRIOR_SCALES = [10.0]

# Cross-validation windows.
# These values assume roughly 37 days of five-minute training data.
CV_INITIAL = "21 days"
CV_PERIOD = "3 days"
CV_HORIZON = "1 day"

# Desired empirical interval coverage.
TARGET_COVERAGE = 0.95

# Avoid rewarding excessively wide intervals.
MAX_ACCEPTABLE_INTERVAL_WIDTH_WATTS = 8.0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_client() -> Elasticsearch:
    if not ES_ENDPOINT:
        raise ValueError("ES_ENDPOINT is missing from collector.env.")

    if not ES_API_KEY:
        raise ValueError("ES_API_KEY is missing from collector.env.")

    client = Elasticsearch(
        ES_ENDPOINT,
        api_key=ES_API_KEY,
        request_timeout=180,
    )

    result = client.count(index=TRAINING_INDEX)

    print(
        "Elasticsearch connection successful. "
        f"Training documents: {result['count']}"
    )

    return client


def load_training_data(
    client: Elasticsearch,
) -> pd.DataFrame:
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
                            "gte": f"now-{TRAINING_DAYS}d"
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

    records: list[dict[str, Any]] = []
    search_after: list[Any] | None = None

    while True:
        request: dict[str, Any] = {
            "index": TRAINING_INDEX,
            "size": PAGE_SIZE,
            "query": query,
            "_source": [
                "@timestamp",
                TARGET_FIELD,
            ],
            "sort": [
                {
                    "@timestamp": {
                        "order": "asc",
                        "unmapped_type": "date",
                    }
                }
            ],
        }

        if search_after is not None:
            request["search_after"] = search_after

        response = client.search(**request)
        hits = response.get("hits", {}).get("hits", [])

        if not hits:
            break

        for hit in hits:
            source = hit.get("_source", {})

            timestamp = source.get("@timestamp")
            value = source.get(TARGET_FIELD)

            if timestamp is None or value is None:
                continue

            records.append(
                {
                    "ds": timestamp,
                    "y": float(value),
                }
            )

        search_after = hits[-1].get("sort")

        print(f"Loaded {len(records)} training points")

        if len(hits) < PAGE_SIZE:
            break

    frame = pd.DataFrame(records)

    if frame.empty:
        raise ValueError(
            "No training records matched the configured filters."
        )

    frame["ds"] = pd.to_datetime(
        frame["ds"],
        utc=True,
    ).dt.tz_localize(None)

    frame = (
        frame
        .dropna()
        .drop_duplicates(subset=["ds"])
        .sort_values("ds")
        .reset_index(drop=True)
    )

    return frame


def empirical_interval_metrics(
    cv_frame: pd.DataFrame,
) -> dict[str, float]:
    valid = cv_frame.dropna(
        subset=[
            "y",
            "yhat",
            "yhat_lower",
            "yhat_upper",
        ]
    ).copy()

    inside = (
        (valid["y"] >= valid["yhat_lower"])
        & (valid["y"] <= valid["yhat_upper"])
    )

    interval_width = (
        valid["yhat_upper"] - valid["yhat_lower"]
    )

    return {
        "interval_coverage": float(inside.mean()),
        "average_interval_width_watts":
            float(interval_width.mean()),
        "median_interval_width_watts":
            float(interval_width.median()),
    }


def calculate_accuracy_metrics(
    cv_frame: pd.DataFrame,
) -> dict[str, float]:
    valid = cv_frame.dropna(
        subset=["y", "yhat"]
    ).copy()

    errors = valid["y"] - valid["yhat"]
    absolute_errors = errors.abs()
    squared_errors = errors.pow(2)

    nonzero_actual = valid["y"].abs() > 1e-9

    percentage_errors = (
        absolute_errors[nonzero_actual]
        / valid.loc[nonzero_actual, "y"].abs()
    ) * 100

    denominator = (
        valid["y"].abs()
        + valid["yhat"].abs()
    )

    valid_smape = denominator > 1e-9

    smape = (
        2
        * absolute_errors[valid_smape]
        / denominator[valid_smape]
    ) * 100

    return {
        "mae_watts":
            float(absolute_errors.mean()),
        "rmse_watts":
            float(math.sqrt(squared_errors.mean())),
        "mape_percent":
            float(percentage_errors.mean()),
        "smape_percent":
            float(smape.mean()),
    }


def calculate_selection_score(
    metrics: dict[str, float],
) -> float:
    """
    Lower score is better.

    Priorities:
    - low point forecast error;
    - coverage close to 95%;
    - avoid excessively wide intervals.
    """
    mae = metrics["mae_watts"]
    rmse = metrics["rmse_watts"]
    mape = metrics["mape_percent"]

    coverage = metrics["interval_coverage"]
    interval_width = metrics[
        "average_interval_width_watts"
    ]

    coverage_penalty = (
        abs(coverage - TARGET_COVERAGE) * 10
    )

    excessive_width_penalty = max(
        0.0,
        interval_width
        - MAX_ACCEPTABLE_INTERVAL_WIDTH_WATTS,
    )

    return float(
        (mae * 0.30)
        + (rmse * 0.30)
        + ((mape / 100) * 0.20)
        + (coverage_penalty * 0.15)
        + (excessive_width_penalty * 0.05)
    )


def evaluate_candidate(
    training_frame: pd.DataFrame,
    parameters: dict[str, float],
    candidate_number: int,
    total_candidates: int,
) -> dict[str, Any]:
    print()
    print(
        f"Candidate {candidate_number}/"
        f"{total_candidates}"
    )
    print(json.dumps(parameters, indent=2))

    model = Prophet(
        growth="linear",
        interval_width=
            parameters["interval_width"],
        daily_seasonality=True,
        weekly_seasonality=True,
        yearly_seasonality=False,
        seasonality_mode="additive",
        changepoint_prior_scale=
            parameters["changepoint_prior_scale"],
        seasonality_prior_scale=
            parameters["seasonality_prior_scale"],
    )

    model.fit(training_frame)

    cv_frame = cross_validation(
        model,
        initial=CV_INITIAL,
        period=CV_PERIOD,
        horizon=CV_HORIZON,
        parallel=None,
    )

    prophet_metrics = performance_metrics(
        cv_frame,
        rolling_window=1,
    )

    accuracy = calculate_accuracy_metrics(
        cv_frame
    )

    interval_metrics = empirical_interval_metrics(
        cv_frame
    )

    result: dict[str, Any] = {
        **parameters,
        **accuracy,
        **interval_metrics,
        "prophet_rmse":
            float(prophet_metrics["rmse"].iloc[-1]),
        "prophet_mae":
            float(prophet_metrics["mae"].iloc[-1]),
        "prophet_mape":
            float(prophet_metrics["mape"].iloc[-1]),
        "cross_validation_rows":
            int(len(cv_frame)),
    }

    result["coverage_percent"] = (
        result["interval_coverage"] * 100
    )

    result["selection_score"] = (
        calculate_selection_score(result)
    )

    print(
        "MAE: "
        f"{result['mae_watts']:.4f} W"
    )
    print(
        "RMSE: "
        f"{result['rmse_watts']:.4f} W"
    )
    print(
        "MAPE: "
        f"{result['mape_percent']:.2f}%"
    )
    print(
        "Coverage: "
        f"{result['coverage_percent']:.2f}%"
    )
    print(
        "Average interval width: "
        f"{result['average_interval_width_watts']:.4f} W"
    )
    print(
        "Selection score: "
        f"{result['selection_score']:.6f}"
    )

    return result


def write_results(
    results_frame: pd.DataFrame,
) -> tuple[Path, Path]:
    timestamp = utc_now().strftime(
        "%Y%m%dT%H%M%SZ"
    )

    csv_path = (
        OUTPUT_DIR
        / f"prophet_comparison_{timestamp}.csv"
    )

    json_path = (
        OUTPUT_DIR
        / f"prophet_comparison_{timestamp}.json"
    )

    results_frame.to_csv(
        csv_path,
        index=False,
    )

    results_frame.to_json(
        json_path,
        orient="records",
        indent=2,
    )

    return csv_path, json_path


def index_results(
    client: Elasticsearch,
    results_frame: pd.DataFrame,
    comparison_run_id: str,
) -> None:
    generated_at = utc_now().isoformat()

    for rank, row in results_frame.iterrows():
        document = row.to_dict()

        document.update(
            {
                "@timestamp": generated_at,
                "comparison_run_id":
                    comparison_run_id,
                "candidate_rank":
                    int(rank + 1),
                "is_recommended":
                    bool(rank == 0),
                "node_name":
                    NODE_NAME,
                "training_index":
                    TRAINING_INDEX,
                "training_days":
                    TRAINING_DAYS,
                "cv_initial":
                    CV_INITIAL,
                "cv_period":
                    CV_PERIOD,
                "cv_horizon":
                    CV_HORIZON,
                "source":
                    "ttg_prophet_model_comparison",
            }
        )

        document_id = (
            f"{comparison_run_id}-"
            f"candidate-{rank + 1:03d}"
        )

        client.index(
            index=MODEL_COMPARISON_INDEX,
            id=document_id,
            document=document,
        )


def print_rankings(
    results_frame: pd.DataFrame,
) -> None:
    columns = [
        "interval_width",
        "changepoint_prior_scale",
        "seasonality_prior_scale",
        "mae_watts",
        "rmse_watts",
        "mape_percent",
        "coverage_percent",
        "average_interval_width_watts",
        "selection_score",
    ]

    print()
    print("Top candidate models")
    print(
        results_frame[columns]
        .head(10)
        .to_string(index=False)
    )

    best = results_frame.iloc[0]

    print()
    print("Recommended Prophet configuration")
    print(
        "interval_width="
        f"{best['interval_width']}"
    )
    print(
        "changepoint_prior_scale="
        f"{best['changepoint_prior_scale']}"
    )
    print(
        "seasonality_prior_scale="
        f"{best['seasonality_prior_scale']}"
    )
    print(
        "Expected MAE="
        f"{best['mae_watts']:.4f} W"
    )
    print(
        "Expected RMSE="
        f"{best['rmse_watts']:.4f} W"
    )
    print(
        "Expected MAPE="
        f"{best['mape_percent']:.2f}%"
    )
    print(
        "Expected coverage="
        f"{best['coverage_percent']:.2f}%"
    )
    print(
        "Average interval width="
        f"{best['average_interval_width_watts']:.4f} W"
    )


def main() -> None:
    try:
        print("Starting Prophet model comparison")
        print(f"Training index: {TRAINING_INDEX}")
        print(f"Node: {NODE_NAME}")

        client = get_client()
        training_frame = load_training_data(
            client
        )

        print()
        print("Training data summary")
        print(f"Points: {len(training_frame)}")
        print(
            f"Start: {training_frame['ds'].min()}"
        )
        print(
            f"End: {training_frame['ds'].max()}"
        )

        combinations = list(
            itertools.product(
                INTERVAL_WIDTHS,
                CHANGEPOINT_PRIOR_SCALES,
                SEASONALITY_PRIOR_SCALES,
            )
        )

        total_candidates = len(combinations)
        results: list[dict[str, Any]] = []

        for candidate_number, combination in enumerate(
            combinations,
            start=1,
        ):
            parameters = {
                "interval_width": combination[0],
                "changepoint_prior_scale":
                    combination[1],
                "seasonality_prior_scale":
                    combination[2],
            }

            try:
                result = evaluate_candidate(
                    training_frame,
                    parameters,
                    candidate_number,
                    total_candidates,
                )

                results.append(result)

            except Exception as error:
                print(
                    "Candidate failed: "
                    f"{type(error).__name__}: "
                    f"{error}"
                )

        if not results:
            raise RuntimeError(
                "All candidate models failed."
            )

        results_frame = pd.DataFrame(results)

        results_frame = (
            results_frame
            .sort_values(
                by=[
                    "selection_score",
                    "mae_watts",
                    "rmse_watts",
                ],
                ascending=True,
            )
            .reset_index(drop=True)
        )

        comparison_run_id = (
            utc_now().strftime("%Y%m%dT%H%M%SZ")
        )

        csv_path, json_path = write_results(
            results_frame
        )

        index_results(
            client,
            results_frame,
            comparison_run_id,
        )

        print_rankings(results_frame)

        print()
        print(f"CSV results: {csv_path}")
        print(f"JSON results: {json_path}")
        print(
            "Elasticsearch comparison index: "
            f"{MODEL_COMPARISON_INDEX}"
        )

    except KeyboardInterrupt:
        print("Model comparison stopped.")

    except Exception as error:
        print(
            "Model comparison failed: "
            f"{type(error).__name__}: {error}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
