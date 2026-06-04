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
APP_CHATBOT_CONTEXT_TOOLS_SCHEMA="${APP_CHATBOT_CONTEXT_TOOLS_SCHEMA:-agent_tools}"
APP_CHATBOT_MEMORY_MAX_TURNS="${APP_CHATBOT_MEMORY_MAX_TURNS:-8}"
APP_LLM_PROVIDER="${APP_LLM_PROVIDER:-databricks_model_serving}"
APP_LLM_ENDPOINT_NAME="${APP_LLM_ENDPOINT_NAME:-databricks-qwen3-next-80b-a3b-instruct}"
APP_LLM_ENDPOINT_RESOURCE_KEY="${APP_LLM_ENDPOINT_RESOURCE_KEY:-chatbot_llm_endpoint}"
APP_LLM_ENDPOINT_DESCRIPTION="${APP_LLM_ENDPOINT_DESCRIPTION:-CHEC chatbot Databricks Model Serving endpoint}"
APP_LLM_MAX_TOKENS="${APP_LLM_MAX_TOKENS:-1200}"
APP_LLM_TEMPERATURE="${APP_LLM_TEMPERATURE:-0.2}"
APP_RETRIEVER_BACKEND="${APP_RETRIEVER_BACKEND:-databricks_ai_search}"
APP_AI_SEARCH_ENDPOINT_NAME="${APP_AI_SEARCH_ENDPOINT_NAME:-chec-agent-search}"
APP_AI_SEARCH_INDEX_FULL_NAME="${APP_AI_SEARCH_INDEX_FULL_NAME:-${APP_CATALOG_NAME:-chec_dbx_demo}.gold.technical_doc_chunks_current_index}"
APP_AI_SEARCH_INDEX_RESOURCE_KEY="${APP_AI_SEARCH_INDEX_RESOURCE_KEY:-chatbot_ai_search_index}"
APP_AI_SEARCH_INDEX_DESCRIPTION="${APP_AI_SEARCH_INDEX_DESCRIPTION:-Read-only CHEC chatbot technical document AI Search index}"
APP_AI_SEARCH_TOP_K="${APP_AI_SEARCH_TOP_K:-8}"
APP_AI_SEARCH_QUERY_TYPE="${APP_AI_SEARCH_QUERY_TYPE:-hybrid}"
APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME="${APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME:-databricks-qwen3-embedding-0-6b}"
APP_AI_SEARCH_ENDPOINT_TYPE="${APP_AI_SEARCH_ENDPOINT_TYPE:-STANDARD}"
APP_GEMINI_SECRET_RESOURCE_KEY="${APP_GEMINI_SECRET_RESOURCE_KEY:-gemini_api_key}"
APP_GEMINI_SECRET_SCOPE="${APP_GEMINI_SECRET_SCOPE:-chec_dash_parity}"
APP_GEMINI_SECRET_KEY="${APP_GEMINI_SECRET_KEY:-gemini_api_key}"
APP_GEMINI_SECRET_DESCRIPTION="${APP_GEMINI_SECRET_DESCRIPTION:-Gemini API key for the CHEC technical chatbot}"

export APP_GEMINI_SECRET_RESOURCE_KEY
export APP_LLM_PROVIDER
export APP_LLM_ENDPOINT_RESOURCE_KEY
export APP_LLM_MAX_TOKENS
export APP_LLM_TEMPERATURE
export APP_CHATBOT_CONVERSATION_BACKEND
export APP_CHATBOT_CONVERSATION_SCHEMA
export APP_CHATBOT_CONTEXT_TOOLS_SCHEMA
export APP_CHATBOT_MEMORY_MAX_TURNS
export APP_RETRIEVER_BACKEND
export APP_AI_SEARCH_ENDPOINT_NAME
export APP_AI_SEARCH_INDEX_RESOURCE_KEY
export APP_AI_SEARCH_TOP_K
export APP_AI_SEARCH_QUERY_TYPE
export APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME
export APP_AI_SEARCH_ENDPOINT_TYPE

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

setup_chatbot_context_tools() {
  APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID:-4437a6195e05c59c}" \
  APP_CATALOG_NAME="${APP_CATALOG_NAME:-chec_dbx_demo}" \
  APP_CHATBOT_CONTEXT_TOOLS_SCHEMA="${APP_CHATBOT_CONTEXT_TOOLS_SCHEMA}" \
    ./.venv/bin/python databricks/scripts/setup_phase4_context_tools.py
}

setup_chatbot_ai_search() {
  if [[ "${APP_RETRIEVER_BACKEND}" != "databricks_ai_search" ]]; then
    return 0
  fi
  APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID:-4437a6195e05c59c}" \
  APP_CATALOG_NAME="${APP_CATALOG_NAME:-chec_dbx_demo}" \
  APP_SOURCE_VOLUME_NAME="${APP_SOURCE_VOLUME_NAME:-source_files}" \
  APP_AI_SEARCH_ENDPOINT_NAME="${APP_AI_SEARCH_ENDPOINT_NAME}" \
  APP_AI_SEARCH_INDEX_FULL_NAME="${APP_AI_SEARCH_INDEX_FULL_NAME}" \
  APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME="${APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME}" \
  APP_AI_SEARCH_ENDPOINT_TYPE="${APP_AI_SEARCH_ENDPOINT_TYPE}" \
  APP_AI_SEARCH_QUERY_TYPE="${APP_AI_SEARCH_QUERY_TYPE}" \
    ./.venv/bin/python databricks/scripts/setup_phase5_ai_search.py
}

cd "${REPO_ROOT}"
./.venv/bin/python databricks/scripts/stage_phase35_databricks_app.py
ensure_chatbot_skill_lifecycle_dirs
setup_chatbot_conversation_tables
setup_chatbot_context_tools
setup_chatbot_ai_search

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
  --arg llm_endpoint_resource_key "${APP_LLM_ENDPOINT_RESOURCE_KEY}" \
  --arg llm_endpoint_resource_description "${APP_LLM_ENDPOINT_DESCRIPTION}" \
  --arg llm_endpoint_name "${APP_LLM_ENDPOINT_NAME}" \
  --arg ai_search_resource_key "${APP_AI_SEARCH_INDEX_RESOURCE_KEY}" \
  --arg ai_search_resource_description "${APP_AI_SEARCH_INDEX_DESCRIPTION}" \
  --arg ai_search_index_full_name "${APP_AI_SEARCH_INDEX_FULL_NAME}" \
  --arg gemini_resource_key "${APP_GEMINI_SECRET_RESOURCE_KEY}" \
  --arg gemini_resource_description "${APP_GEMINI_SECRET_DESCRIPTION}" \
  --arg gemini_secret_scope "${APP_GEMINI_SECRET_SCOPE}" \
  --arg gemini_secret_key "${APP_GEMINI_SECRET_KEY}" \
  '{
    description: $description,
    resources: (
      ((.resources // []) | map(select(
        .name != $resource_key
        and .name != $skills_resource_key
        and .name != $llm_endpoint_resource_key
        and .name != $ai_search_resource_key
        and .name != $gemini_resource_key
      )))
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
      + (if ($llm_endpoint_resource_key != "" and $llm_endpoint_name != "") then [{
        name: $llm_endpoint_resource_key,
        description: $llm_endpoint_resource_description,
        serving_endpoint: {
          name: $llm_endpoint_name,
          permission: "CAN_QUERY"
        }
      }] else [] end)
      + [{
        name: $ai_search_resource_key,
        description: $ai_search_resource_description,
        uc_securable: {
          securable_type: "TABLE",
          securable_full_name: $ai_search_index_full_name,
          permission: "SELECT"
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
