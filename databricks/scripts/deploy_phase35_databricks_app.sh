#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATABRICKS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DATABRICKS_DIR}/.." && pwd)"

APP_NAME="${APP_NAME:-chec-dash-parity}"
APP_DESCRIPTION="${APP_DESCRIPTION:-CHEC Databricks App for full Dash parity}"
APP_COMPUTE_SIZE="${APP_COMPUTE_SIZE:-MEDIUM}"
WORKSPACE_SOURCE_PATH="${WORKSPACE_SOURCE_PATH:-}"
BUILD_APP_DIR="${DATABRICKS_DIR}/build/chec_dash_parity"
APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY="${APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY:-chatbot_corpus_volume}"
APP_CHATBOT_CORPUS_VOLUME_FULL_NAME="${APP_CHATBOT_CORPUS_VOLUME_FULL_NAME:-${APP_CATALOG_NAME:-chec_dbx_demo}.raw.${APP_SOURCE_VOLUME_NAME:-source_files}}"
APP_CHATBOT_CORPUS_VOLUME_DESCRIPTION="${APP_CHATBOT_CORPUS_VOLUME_DESCRIPTION:-Read-only CHEC chatbot corpus and source documents volume}"
APP_CHATBOT_SKILLS_VOLUME_RESOURCE_KEY="${APP_CHATBOT_SKILLS_VOLUME_RESOURCE_KEY:-chatbot_skills_volume}"
APP_CHATBOT_SKILLS_VOLUME_FULL_NAME="${APP_CHATBOT_SKILLS_VOLUME_FULL_NAME:-${APP_CATALOG_NAME:-chec_dbx_demo}.agent_config.skills}"
APP_CHATBOT_SKILLS_VOLUME_DESCRIPTION="${APP_CHATBOT_SKILLS_VOLUME_DESCRIPTION:-Read-only CHEC governed assistant skill files volume}"
DEFAULT_APP_CHATBOT_SKILLS_VOLUME_PATH="dbfs:/Volumes/${APP_CHATBOT_SKILLS_VOLUME_FULL_NAME//./\/}"
APP_CHATBOT_SKILLS_VOLUME_PATH="${APP_CHATBOT_SKILLS_VOLUME_PATH:-${DEFAULT_APP_CHATBOT_SKILLS_VOLUME_PATH}}"
APP_CHATBOT_ENABLED="${APP_CHATBOT_ENABLED:-true}"
APP_CHATBOT_CONVERSATION_BACKEND="${APP_CHATBOT_CONVERSATION_BACKEND:-databricks_sql}"
APP_CHATBOT_CONVERSATION_SCHEMA="${APP_CHATBOT_CONVERSATION_SCHEMA:-agent}"
APP_CHATBOT_CONTEXT_TOOLS_SCHEMA="${APP_CHATBOT_CONTEXT_TOOLS_SCHEMA:-agent_tools}"
APP_CHATBOT_MEMORY_MAX_TURNS="${APP_CHATBOT_MEMORY_MAX_TURNS:-8}"
APP_LLM_PROVIDER="${APP_LLM_PROVIDER:-databricks_model_serving}"
APP_MODEL_BACKEND="${APP_MODEL_BACKEND:-mock}"
APP_DATABRICKS_MODEL_ENDPOINT="${APP_DATABRICKS_MODEL_ENDPOINT:-}"
APP_LLM_ENDPOINT_NAME="${APP_LLM_ENDPOINT_NAME:-databricks-qwen3-next-80b-a3b-instruct}"
APP_LLM_ENDPOINT_RESOURCE_KEY="${APP_LLM_ENDPOINT_RESOURCE_KEY:-chatbot_llm_endpoint}"
APP_LLM_ENDPOINT_DESCRIPTION="${APP_LLM_ENDPOINT_DESCRIPTION:-CHEC chatbot Databricks Model Serving endpoint}"
APP_LLM_ROUTING_ENABLED="${APP_LLM_ROUTING_ENABLED:-false}"
APP_LLM_DEFAULT_TIER="${APP_LLM_DEFAULT_TIER:-medium}"
APP_LLM_CHEAP_ENDPOINT_NAME="${APP_LLM_CHEAP_ENDPOINT_NAME:-}"
APP_LLM_MEDIUM_ENDPOINT_NAME="${APP_LLM_MEDIUM_ENDPOINT_NAME:-}"
APP_LLM_BEST_ENDPOINT_NAME="${APP_LLM_BEST_ENDPOINT_NAME:-}"
APP_LLM_ALLOW_BEST_TIER="${APP_LLM_ALLOW_BEST_TIER:-false}"
APP_LLM_MAX_EXPENSIVE_CALLS_PER_REQUEST="${APP_LLM_MAX_EXPENSIVE_CALLS_PER_REQUEST:-1}"
APP_LLM_ROUTE_SIMPLE_TO_CHEAP="${APP_LLM_ROUTE_SIMPLE_TO_CHEAP:-true}"
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
APP_CHATBOT_OBSERVABILITY_ENABLED="${APP_CHATBOT_OBSERVABILITY_ENABLED:-true}"
APP_CHATBOT_TELEMETRY_SCHEMA="${APP_CHATBOT_TELEMETRY_SCHEMA:-agent_observability}"
APP_CHATBOT_EVAL_REPORT_ONLY="${APP_CHATBOT_EVAL_REPORT_ONLY:-true}"
APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED="${APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED:-false}"
APP_CHATBOT_EVAL_ENFORCE="${APP_CHATBOT_EVAL_ENFORCE:-false}"
APP_MLFLOW_TRACKING_URI="${APP_MLFLOW_TRACKING_URI:-databricks}"
APP_MLFLOW_EXPERIMENT_NAME="${APP_MLFLOW_EXPERIMENT_NAME:-/Shared/chec_dash_parity/agent_observability}"
APP_MLFLOW_PROMPT_NAME="${APP_MLFLOW_PROMPT_NAME:-chec_chatbot_answer_prompt}"
APP_MLFLOW_PROMPT_ALIAS="${APP_MLFLOW_PROMPT_ALIAS:-production}"
APP_GEMINI_SECRET_RESOURCE_KEY="${APP_GEMINI_SECRET_RESOURCE_KEY:-}"
APP_GEMINI_SECRET_SCOPE="${APP_GEMINI_SECRET_SCOPE:-chec_dash_parity}"
APP_GEMINI_SECRET_KEY="${APP_GEMINI_SECRET_KEY:-gemini_api_key}"
APP_GEMINI_SECRET_DESCRIPTION="${APP_GEMINI_SECRET_DESCRIPTION:-Gemini API key for the CHEC technical chatbot}"

