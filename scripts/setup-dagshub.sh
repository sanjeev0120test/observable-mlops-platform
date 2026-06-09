#!/usr/bin/env bash
# Configure DagsHub as the MLflow tracking server and DVC remote.
# Must be called at the start of any workflow job that trains models or logs experiments.
#
# Required env vars:
#   DAGSHUB_TOKEN  — DagsHub personal access token (set as GitHub Actions secret)
#   DAGSHUB_REPO   — <owner>/<repo-name> on DagsHub (default: same as GH repo)
#
# Optional env vars:
#   DAGSHUB_HOST   — DagsHub base URL (default: https://dagshub.com)

set -euo pipefail

DAGSHUB_TOKEN="${DAGSHUB_TOKEN:-}"
DAGSHUB_REPO="${DAGSHUB_REPO:-${GITHUB_REPOSITORY:-observable-mlops/observable-mlops-platform}}"
DAGSHUB_HOST="${DAGSHUB_HOST:-https://dagshub.com}"

if [ -z "$DAGSHUB_TOKEN" ]; then
    echo "[setup-dagshub] DAGSHUB_TOKEN not set — using local MLflow (sqlite:///mlruns/mlflow.db)"
    export MLFLOW_TRACKING_URI="sqlite:///mlruns/mlflow.db"
    export DVC_REMOTE_URL="local:///tmp/dvc-remote"
    mkdir -p mlruns /tmp/dvc-remote
    dvc remote add --force default /tmp/dvc-remote 2>/dev/null || true
    echo "[setup-dagshub] Local MLflow + DVC configured (no persistence across runs)"
    exit 0
fi

echo "[setup-dagshub] Configuring DagsHub backend: $DAGSHUB_HOST/$DAGSHUB_REPO"

# MLflow tracking URI
export MLFLOW_TRACKING_URI="${DAGSHUB_HOST}/${DAGSHUB_REPO}.mlflow"
export MLFLOW_TRACKING_USERNAME="${DAGSHUB_TOKEN}"
export MLFLOW_TRACKING_PASSWORD="${DAGSHUB_TOKEN}"

# DVC remote
DVC_REMOTE="${DAGSHUB_HOST}/${DAGSHUB_REPO}.dvc"
dvc remote add --force dagshub "${DVC_REMOTE}" 2>/dev/null || \
    dvc remote modify dagshub url "${DVC_REMOTE}"
dvc remote modify dagshub --local auth basic
dvc remote modify dagshub --local user "${DAGSHUB_TOKEN}"
dvc remote modify dagshub --local password "${DAGSHUB_TOKEN}"
dvc remote default dagshub

# Write to GITHUB_ENV so subsequent steps inherit these
if [ -n "${GITHUB_ENV:-}" ]; then
    echo "MLFLOW_TRACKING_URI=${MLFLOW_TRACKING_URI}" >> "$GITHUB_ENV"
    echo "MLFLOW_TRACKING_USERNAME=${DAGSHUB_TOKEN}" >> "$GITHUB_ENV"
    echo "MLFLOW_TRACKING_PASSWORD=${DAGSHUB_TOKEN}" >> "$GITHUB_ENV"
fi

echo "[setup-dagshub] Done."
echo "[setup-dagshub]   MLFLOW_TRACKING_URI=${MLFLOW_TRACKING_URI}"
echo "[setup-dagshub]   DVC remote: dagshub → ${DVC_REMOTE}"
