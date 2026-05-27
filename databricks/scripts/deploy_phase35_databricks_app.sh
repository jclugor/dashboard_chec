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
APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY="${APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY:-chatbot_corpus_volume}"
APP_CHATBOT_CORPUS_VOLUME_FULL_NAME="${APP_CHATBOT_CORPUS_VOLUME_FULL_NAME:-${APP_CATALOG_NAME:-chec_dbx_demo}.raw.${APP_SOURCE_VOLUME_NAME:-source_files}}"
APP_CHATBOT_CORPUS_VOLUME_DESCRIPTION="${APP_CHATBOT_CORPUS_VOLUME_DESCRIPTION:-Read-only CHEC chatbot corpus and source documents volume}"

cd "${REPO_ROOT}"
./.venv/bin/python databricks/scripts/stage_phase35_databricks_app.py

if ! databricks apps get "${APP_NAME}" -o json >/dev/null 2>&1; then
  databricks apps create "${APP_NAME}" \
    --description "${APP_DESCRIPTION}" \
    --compute-size "${APP_COMPUTE_SIZE}"
fi

APP_JSON="$(databricks apps get "${APP_NAME}" -o json)"
APP_RESOURCE_UPDATE_JSON="$(jq -c \
  --arg description "${APP_DESCRIPTION}" \
  --arg resource_key "${APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY}" \
  --arg resource_description "${APP_CHATBOT_CORPUS_VOLUME_DESCRIPTION}" \
  --arg volume_full_name "${APP_CHATBOT_CORPUS_VOLUME_FULL_NAME}" \
  '{
    description: $description,
    resources: (((.resources // []) | map(select(.name != $resource_key))) + [{
      name: $resource_key,
      description: $resource_description,
      uc_securable: {
        securable_type: "VOLUME",
        securable_full_name: $volume_full_name,
        permission: "READ_VOLUME"
      }
    }])
  }' <<< "${APP_JSON}")"
databricks apps update "${APP_NAME}" --json "${APP_RESOURCE_UPDATE_JSON}" >/dev/null

databricks workspace delete "${WORKSPACE_SOURCE_PATH}" --recursive >/dev/null 2>&1 || true
databricks workspace import-dir "${BUILD_APP_DIR}" "${WORKSPACE_SOURCE_PATH}" --overwrite
databricks apps deploy "${APP_NAME}" \
  --source-code-path "${WORKSPACE_SOURCE_PATH}" \
  --mode SNAPSHOT
databricks apps start "${APP_NAME}"

echo "Deployed Databricks app '${APP_NAME}' from ${WORKSPACE_SOURCE_PATH}"