export APP_GEMINI_SECRET_RESOURCE_KEY
export APP_CHATBOT_ENABLED
export APP_LLM_PROVIDER
export APP_MODEL_BACKEND
export APP_DATABRICKS_MODEL_ENDPOINT
export APP_LLM_ENDPOINT_RESOURCE_KEY
export APP_LLM_ROUTING_ENABLED
export APP_LLM_DEFAULT_TIER
export APP_LLM_CHEAP_ENDPOINT_NAME
export APP_LLM_MEDIUM_ENDPOINT_NAME
export APP_LLM_BEST_ENDPOINT_NAME
export APP_LLM_ALLOW_BEST_TIER
export APP_LLM_MAX_EXPENSIVE_CALLS_PER_REQUEST
export APP_LLM_ROUTE_SIMPLE_TO_CHEAP
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
export APP_CHATBOT_OBSERVABILITY_ENABLED
export APP_CHATBOT_TELEMETRY_SCHEMA
export APP_CHATBOT_EVAL_REPORT_ONLY
export APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED
export APP_CHATBOT_EVAL_ENFORCE
export APP_MLFLOW_TRACKING_URI
export APP_MLFLOW_EXPERIMENT_NAME
export APP_MLFLOW_PROMPT_NAME
export APP_MLFLOW_PROMPT_ALIAS

