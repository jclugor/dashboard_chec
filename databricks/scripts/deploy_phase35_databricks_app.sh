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
APP_CHATBOT_SKILLS_VOLUME_RESOURCE_KEY="${APP_CHATBOT_SKILLS_VOLUME_RESOURCE_KEY:-chatbot_skills_volume}"
APP_CHATBOT_SKILLS_VOLUME_FULL_NAME="${APP_CHATBOT_SKILLS_VOLUME_FULL_NAME:-${APP_CATALOG_NAME:-chec_dbx_demo}.agent_config.skills}"
APP_CHATBOT_SKILLS_VOLUME_DESCRIPTION="${APP_CHATBOT_SKILLS_VOLUME_DESCRIPTION:-Read-only CHEC governed assistant skill files volume}"
DEFAULT_APP_CHATBOT_SKILLS_VOLUME_PATH="dbfs:/Volumes/${APP_CHATBOT_SKILLS_VOLUME_FULL_NAME//./\/}"
APP_CHATBOT_SKILLS_VOLUME_PATH="${APP_CHATBOT_SKILLS_VOLUME_PATH:-${DEFAULT_APP_CHATBOT_SKILLS_VOLUME_PATH}}"
APP_CHATBOT_CONVERSATION_BACKEND="${APP_CHATBOT_CONVERSATION_BACKEND:-databricks_sql}"
APP_CHATBOT_CONVERSATION_SCHEMA="${APP_CHATBOT_CONVERSATION_SCHEMA:-agent}"
APP_CHATBOT_MEMORY_MAX_TURNS="${APP_CHATBOT_MEMORY_MAX_TURNS:-8}"
APP_GEMINI_SECRET_RESOURCE_KEY="${APP_GEMINI_SECRET_RESOURCE_KEY:-gemini_api_key}"
APP_GEMINI_SECRET_SCOPE="${APP_GEMINI_SECRET_SCOPE:-chec_dash_parity}"
APP_GEMINI_SECRET_KEY="${APP_GEMINI_SECRET_KEY:-gemini_api_key}"
APP_GEMINI_SECRET_DESCRIPTION="${APP_GEMINI_SECRET_DESCRIPTION:-Gemini API key for the CHEC technical chatbot}"

export APP_GEMINI_SECRET_RESOURCE_KEY
export APP_CHATBOT_CONVERSATION_BACKEND
export APP_CHATBOT_CONVERSATION_SCHEMA
export APP_CHATBOT_MEMORY_MAX_TURNS

ensure_chatbot_skill_lifecycle_dirs() {
  local lifecycle_dir
  for lifecycle_dir in active draft archive; do
    databricks fs mkdir "${APP_CHATBOT_SKILLS_VOLUME_PATH}/${lifecycle_dir}" >/dev/null
  done
}

setup_chatbot_conversation_tables() {
  if [[ "${APP_CHATBOT_CONVERSATION_BACKEND}" != "databricks_sql" ]]; then
    return 0
  fi
  APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID:-4437a6195e05c59c}" \
  APP_CATALOG_NAME="${APP_CATALOG_NAME:-chec_dbx_demo}" \
  APP_CHATBOT_CONVERSATION_SCHEMA="${APP_CHATBOT_CONVERSATION_SCHEMA}" \
    ./.venv/bin/python databricks/scripts/setup_phase3_conversation_tables.py
}

cd "${REPO_ROOT}"
./.venv/bin/python databricks/scripts/stage_phase35_databricks_app.py
ensure_chatbot_skill_lifecycle_dirs
setup_chatbot_conversation_tables

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
  --arg skills_resource_key "${APP_CHATBOT_SKILLS_VOLUME_RESOURCE_KEY}" \
  --arg skills_resource_description "${APP_CHATBOT_SKILLS_VOLUME_DESCRIPTION}" \
  --arg skills_volume_full_name "${APP_CHATBOT_SKILLS_VOLUME_FULL_NAME}" \
  --arg gemini_resource_key "${APP_GEMINI_SECRET_RESOURCE_KEY}" \
  --arg gemini_resource_description "${APP_GEMINI_SECRET_DESCRIPTION}" \
  --arg gemini_secret_scope "${APP_GEMINI_SECRET_SCOPE}" \
  --arg gemini_secret_key "${APP_GEMINI_SECRET_KEY}" \
  '{
    description: $description,
    resources: (
      ((.resources // []) | map(select(.name != $resource_key and .name != $skills_resource_key and .name != $gemini_resource_key)))
      + [{
        name: $resource_key,
        description: $resource_description,
        uc_securable: {
          securable_type: "VOLUME",
          securable_full_name: $volume_full_name,
          permission: "READ_VOLUME"
        }
      }]
      + [{
        name: $skills_resource_key,
        description: $skills_resource_description,
        uc_securable: {
          securable_type: "VOLUME",
          securable_full_name: $skills_volume_full_name,
          permission: "READ_VOLUME"
        }
      }]
      + (if ($gemini_resource_key != "" and $gemini_secret_scope != "" and $gemini_secret_key != "") then [{
        name: $gemini_resource_key,
        description: $gemini_resource_description,
        secret: {
          scope: $gemini_secret_scope,
          key: $gemini_secret_key,
          permission: "READ"
        }
      }] else [] end)
    )
  }' <<< "${APP_JSON}")"
databricks apps update "${APP_NAME}" --json "${APP_RESOURCE_UPDATE_JSON}" >/dev/null

APP_JSON="$(databricks apps get "${APP_NAME}" -o json)"
COMPUTE_STATE="$(jq -r '.compute_status.state // empty' <<< "${APP_JSON}")"
if [[ "${COMPUTE_STATE}" != "ACTIVE" ]]; then
  databricks apps start "${APP_NAME}" >/dev/null
fi

databricks workspace delete "${WORKSPACE_SOURCE_PATH}" --recursive >/dev/null 2>&1 || true
databricks workspace import-dir "${BUILD_APP_DIR}" "${WORKSPACE_SOURCE_PATH}" --overwrite
databricks apps deploy "${APP_NAME}" \
  --source-code-path "${WORKSPACE_SOURCE_PATH}" \
  --mode SNAPSHOT
databricks apps start "${APP_NAME}"

echo "Deployed Databricks app '${APP_NAME}' from ${WORKSPACE_SOURCE_PATH}"
