#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATABRICKS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DATABRICKS_DIR}/.." && pwd)"

APP_NAME="${APP_NAME:-chec-dash-parity}"
APP_DESCRIPTION="${APP_DESCRIPTION:-CHEC Databricks App for full Dash parity}"
APP_COMPUTE_SIZE="${APP_COMPUTE_SIZE:-MEDIUM}"
WORKSPACE_SOURCE_PATH="${WORKSPACE_SOURCE_PATH:-/Workspace/Users/$(databricks current-user me -o json | jq -r '.userName')/.apps/${APP_NAME}}"
BUILD_APP_DIR="${DATABRICKS_DIR}/build/chec_dash_parity"

cd "${REPO_ROOT}"
./.venv/bin/python databricks/scripts/stage_phase35_databricks_app.py

if ! databricks apps get "${APP_NAME}" -o json >/dev/null 2>&1; then
  databricks apps create "${APP_NAME}" \
    --description "${APP_DESCRIPTION}" \
    --compute-size "${APP_COMPUTE_SIZE}"
fi

databricks workspace import-dir "${BUILD_APP_DIR}" "${WORKSPACE_SOURCE_PATH}" --overwrite
databricks apps deploy "${APP_NAME}" \
  --source-code-path "${WORKSPACE_SOURCE_PATH}" \
  --mode SNAPSHOT
databricks apps start "${APP_NAME}"

echo "Deployed Databricks app '${APP_NAME}' from ${WORKSPACE_SOURCE_PATH}"