run_with_retries() {
  local attempt=1
  local max_attempts="${DATABRICKS_CLI_RETRIES:-4}"
  local delay_seconds="${DATABRICKS_CLI_RETRY_DELAY_SECONDS:-5}"
  while true; do
    if "$@"; then
      return 0
    fi
    if (( attempt >= max_attempts )); then
      return 1
    fi
    echo "Retrying Databricks command after transient failure (${attempt}/${max_attempts}): $*" >&2
    sleep "${delay_seconds}"
    attempt=$((attempt + 1))
  done
}

capture_with_retries() {
  local attempt=1
  local max_attempts="${DATABRICKS_CLI_RETRIES:-4}"
  local delay_seconds="${DATABRICKS_CLI_RETRY_DELAY_SECONDS:-5}"
  local output
  local status
  local stderr_file
  while true; do
    stderr_file="$(mktemp)"
    if output="$("$@" 2>"${stderr_file}")"; then
      rm -f "${stderr_file}"
      printf '%s' "${output}"
      return 0
    fi
    status=$?
    cat "${stderr_file}" >&2 || true
    rm -f "${stderr_file}"
    if (( attempt >= max_attempts )); then
      return "${status}"
    fi
    echo "Retrying Databricks command after transient failure (${attempt}/${max_attempts}): $*" >&2
    sleep "${delay_seconds}"
    attempt=$((attempt + 1))
  done
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required environment variable: ${name}" >&2
    echo "Set it directly or run databricks/scripts/fresh_install_databricks.sh to create/reuse a SQL warehouse." >&2
    exit 1
  fi
}

if [[ -z "${WORKSPACE_SOURCE_PATH}" ]]; then
  WORKSPACE_USER="$(capture_with_retries databricks current-user me -o json | jq -r '.userName')"
  WORKSPACE_SOURCE_PATH="/Workspace/Users/${WORKSPACE_USER}/.apps/${APP_NAME}"
fi

ensure_chatbot_skill_lifecycle_dirs() {
  if [[ "${SKIP_CHATBOT_SKILL_LIFECYCLE_DIRS:-false}" == "true" ]]; then
    echo "Skipping governed chatbot skill lifecycle directory check."
    return 0
  fi
  local lifecycle_dir
  for lifecycle_dir in active draft archive knowledge; do
    if databricks fs ls "${APP_CHATBOT_SKILLS_VOLUME_PATH}/${lifecycle_dir}" >/dev/null 2>&1; then
      continue
    fi
    run_with_retries databricks fs mkdir "${APP_CHATBOT_SKILLS_VOLUME_PATH}/${lifecycle_dir}" >/dev/null
  done
}

setup_chatbot_conversation_tables() {
  if [[ "${APP_CHATBOT_CONVERSATION_BACKEND}" != "databricks_sql" ]]; then
    return 0
  fi
  APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID}" \
  APP_CATALOG_NAME="${APP_CATALOG_NAME:-chec_dbx_demo}" \
  APP_CHATBOT_CONVERSATION_SCHEMA="${APP_CHATBOT_CONVERSATION_SCHEMA}" \
    ./.venv/bin/python databricks/scripts/setup_phase3_conversation_tables.py
}

setup_chatbot_context_tools() {
  APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID}" \
  APP_CATALOG_NAME="${APP_CATALOG_NAME:-chec_dbx_demo}" \
  APP_CHATBOT_CONTEXT_TOOLS_SCHEMA="${APP_CHATBOT_CONTEXT_TOOLS_SCHEMA}" \
    ./.venv/bin/python databricks/scripts/setup_phase4_context_tools.py
}

