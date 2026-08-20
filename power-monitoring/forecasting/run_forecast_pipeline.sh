#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="/home/cx-002/cx002-power-poc"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python"
ENV_FILE="$PROJECT_DIR/collector.env"

cd "$PROJECT_DIR"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "Virtual-environment Python not found: $VENV_PYTHON"
    exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Environment file not found: $ENV_FILE"
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

START_TIME=$(date --iso-8601=seconds)

echo "=================================================="
echo "Starting CX-002 forecasting pipeline"
echo "Started at: $START_TIME"
echo "=================================================="

echo
echo "Step 1/4: Evaluating matured forecasts..."

"$VENV_PYTHON" \
    "$PROJECT_DIR/forecasting/evaluate_forecasts.py"

echo "Forecast evaluation completed successfully."

echo
echo "Step 2/4: Evaluating forecast alerts..."

"$VENV_PYTHON" \
    "$PROJECT_DIR/forecasting/forecast_alert_engine.py"

echo "Forecast alert evaluation completed successfully."

echo
echo "Step 3/4: Refreshing five-minute training data..."

"$VENV_PYTHON" \
    "$PROJECT_DIR/forecasting/forecast_data_generator.py"

echo "Forecast training dataset refreshed successfully."

echo
echo "Step 4/4: Training Prophet and publishing forecast..."

"$VENV_PYTHON" \
    "$PROJECT_DIR/forecasting/train_prophet.py"

echo "Forecast generated and published successfully."


END_TIME=$(date --iso-8601=seconds)

echo
echo "=================================================="
echo "CX-002 forecasting pipeline completed Successfully"
echo "Completed at: $END_TIME"
echo "=================================================="