setup_chatbot_ai_search() {
  if [[ "${APP_RETRIEVER_BACKEND}" != "databricks_ai_search" ]]; then
    return 0
  fi
  APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID}" \
  APP_CATALOG_NAME="${APP_CATALOG_NAME:-chec_dbx_demo}" \
  APP_SOURCE_VOLUME_NAME="${APP_SOURCE_VOLUME_NAME:-source_files}" \
  APP_AI_SEARCH_ENDPOINT_NAME="${APP_AI_SEARCH_ENDPOINT_NAME}" \
  APP_AI_SEARCH_INDEX_FULL_NAME="${APP_AI_SEARCH_INDEX_FULL_NAME}" \
  APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME="${APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME}" \
  APP_AI_SEARCH_ENDPOINT_TYPE="${APP_AI_SEARCH_ENDPOINT_TYPE}" \
  APP_AI_SEARCH_QUERY_TYPE="${APP_AI_SEARCH_QUERY_TYPE}" \
    ./.venv/bin/python databricks/scripts/setup_phase5_ai_search.py
}

setup_chatbot_observability() {
  if [[ "${APP_CHATBOT_OBSERVABILITY_ENABLED}" != "true" ]]; then
    return 0
  fi
  APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID}" \
  APP_CATALOG_NAME="${APP_CATALOG_NAME:-chec_dbx_demo}" \
  APP_CHATBOT_TELEMETRY_SCHEMA="${APP_CHATBOT_TELEMETRY_SCHEMA}" \
  APP_CHATBOT_EVAL_REPORT_ONLY="${APP_CHATBOT_EVAL_REPORT_ONLY}" \
  APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED="${APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED}" \
  APP_CHATBOT_EVAL_ENFORCE="${APP_CHATBOT_EVAL_ENFORCE}" \
  APP_MLFLOW_TRACKING_URI="${APP_MLFLOW_TRACKING_URI}" \
  APP_MLFLOW_EXPERIMENT_NAME="${APP_MLFLOW_EXPERIMENT_NAME}" \
  APP_MLFLOW_PROMPT_NAME="${APP_MLFLOW_PROMPT_NAME}" \
  APP_MLFLOW_PROMPT_ALIAS="${APP_MLFLOW_PROMPT_ALIAS}" \
    ./.venv/bin/python databricks/scripts/setup_phase9_observability.py
}

cd "${REPO_ROOT}"
require_env APP_WAREHOUSE_ID
export DATABRICKS_SQL_WAREHOUSE_ID="${DATABRICKS_SQL_WAREHOUSE_ID:-${APP_WAREHOUSE_ID}}"
echo "Deploying Databricks app '${APP_NAME}'"
echo "  Host: ${DATABRICKS_HOST:-<databricks CLI profile default>}"
echo "  Catalog: ${APP_CATALOG_NAME:-chec_dbx_demo}"
echo "  Warehouse: ${APP_WAREHOUSE_ID}"
echo "  Gemini secret resource: ${APP_GEMINI_SECRET_RESOURCE_KEY:-disabled}"
env \
  APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID}" \
  APP_CATALOG_NAME="${APP_CATALOG_NAME:-chec_dbx_demo}" \
  APP_GOLD_SCHEMA="${APP_GOLD_SCHEMA:-gold}" \
  APP_SILVER_SCHEMA="${APP_SILVER_SCHEMA:-silver}" \
  APP_CHATBOT_ENABLED="${APP_CHATBOT_ENABLED}" \
  APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY="${APP_CHATBOT_CORPUS_VOLUME_RESOURCE_KEY}" \
  APP_CHATBOT_CORPUS_SUBDIR="${APP_CHATBOT_CORPUS_SUBDIR:-chatbot_corpus}" \
  APP_CHATBOT_SKILLS_VOLUME_RESOURCE_KEY="${APP_CHATBOT_SKILLS_VOLUME_RESOURCE_KEY}" \
  APP_CHATBOT_SKILLS_SUBDIR="${APP_CHATBOT_SKILLS_SUBDIR:-active}" \
  APP_CHATBOT_RETRIEVAL_TOP_K="${APP_CHATBOT_RETRIEVAL_TOP_K:-5}" \
  APP_CHATBOT_MAX_CONTEXT_CHARS="${APP_CHATBOT_MAX_CONTEXT_CHARS:-12000}" \
  APP_LLM_PROVIDER="${APP_LLM_PROVIDER}" \
  APP_LLM_ENDPOINT_RESOURCE_KEY="${APP_LLM_ENDPOINT_RESOURCE_KEY}" \
  APP_LLM_ROUTING_ENABLED="${APP_LLM_ROUTING_ENABLED}" \
  APP_LLM_DEFAULT_TIER="${APP_LLM_DEFAULT_TIER}" \
  APP_LLM_CHEAP_ENDPOINT_NAME="${APP_LLM_CHEAP_ENDPOINT_NAME}" \
  APP_LLM_MEDIUM_ENDPOINT_NAME="${APP_LLM_MEDIUM_ENDPOINT_NAME}" \
  APP_LLM_BEST_ENDPOINT_NAME="${APP_LLM_BEST_ENDPOINT_NAME}" \
  APP_LLM_ALLOW_BEST_TIER="${APP_LLM_ALLOW_BEST_TIER}" \
  APP_LLM_MAX_EXPENSIVE_CALLS_PER_REQUEST="${APP_LLM_MAX_EXPENSIVE_CALLS_PER_REQUEST}" \
  APP_LLM_ROUTE_SIMPLE_TO_CHEAP="${APP_LLM_ROUTE_SIMPLE_TO_CHEAP}" \
  APP_LLM_MAX_TOKENS="${APP_LLM_MAX_TOKENS}" \
  APP_LLM_TEMPERATURE="${APP_LLM_TEMPERATURE}" \
  APP_SUMMARY_INTERPRETABILITY_ENABLED="${APP_SUMMARY_INTERPRETABILITY_ENABLED:-true}" \
  APP_SUMMARY_INTERPRETABILITY_MAX_POINTS="${APP_SUMMARY_INTERPRETABILITY_MAX_POINTS:-5}" \
  APP_SUMMARY_INTERPRETABILITY_HIGH_ROBUST_Z="${APP_SUMMARY_INTERPRETABILITY_HIGH_ROBUST_Z:-3.0}" \
  APP_SUMMARY_INTERPRETABILITY_LOW_ROBUST_Z="${APP_SUMMARY_INTERPRETABILITY_LOW_ROBUST_Z:--2.5}" \
  APP_SUMMARY_INTERPRETABILITY_DELTA_ROBUST_Z="${APP_SUMMARY_INTERPRETABILITY_DELTA_ROBUST_Z:-3.0}" \
  APP_SUMMARY_INTERPRETABILITY_TOP_CONTRIBUTOR_PCT="${APP_SUMMARY_INTERPRETABILITY_TOP_CONTRIBUTOR_PCT:-0.10}" \
  APP_SUMMARY_INTERPRETABILITY_SUSTAINED_MIN_DAYS="${APP_SUMMARY_INTERPRETABILITY_SUSTAINED_MIN_DAYS:-3}" \
  APP_SUMMARY_INTERPRETABILITY_INCLUDE_AGENT_TEXT_DEFAULT="${APP_SUMMARY_INTERPRETABILITY_INCLUDE_AGENT_TEXT_DEFAULT:-true}" \
  APP_SUMMARY_INTERPRETABILITY_CACHE_SECONDS="${APP_SUMMARY_INTERPRETABILITY_CACHE_SECONDS:-300}" \
  APP_CHATBOT_CONVERSATION_BACKEND="${APP_CHATBOT_CONVERSATION_BACKEND}" \
  APP_CHATBOT_CONVERSATION_SCHEMA="${APP_CHATBOT_CONVERSATION_SCHEMA}" \
  APP_CHATBOT_CONTEXT_TOOLS_SCHEMA="${APP_CHATBOT_CONTEXT_TOOLS_SCHEMA}" \
  APP_CHATBOT_MEMORY_MAX_TURNS="${APP_CHATBOT_MEMORY_MAX_TURNS}" \
  APP_CHATBOT_OBSERVABILITY_ENABLED="${APP_CHATBOT_OBSERVABILITY_ENABLED}" \
  APP_CHATBOT_TELEMETRY_SCHEMA="${APP_CHATBOT_TELEMETRY_SCHEMA}" \
  APP_CHATBOT_EVAL_REPORT_ONLY="${APP_CHATBOT_EVAL_REPORT_ONLY}" \
  APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED="${APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED}" \
  APP_CHATBOT_EVAL_ENFORCE="${APP_CHATBOT_EVAL_ENFORCE}" \
  APP_MLFLOW_TRACKING_URI="${APP_MLFLOW_TRACKING_URI}" \
  APP_MLFLOW_EXPERIMENT_NAME="${APP_MLFLOW_EXPERIMENT_NAME}" \
  APP_MLFLOW_PROMPT_NAME="${APP_MLFLOW_PROMPT_NAME}" \
  APP_MLFLOW_PROMPT_ALIAS="${APP_MLFLOW_PROMPT_ALIAS}" \
  APP_RETRIEVER_BACKEND="${APP_RETRIEVER_BACKEND}" \
  APP_AI_SEARCH_ENDPOINT_NAME="${APP_AI_SEARCH_ENDPOINT_NAME}" \
  APP_AI_SEARCH_INDEX_RESOURCE_KEY="${APP_AI_SEARCH_INDEX_RESOURCE_KEY}" \
  APP_AI_SEARCH_TOP_K="${APP_AI_SEARCH_TOP_K}" \
  APP_AI_SEARCH_QUERY_TYPE="${APP_AI_SEARCH_QUERY_TYPE}" \
  APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME="${APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME}" \
  APP_AI_SEARCH_ENDPOINT_TYPE="${APP_AI_SEARCH_ENDPOINT_TYPE}" \
  APP_GEMINI_SECRET_RESOURCE_KEY="${APP_GEMINI_SECRET_RESOURCE_KEY}" \
  APP_GEMINI_MODEL="${APP_GEMINI_MODEL:-gemini-2.5-flash}" \
  ./.venv/bin/python databricks/scripts/stage_phase35_databricks_app.py
ensure_chatbot_skill_lifecycle_dirs
setup_chatbot_conversation_tables
setup_chatbot_context_tools
setup_chatbot_ai_search
setup_chatbot_observability

if ! run_with_retries databricks apps get "${APP_NAME}" -o json >/dev/null 2>&1; then
  run_with_retries databricks apps create "${APP_NAME}" \
    --description "${APP_DESCRIPTION}" \
    --compute-size "${APP_COMPUTE_SIZE}"
fi

APP_JSON="$(capture_with_retries databricks apps get "${APP_NAME}" -o json)"
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
run_with_retries databricks apps update "${APP_NAME}" --json "${APP_RESOURCE_UPDATE_JSON}" >/dev/null

APP_JSON="$(capture_with_retries databricks apps get "${APP_NAME}" -o json)"
COMPUTE_STATE="$(jq -r '.compute_status.state // empty' <<< "${APP_JSON}")"
if [[ "${COMPUTE_STATE}" != "ACTIVE" ]]; then
  run_with_retries databricks apps start "${APP_NAME}" >/dev/null
fi

run_with_retries databricks workspace delete "${WORKSPACE_SOURCE_PATH}" --recursive >/dev/null 2>&1 || true
run_with_retries databricks workspace import-dir "${BUILD_APP_DIR}" "${WORKSPACE_SOURCE_PATH}" --overwrite
run_with_retries databricks apps deploy "${APP_NAME}" \
  --source-code-path "${WORKSPACE_SOURCE_PATH}" \
  --mode SNAPSHOT
run_with_retries databricks apps start "${APP_NAME}"

echo "Deployed Databricks app '${APP_NAME}' from ${WORKSPACE_SOURCE_PATH}"
APP_JSON="$(capture_with_retries databricks apps get "${APP_NAME}" -o json)"
APP_URL="$(jq -r '.url // empty' <<< "${APP_JSON}")"
if [[ -n "${APP_URL}" ]]; then
  echo "App URL: ${APP_URL}"
  echo "Next smoke check: curl -sS '${APP_URL}/ready'"
fi
