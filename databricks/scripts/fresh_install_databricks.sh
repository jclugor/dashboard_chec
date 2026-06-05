#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATABRICKS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${DATABRICKS_DIR}/.." && pwd)"
CHEC_ROOT="$(cd "${REPO_ROOT}/.." && pwd)"

ENV_FILE="${FRESH_INSTALL_ENV_FILE:-${REPO_ROOT}/.env.databricks-fresh-install}"
ENV_TEMPLATE="${DATABRICKS_DIR}/fresh_install.env.example"

log() {
  printf '\n== %s ==\n' "$*"
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

load_env_file() {
  local stage_override="${FRESH_INSTALL_STAGE:-}"
  if [[ ! -f "${ENV_FILE}" ]]; then
    cp "${ENV_TEMPLATE}" "${ENV_FILE}"
    echo "Created local deploy env file: ${ENV_FILE}"
  fi
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  if [[ -n "${stage_override}" ]]; then
    FRESH_INSTALL_STAGE="${stage_override}"
  fi
}

env_quote() {
  local value="$1"
  value="${value//\'/\'\\\'\'}"
  printf "'%s'" "${value}"
}

upsert_env() {
  local key="$1"
  local value="$2"
  local line
  local tmp
  line="${key}=$(env_quote "${value}")"
  touch "${ENV_FILE}"
  tmp="$(mktemp)"
  awk -v key="${key}" -v line="${line}" '
    BEGIN { done = 0 }
    $0 ~ "^" key "=" { print line; done = 1; next }
    { print }
    END { if (done == 0) print line }
  ' "${ENV_FILE}" > "${tmp}"
  mv "${tmp}" "${ENV_FILE}"
}

selected_stage() {
  local stage="$1"
  [[ "${FRESH_INSTALL_STAGE}" == "all" || ",${FRESH_INSTALL_STAGE}," == *",${stage},"* ]]
}

extract_json_payload() {
  local raw_output="$1"
  printf '%s\n' "${raw_output}" | awk '
    BEGIN { printing = 0 }
    /^[[:space:]]*[\[{]/ { printing = 1 }
    printing { print }
  '
}

capture_retry() {
  local attempt=1
  local max_attempts="${FRESH_INSTALL_RETRIES:-3}"
  local delay_seconds="${FRESH_INSTALL_RETRY_DELAY_SECONDS:-10}"
  local output
  local status
  while true; do
    if output="$("$@" 2>&1)"; then
      printf '%s' "${output}"
      return 0
    fi
    status=$?
    if (( attempt >= max_attempts )); then
      printf '%s\n' "${output}" >&2
      return "${status}"
    fi
    printf '%s\n' "${output}" >&2
    echo "Retrying (${attempt}/${max_attempts}): $*" >&2
    sleep "${delay_seconds}"
    attempt=$((attempt + 1))
  done
}

apply_defaults() {
  AZURE_REGION="${AZURE_REGION:-eastus}"
  AZURE_RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-rg-chec-dashboard-dev}"
  DATABRICKS_WORKSPACE_NAME="${DATABRICKS_WORKSPACE_NAME:-adb-chec-dashboard-dev}"
  DATABRICKS_AUTH_TYPE="${DATABRICKS_AUTH_TYPE:-azure-cli}"
  CATALOG_NAME="${CATALOG_NAME:-chec_dbx_demo}"
  APP_CATALOG_NAME="${APP_CATALOG_NAME:-${CATALOG_NAME}}"
  APP_NAME="${APP_NAME:-chec-dash-parity}"
  REVIEWER_PRINCIPAL="${REVIEWER_PRINCIPAL:-users}"
  EDITOR_PRINCIPAL="${EDITOR_PRINCIPAL:-}"
  UC_MANAGED_STORAGE_ENABLED="${UC_MANAGED_STORAGE_ENABLED:-true}"
  UC_STORAGE_CONTAINER_NAME="${UC_STORAGE_CONTAINER_NAME:-unity-catalog}"
  UC_STORAGE_CREDENTIAL_NAME="${UC_STORAGE_CREDENTIAL_NAME:-chec_dashboard_mi_cred}"
  UC_EXTERNAL_LOCATION_NAME="${UC_EXTERNAL_LOCATION_NAME:-chec_dashboard_uc_root}"
  WAREHOUSE_NAME="${WAREHOUSE_NAME:-CHEC Dashboard Warehouse}"
  WAREHOUSE_CLUSTER_SIZE="${WAREHOUSE_CLUSTER_SIZE:-Small}"
  WAREHOUSE_AUTO_STOP_MINS="${WAREHOUSE_AUTO_STOP_MINS:-10}"
  WAREHOUSE_TYPE="${WAREHOUSE_TYPE:-PRO}"
  WAREHOUSE_ENABLE_SERVERLESS="${WAREHOUSE_ENABLE_SERVERLESS:-true}"
  WAREHOUSE_ENABLE_PHOTON="${WAREHOUSE_ENABLE_PHOTON:-true}"
  GRANT_APP_WAREHOUSE_ACCESS="${GRANT_APP_WAREHOUSE_ACCESS:-true}"
  SOURCE_VOLUME_NAME="${SOURCE_VOLUME_NAME:-source_files}"
  ARTIFACT_VOLUME_NAME="${ARTIFACT_VOLUME_NAME:-artifacts}"
  USE_CLASSIC_JOBS="${USE_CLASSIC_JOBS:-false}"
  CHECK_CLASSIC_SKU_FALLBACKS="${CHECK_CLASSIC_SKU_FALLBACKS:-false}"
  FRESH_INSTALL_RESET_STALE_BUNDLE_STATE="${FRESH_INSTALL_RESET_STALE_BUNDLE_STATE:-true}"
  FRESH_INSTALL_SKIP_PREFLIGHT="${FRESH_INSTALL_SKIP_PREFLIGHT:-false}"
  FRESH_INSTALL_STAGE="${FRESH_INSTALL_STAGE:-all}"
  BUILD_CHATBOT_CORPUS="${BUILD_CHATBOT_CORPUS:-true}"

  CHEC_SOURCE_DATA_DIR="${CHEC_SOURCE_DATA_DIR:-${CHEC_ROOT}/data}"
  CHATBOT_SOURCE_DOCS_DIR="${CHATBOT_SOURCE_DOCS_DIR:-${CHEC_ROOT}/Dashboard_CHEC/Unstructured_Files}"
  CHATBOT_VARIABLES_SOURCE_DIR="${CHATBOT_VARIABLES_SOURCE_DIR:-${CHEC_ROOT}/data/arbol_decision_recomendaciones}"
  CHATBOT_CORPUS_SOURCE_DIR="${CHATBOT_CORPUS_SOURCE_DIR:-${CHEC_ROOT}/data/chatbot_corpus}"
  CHATBOT_SKILLS_SOURCE_DIR="${CHATBOT_SKILLS_SOURCE_DIR:-${REPO_ROOT}/src/chec_dashboard/agent_skills/active}"

  APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID:-${DATABRICKS_SQL_WAREHOUSE_ID:-}}"
  DATABRICKS_SQL_WAREHOUSE_ID="${DATABRICKS_SQL_WAREHOUSE_ID:-${APP_WAREHOUSE_ID}}"
  WAREHOUSE_ID="${WAREHOUSE_ID:-${APP_WAREHOUSE_ID}}"

  APP_GOLD_SCHEMA="${APP_GOLD_SCHEMA:-gold}"
  APP_SILVER_SCHEMA="${APP_SILVER_SCHEMA:-silver}"
  APP_SOURCE_VOLUME_NAME="${APP_SOURCE_VOLUME_NAME:-${SOURCE_VOLUME_NAME}}"
  APP_COMPUTE_SIZE="${APP_COMPUTE_SIZE:-MEDIUM}"
  APP_CHATBOT_ENABLED="${APP_CHATBOT_ENABLED:-true}"
  APP_CHATBOT_CONVERSATION_BACKEND="${APP_CHATBOT_CONVERSATION_BACKEND:-databricks_sql}"
  APP_CHATBOT_CONVERSATION_SCHEMA="${APP_CHATBOT_CONVERSATION_SCHEMA:-agent}"
  APP_CHATBOT_CONTEXT_TOOLS_SCHEMA="${APP_CHATBOT_CONTEXT_TOOLS_SCHEMA:-agent_tools}"
  APP_CHATBOT_MEMORY_MAX_TURNS="${APP_CHATBOT_MEMORY_MAX_TURNS:-8}"
  APP_RETRIEVER_BACKEND="${APP_RETRIEVER_BACKEND:-databricks_ai_search}"
  APP_AI_SEARCH_ENDPOINT_NAME="${APP_AI_SEARCH_ENDPOINT_NAME:-chec-agent-search}"
  APP_AI_SEARCH_INDEX_FULL_NAME="${APP_AI_SEARCH_INDEX_FULL_NAME:-${APP_CATALOG_NAME}.gold.technical_doc_chunks_current_index}"
  APP_AI_SEARCH_INDEX_RESOURCE_KEY="${APP_AI_SEARCH_INDEX_RESOURCE_KEY:-chatbot_ai_search_index}"
  APP_AI_SEARCH_TOP_K="${APP_AI_SEARCH_TOP_K:-8}"
  APP_AI_SEARCH_QUERY_TYPE="${APP_AI_SEARCH_QUERY_TYPE:-hybrid}"
  APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME="${APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME:-databricks-qwen3-embedding-0-6b}"
  APP_AI_SEARCH_ENDPOINT_TYPE="${APP_AI_SEARCH_ENDPOINT_TYPE:-STANDARD}"
  APP_LLM_PROVIDER="${APP_LLM_PROVIDER:-databricks_model_serving}"
  APP_LLM_ENDPOINT_NAME="${APP_LLM_ENDPOINT_NAME:-databricks-qwen3-next-80b-a3b-instruct}"
  APP_LLM_ENDPOINT_RESOURCE_KEY="${APP_LLM_ENDPOINT_RESOURCE_KEY:-chatbot_llm_endpoint}"
  APP_LLM_MAX_TOKENS="${APP_LLM_MAX_TOKENS:-1200}"
  APP_LLM_TEMPERATURE="${APP_LLM_TEMPERATURE:-0.2}"
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
  APP_GEMINI_SECRET_SCOPE="${APP_GEMINI_SECRET_SCOPE:-}"
  APP_GEMINI_SECRET_KEY="${APP_GEMINI_SECRET_KEY:-}"
}

derive_uc_storage_defaults() {
  local storage_suffix
  storage_suffix="${DATABRICKS_WORKSPACE_ID:-${DATABRICKS_WORKSPACE_NAME//[^[:alnum:]]/}}"
  storage_suffix="${storage_suffix: -12}"
  UC_STORAGE_ACCOUNT_NAME="${UC_STORAGE_ACCOUNT_NAME:-stchec${storage_suffix,,}}"
  UC_ACCESS_CONNECTOR_NAME="${UC_ACCESS_CONNECTOR_NAME:-ac-${DATABRICKS_WORKSPACE_NAME}}"
  CATALOG_MANAGED_LOCATION="${CATALOG_MANAGED_LOCATION:-abfss://${UC_STORAGE_CONTAINER_NAME}@${UC_STORAGE_ACCOUNT_NAME}.dfs.core.windows.net/catalogs/${CATALOG_NAME}}"
}

persist_core_env() {
  upsert_env AZURE_SUBSCRIPTION_ID "${AZURE_SUBSCRIPTION_ID:-}"
  upsert_env AZURE_REGION "${AZURE_REGION}"
  upsert_env AZURE_RESOURCE_GROUP "${AZURE_RESOURCE_GROUP}"
  upsert_env DATABRICKS_WORKSPACE_NAME "${DATABRICKS_WORKSPACE_NAME}"
  upsert_env DATABRICKS_WORKSPACE_ID "${DATABRICKS_WORKSPACE_ID:-}"
  upsert_env DATABRICKS_HOST "${DATABRICKS_HOST:-}"
  upsert_env DATABRICKS_AUTH_TYPE "${DATABRICKS_AUTH_TYPE}"
  upsert_env CATALOG_NAME "${CATALOG_NAME}"
  upsert_env APP_CATALOG_NAME "${APP_CATALOG_NAME}"
  upsert_env APP_NAME "${APP_NAME}"
  upsert_env UC_STORAGE_ACCOUNT_NAME "${UC_STORAGE_ACCOUNT_NAME:-}"
  upsert_env UC_STORAGE_CONTAINER_NAME "${UC_STORAGE_CONTAINER_NAME:-}"
  upsert_env UC_ACCESS_CONNECTOR_NAME "${UC_ACCESS_CONNECTOR_NAME:-}"
  upsert_env UC_STORAGE_CREDENTIAL_NAME "${UC_STORAGE_CREDENTIAL_NAME:-}"
  upsert_env UC_EXTERNAL_LOCATION_NAME "${UC_EXTERNAL_LOCATION_NAME:-}"
  upsert_env CATALOG_MANAGED_LOCATION "${CATALOG_MANAGED_LOCATION:-}"
  upsert_env APP_WAREHOUSE_ID "${APP_WAREHOUSE_ID:-}"
  upsert_env DATABRICKS_SQL_WAREHOUSE_ID "${DATABRICKS_SQL_WAREHOUSE_ID:-}"
  upsert_env WAREHOUSE_NAME "${WAREHOUSE_NAME}"
  upsert_env GRANT_APP_WAREHOUSE_ACCESS "${GRANT_APP_WAREHOUSE_ACCESS:-true}"
}

export_runtime_env() {
  export DATABRICKS_HOST DATABRICKS_AUTH_TYPE
  export CATALOG_NAME SOURCE_VOLUME_NAME ARTIFACT_VOLUME_NAME
  export UC_MANAGED_STORAGE_ENABLED UC_STORAGE_ACCOUNT_NAME UC_STORAGE_CONTAINER_NAME UC_ACCESS_CONNECTOR_NAME
  export UC_STORAGE_CREDENTIAL_NAME UC_EXTERNAL_LOCATION_NAME CATALOG_MANAGED_LOCATION
  export CHEC_SOURCE_DATA_DIR CHATBOT_SOURCE_DOCS_DIR CHATBOT_VARIABLES_SOURCE_DIR CHATBOT_CORPUS_SOURCE_DIR CHATBOT_SKILLS_SOURCE_DIR
  export APP_CATALOG_NAME APP_NAME APP_WAREHOUSE_ID DATABRICKS_SQL_WAREHOUSE_ID WAREHOUSE_ID GRANT_APP_WAREHOUSE_ACCESS
  export APP_GOLD_SCHEMA APP_SILVER_SCHEMA APP_SOURCE_VOLUME_NAME APP_COMPUTE_SIZE
  export APP_CHATBOT_ENABLED APP_CHATBOT_CONVERSATION_BACKEND APP_CHATBOT_CONVERSATION_SCHEMA APP_CHATBOT_CONTEXT_TOOLS_SCHEMA APP_CHATBOT_MEMORY_MAX_TURNS
  export APP_RETRIEVER_BACKEND APP_AI_SEARCH_ENDPOINT_NAME APP_AI_SEARCH_INDEX_FULL_NAME APP_AI_SEARCH_INDEX_RESOURCE_KEY APP_AI_SEARCH_TOP_K
  export APP_AI_SEARCH_QUERY_TYPE APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME APP_AI_SEARCH_ENDPOINT_TYPE
  export APP_LLM_PROVIDER APP_LLM_ENDPOINT_NAME APP_LLM_ENDPOINT_RESOURCE_KEY APP_LLM_MAX_TOKENS APP_LLM_TEMPERATURE
  export APP_CHATBOT_OBSERVABILITY_ENABLED APP_CHATBOT_TELEMETRY_SCHEMA APP_CHATBOT_EVAL_REPORT_ONLY APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED APP_CHATBOT_EVAL_ENFORCE
  export APP_MLFLOW_TRACKING_URI APP_MLFLOW_EXPERIMENT_NAME APP_MLFLOW_PROMPT_NAME APP_MLFLOW_PROMPT_ALIAS
  export APP_GEMINI_SECRET_RESOURCE_KEY APP_GEMINI_SECRET_SCOPE APP_GEMINI_SECRET_KEY
}

ensure_azure_workspace() {
  log "Azure workspace"
  if [[ -z "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
    AZURE_SUBSCRIPTION_ID="$(az account show -o json | jq -r '.id')"
  fi
  az account set --subscription "${AZURE_SUBSCRIPTION_ID}"
  az provider register --namespace Microsoft.Databricks --wait >/dev/null
  az group create --name "${AZURE_RESOURCE_GROUP}" --location "${AZURE_REGION}" -o table

  if ! az databricks workspace show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${DATABRICKS_WORKSPACE_NAME}" -o json >/tmp/chec_workspace.json 2>/tmp/chec_workspace.err; then
    cat /tmp/chec_workspace.err >&2
    az databricks workspace create \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${DATABRICKS_WORKSPACE_NAME}" \
      --location "${AZURE_REGION}" \
      --sku premium \
      -o json >/tmp/chec_workspace.json
  fi

  local workspace_url
  workspace_url="$(jq -r '.workspaceUrl // empty' /tmp/chec_workspace.json)"
  [[ -n "${workspace_url}" ]] || die "Azure workspace exists but no workspaceUrl was returned."
  DATABRICKS_WORKSPACE_ID="$(jq -r '.workspaceId // empty' /tmp/chec_workspace.json)"
  DATABRICKS_HOST="https://${workspace_url}"
  derive_uc_storage_defaults
  upsert_env DATABRICKS_HOST "${DATABRICKS_HOST}"
  persist_core_env
  echo "Databricks host: ${DATABRICKS_HOST}"
}

ensure_databricks_ready() {
  log "Databricks auth and Unity Catalog"
  [[ -n "${DATABRICKS_HOST:-}" ]] || die "DATABRICKS_HOST is empty. Run FRESH_INSTALL_STAGE=azure first."
  export DATABRICKS_HOST DATABRICKS_AUTH_TYPE
  databricks current-user me -o json | jq -r '"User: " + .userName'
  if ! databricks metastores current -o json >/tmp/chec_metastore.json 2>/tmp/chec_metastore.err; then
    cat /tmp/chec_metastore.err >&2
    die "No Unity Catalog metastore is attached. Open the Databricks account console, create/attach a metastore in ${AZURE_REGION}, then rerun."
  fi
  DATABRICKS_WORKSPACE_ID="$(jq -r '.workspace_id // empty' /tmp/chec_metastore.json)"
  export DATABRICKS_WORKSPACE_ID
  derive_uc_storage_defaults
  jq -r '"Metastore: " + .metastore_id + " | default catalog: " + (.default_catalog_name // "<none>")' /tmp/chec_metastore.json
}

ensure_uc_catalog() {
  log "Unity Catalog target catalog"
  if databricks catalogs get "${CATALOG_NAME}" -o json >/tmp/chec_catalog.json 2>/tmp/chec_catalog.err; then
    echo "Catalog exists: ${CATALOG_NAME}"
    return 0
  fi

  if databricks catalogs create "${CATALOG_NAME}" -o json >/tmp/chec_catalog_create.json 2>/tmp/chec_catalog_create.err; then
    echo "Created catalog with workspace/default storage: ${CATALOG_NAME}"
    return 0
  fi

  if ! grep -q "Metastore storage root URL does not exist" /tmp/chec_catalog_create.err; then
    cat /tmp/chec_catalog_create.err >&2
    die "Unable to create target catalog ${CATALOG_NAME}."
  fi
  [[ "${UC_MANAGED_STORAGE_ENABLED}" == "true" ]] || {
    cat /tmp/chec_catalog_create.err >&2
    die "Catalog ${CATALOG_NAME} needs managed storage. Set UC_MANAGED_STORAGE_ENABLED=true or use an existing catalog."
  }

  echo "Catalog ${CATALOG_NAME} needs an explicit managed storage location."
  ensure_uc_managed_storage
  databricks catalogs create "${CATALOG_NAME}" --storage-root "${CATALOG_MANAGED_LOCATION}" -o json >/tmp/chec_catalog_create.json
  echo "Created catalog ${CATALOG_NAME} with managed location ${CATALOG_MANAGED_LOCATION}"
}

ensure_uc_managed_storage() {
  log "Azure storage for Unity Catalog managed data"
  derive_uc_storage_defaults
  az provider register --namespace Microsoft.Storage --wait >/dev/null

  local storage_json storage_id connector_json connector_id connector_principal location_url
  if ! az storage account show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${UC_STORAGE_ACCOUNT_NAME}" -o json >/tmp/chec_uc_storage.json 2>/tmp/chec_uc_storage.err; then
    az storage account create \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${UC_STORAGE_ACCOUNT_NAME}" \
      --location "${AZURE_REGION}" \
      --sku Standard_LRS \
      --kind StorageV2 \
      --enable-hierarchical-namespace true \
      --allow-blob-public-access false \
      --min-tls-version TLS1_2 \
      -o json >/tmp/chec_uc_storage.json
  fi
  storage_json="$(cat /tmp/chec_uc_storage.json)"
  storage_id="$(jq -r '.id' <<< "${storage_json}")"
  az storage container create \
    --account-name "${UC_STORAGE_ACCOUNT_NAME}" \
    --name "${UC_STORAGE_CONTAINER_NAME}" \
    --auth-mode key \
    -o none

  if ! az databricks access-connector show --resource-group "${AZURE_RESOURCE_GROUP}" --name "${UC_ACCESS_CONNECTOR_NAME}" -o json >/tmp/chec_uc_connector.json 2>/tmp/chec_uc_connector.err; then
    az databricks access-connector create \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${UC_ACCESS_CONNECTOR_NAME}" \
      --location "${AZURE_REGION}" \
      --identity-type SystemAssigned \
      -o json >/tmp/chec_uc_connector.json
  fi
  connector_json="$(cat /tmp/chec_uc_connector.json)"
  connector_id="$(jq -r '.id' <<< "${connector_json}")"
  connector_principal="$(jq -r '.identity.principalId // empty' <<< "${connector_json}")"
  [[ -n "${connector_principal}" ]] || die "Access connector ${UC_ACCESS_CONNECTOR_NAME} has no system-assigned principal ID."

  if ! az role assignment create \
    --assignee-object-id "${connector_principal}" \
    --assignee-principal-type ServicePrincipal \
    --role "Storage Blob Data Contributor" \
    --scope "${storage_id}" \
    -o json >/tmp/chec_uc_role_assignment.json 2>/tmp/chec_uc_role_assignment.err; then
    if ! grep -qi "already exists" /tmp/chec_uc_role_assignment.err; then
      cat /tmp/chec_uc_role_assignment.err >&2
      die "Unable to grant Storage Blob Data Contributor to the Databricks access connector."
    fi
  fi

  local credential_payload
  credential_payload="$(jq -n \
    --arg name "${UC_STORAGE_CREDENTIAL_NAME}" \
    --arg access_connector_id "${connector_id}" \
    '{
      name: $name,
      azure_managed_identity: {access_connector_id: $access_connector_id},
      comment: "CHEC Dashboard fresh-install managed identity storage credential",
      read_only: false,
      skip_validation: true
    }')"
  if ! databricks storage-credentials get "${UC_STORAGE_CREDENTIAL_NAME}" -o json >/tmp/chec_uc_credential.json 2>/tmp/chec_uc_credential.err; then
    databricks storage-credentials create --json "${credential_payload}" -o json >/tmp/chec_uc_credential.json
  fi

  location_url="abfss://${UC_STORAGE_CONTAINER_NAME}@${UC_STORAGE_ACCOUNT_NAME}.dfs.core.windows.net/"
  if ! databricks external-locations get "${UC_EXTERNAL_LOCATION_NAME}" -o json >/tmp/chec_uc_location.json 2>/tmp/chec_uc_location.err; then
    databricks external-locations create \
      "${UC_EXTERNAL_LOCATION_NAME}" \
      "${location_url}" \
      "${UC_STORAGE_CREDENTIAL_NAME}" \
      --skip-validation \
      -o json >/tmp/chec_uc_location.json
  fi

  upsert_env UC_STORAGE_ACCOUNT_NAME "${UC_STORAGE_ACCOUNT_NAME}"
  upsert_env UC_STORAGE_CONTAINER_NAME "${UC_STORAGE_CONTAINER_NAME}"
  upsert_env UC_ACCESS_CONNECTOR_NAME "${UC_ACCESS_CONNECTOR_NAME}"
  upsert_env UC_STORAGE_CREDENTIAL_NAME "${UC_STORAGE_CREDENTIAL_NAME}"
  upsert_env UC_EXTERNAL_LOCATION_NAME "${UC_EXTERNAL_LOCATION_NAME}"
  upsert_env CATALOG_MANAGED_LOCATION "${CATALOG_MANAGED_LOCATION}"
  echo "UC managed location: ${CATALOG_MANAGED_LOCATION}"
}

reset_stale_bundle_state() {
  [[ "${FRESH_INSTALL_RESET_STALE_BUNDLE_STATE}" == "true" ]] || return 0
  local state_file="${DATABRICKS_DIR}/.databricks/bundle/dev/terraform/terraform.tfstate"
  [[ -f "${state_file}" ]] || return 0
  [[ -n "${DATABRICKS_WORKSPACE_ID:-}" ]] || return 0

  local state_workspace_ids
  state_workspace_ids="$(
    jq -r '
      [.resources[]?.instances[]?.attributes.provider_config[]?.workspace_id // empty]
      | unique
      | .[]
    ' "${state_file}" 2>/dev/null || true
  )"
  [[ -n "${state_workspace_ids}" ]] || return 0

  if ! grep -qx "${DATABRICKS_WORKSPACE_ID}" <<< "${state_workspace_ids}"; then
    local backup_dir
    backup_dir="${TMPDIR:-/tmp}/chec_databricks_bundle_state_$(date +%Y%m%d%H%M%S)"
    mv "${DATABRICKS_DIR}/.databricks" "${backup_dir}"
    echo "Moved stale local Databricks bundle state to ${backup_dir}"
    echo "State workspace IDs were: ${state_workspace_ids//$'\n'/, }; active workspace ID is ${DATABRICKS_WORKSPACE_ID}."
  fi
}

ensure_sql_warehouse() {
  log "SQL warehouse"
  export_runtime_env
  if [[ -z "${APP_WAREHOUSE_ID:-}" ]]; then
    local warehouses_json
    warehouses_json="$(databricks warehouses list -o json)"
    APP_WAREHOUSE_ID="$(
      jq -r --arg name "${WAREHOUSE_NAME}" '
        (if type == "object" and has("warehouses") then .warehouses else . end)[]?
        | select(.name == $name)
        | .id // .warehouse_id // empty
      ' <<< "${warehouses_json}" | head -n 1
    )"
  fi

  if [[ -z "${APP_WAREHOUSE_ID:-}" ]]; then
    local payload
    payload="$(jq -n \
      --arg name "${WAREHOUSE_NAME}" \
      --arg size "${WAREHOUSE_CLUSTER_SIZE}" \
      --arg type "${WAREHOUSE_TYPE}" \
      --argjson auto_stop "${WAREHOUSE_AUTO_STOP_MINS}" \
      --argjson serverless "${WAREHOUSE_ENABLE_SERVERLESS}" \
      --argjson photon "${WAREHOUSE_ENABLE_PHOTON}" \
      '{
        name: $name,
        cluster_size: $size,
        min_num_clusters: 1,
        max_num_clusters: 1,
        auto_stop_mins: $auto_stop,
        enable_serverless_compute: $serverless,
        enable_photon: $photon,
        warehouse_type: $type
      }')"
    databricks warehouses create --json "${payload}" --no-wait -o json >/tmp/chec_warehouse_create.json
    APP_WAREHOUSE_ID="$(jq -r '.id // .warehouse_id // empty' /tmp/chec_warehouse_create.json)"
  fi

  [[ -n "${APP_WAREHOUSE_ID:-}" ]] || die "Unable to create or discover SQL warehouse '${WAREHOUSE_NAME}'."
  DATABRICKS_SQL_WAREHOUSE_ID="${APP_WAREHOUSE_ID}"
  WAREHOUSE_ID="${APP_WAREHOUSE_ID}"
  upsert_env APP_WAREHOUSE_ID "${APP_WAREHOUSE_ID}"
  upsert_env DATABRICKS_SQL_WAREHOUSE_ID "${DATABRICKS_SQL_WAREHOUSE_ID}"
  upsert_env WAREHOUSE_ID "${WAREHOUSE_ID}"
  export_runtime_env

  local warehouse_json
  warehouse_json="$(databricks warehouses get "${APP_WAREHOUSE_ID}" -o json)"
  local state
  state="$(jq -r '.state // empty' <<< "${warehouse_json}")"
  if [[ "${state}" != "RUNNING" ]]; then
    databricks warehouses start "${APP_WAREHOUSE_ID}" --timeout "${WAREHOUSE_START_TIMEOUT:-20m}"
  fi
  echo "Warehouse '${WAREHOUSE_NAME}': ${APP_WAREHOUSE_ID}"
}

bundle_args() {
  printf '%s\n' \
    -t dev \
    --var "catalog_name=${CATALOG_NAME}" \
    --var "source_volume_name=${SOURCE_VOLUME_NAME}" \
    --var "artifact_volume_name=${ARTIFACT_VOLUME_NAME}" \
    --var "dashboard_warehouse_id=${APP_WAREHOUSE_ID}"
}

run_foundation() {
  log "Databricks data foundation"
  ensure_uc_catalog
  ensure_sql_warehouse
  reset_stale_bundle_state
  if [[ "${FRESH_INSTALL_SKIP_PREFLIGHT}" != "true" ]]; then
    CHECK_CLASSIC_SKU_FALLBACKS="${CHECK_CLASSIC_SKU_FALLBACKS}" bash "${REPO_ROOT}/databricks/scripts/preflight_phase1_deploy.sh"
  fi

  mapfile -t args < <(bundle_args)
  (cd "${DATABRICKS_DIR}" && databricks bundle validate "${args[@]}")
  (cd "${DATABRICKS_DIR}" && databricks bundle deploy "${args[@]}")

  local bootstrap_job="chec_phase1_bootstrap"
  local ingest_job="chec_phase1_ingest_validation"
  if [[ "${USE_CLASSIC_JOBS}" == "true" ]]; then
    bootstrap_job="chec_phase1_bootstrap_classic"
    ingest_job="chec_phase1_ingest_validation_classic"
  fi
  (cd "${DATABRICKS_DIR}" && databricks bundle run "${args[@]}" "${bootstrap_job}")
  CATALOG_NAME="${CATALOG_NAME}" SOURCE_VOLUME_NAME="${SOURCE_VOLUME_NAME}" ARTIFACT_VOLUME_NAME="${ARTIFACT_VOLUME_NAME}" \
    bash "${REPO_ROOT}/databricks/scripts/upload_phase1_assets.sh"
  (cd "${DATABRICKS_DIR}" && databricks bundle run "${args[@]}" "${ingest_job}")
}

run_dashboard() {
  log "Lakeview dashboard"
  ensure_sql_warehouse
  mapfile -t args < <(bundle_args)
  (cd "${DATABRICKS_DIR}" && databricks bundle validate "${args[@]}")
  (cd "${DATABRICKS_DIR}" && databricks bundle deploy "${args[@]}")
  (cd "${DATABRICKS_DIR}" && bash scripts/publish_phase2_notebooks.sh)
  (cd "${DATABRICKS_DIR}" && WAREHOUSE_ID="${APP_WAREHOUSE_ID}" bash scripts/publish_phase2_dashboard.sh)
  (cd "${DATABRICKS_DIR}" && REVIEWER_PRINCIPAL="${REVIEWER_PRINCIPAL}" bash scripts/apply_phase2_pilot_permissions.sh)
}

maybe_build_chatbot_corpus() {
  if [[ "${BUILD_CHATBOT_CORPUS}" != "true" ]]; then
    return 0
  fi
  if [[ -f "${CHATBOT_CORPUS_SOURCE_DIR}/chunks.jsonl" ]]; then
    return 0
  fi
  if [[ ! -d "${CHATBOT_SOURCE_DOCS_DIR}" ]]; then
    echo "Skipping corpus build; source docs directory not found: ${CHATBOT_SOURCE_DOCS_DIR}" >&2
    return 0
  fi
  mkdir -p "${CHATBOT_CORPUS_SOURCE_DIR}"
  "${REPO_ROOT}/.venv/bin/python" "${REPO_ROOT}/scripts/build_chatbot_corpus.py" \
    --source-dir "${CHATBOT_SOURCE_DOCS_DIR}" \
    --source-dir "${CHATBOT_VARIABLES_SOURCE_DIR}" \
    --output-dir "${CHATBOT_CORPUS_SOURCE_DIR}"
}

run_chatbot_assets() {
  log "Chatbot documents, corpus, and skills"
  maybe_build_chatbot_corpus
  CATALOG_NAME="${CATALOG_NAME}" SOURCE_VOLUME_NAME="${SOURCE_VOLUME_NAME}" \
  CHATBOT_SOURCE_DOCS_DIR="${CHATBOT_SOURCE_DOCS_DIR}" \
  CHATBOT_VARIABLES_SOURCE_DIR="${CHATBOT_VARIABLES_SOURCE_DIR}" \
  CHATBOT_CORPUS_SOURCE_DIR="${CHATBOT_CORPUS_SOURCE_DIR}" \
  CHATBOT_SKILLS_SOURCE_DIR="${CHATBOT_SKILLS_SOURCE_DIR}" \
    bash "${REPO_ROOT}/databricks/scripts/upload_chatbot_assets.sh"
}

run_app() {
  log "Databricks app"
  ensure_sql_warehouse
  export_runtime_env
  bash "${REPO_ROOT}/databricks/scripts/deploy_phase35_databricks_app.sh"
}

run_permissions() {
  log "App permissions"
  export_runtime_env
  if [[ -z "${EDITOR_PRINCIPAL}" ]]; then
    EDITOR_PRINCIPAL="$(databricks current-user me -o json | jq -r '.userName')"
    upsert_env EDITOR_PRINCIPAL "${EDITOR_PRINCIPAL}"
  fi
  EDITOR_PRINCIPAL="${EDITOR_PRINCIPAL}" \
  REVIEWER_PRINCIPAL="${REVIEWER_PRINCIPAL}" \
  APP_TELEMETRY_SCHEMA="${APP_CHATBOT_TELEMETRY_SCHEMA}" \
  APP_MLFLOW_EXPERIMENT_NAME="${APP_MLFLOW_EXPERIMENT_NAME}" \
    bash "${REPO_ROOT}/databricks/scripts/apply_phase35_app_permissions.sh"
}

run_validation() {
  log "Deployment validation"
  local expected_tables=(
    gold_saidi_saifi_daily
    gold_saidi_saifi_circuit_summary
    gold_timeseries_event_details
    gold_timeseries_daily_attribution
    gold_timeseries_environment_daily
    gold_probability_inputs
    gold_map_points
    gold_map_line_segments
    gold_map_filter_index
    gold_map_event_days
  )
  for table_name in "${expected_tables[@]}"; do
    databricks tables get "${CATALOG_NAME}.gold.${table_name}" -o json >/dev/null
    echo "OK table: ${CATALOG_NAME}.gold.${table_name}"
  done

  local app_json app_url app_state compute_state
  app_json="$(databricks apps get "${APP_NAME}" -o json)"
  app_url="$(jq -r '.url // empty' <<< "${app_json}")"
  app_state="$(jq -r '.app_status.state // empty' <<< "${app_json}")"
  compute_state="$(jq -r '.compute_status.state // empty' <<< "${app_json}")"
  echo "App state: ${app_state}; compute state: ${compute_state}; url: ${app_url}"

  if command -v curl >/dev/null 2>&1 && [[ -n "${app_url}" ]]; then
    local token ready_status
    token="$(databricks auth token -o json 2>/dev/null | jq -r '.access_token // empty' || true)"
    if [[ -n "${token}" ]]; then
      ready_status="$(
        curl -sS -o /tmp/chec_app_ready.out -w "%{http_code}" \
          -H "Authorization: Bearer ${token}" \
          "${app_url}/ready" || true
      )"
    else
      ready_status="$(curl -sS -o /tmp/chec_app_ready.out -w "%{http_code}" "${app_url}/ready" || true)"
    fi
    if [[ "${ready_status}" == "200" ]]; then
      cat /tmp/chec_app_ready.out
      echo
    elif [[ "${ready_status}" =~ ^30[1278]$ ]]; then
      echo "App /ready returned HTTP ${ready_status}; Databricks App OAuth is protecting the endpoint. Open ${app_url}/ready in a signed-in browser to view the JSON readiness payload."
    else
      cat /tmp/chec_app_ready.out >&2 || true
      die "App /ready smoke check returned HTTP ${ready_status}."
    fi
  fi
}

main() {
  require_command az
  require_command databricks
  require_command jq
  require_command awk

  load_env_file
  apply_defaults
  persist_core_env

  if selected_stage azure; then
    ensure_azure_workspace
  fi

  ensure_databricks_ready
  persist_core_env

  if selected_stage foundation; then
    run_foundation
  fi
  if selected_stage dashboard; then
    run_dashboard
  fi
  if selected_stage chatbot; then
    run_chatbot_assets
  fi
  if selected_stage app; then
    run_app
  fi
  if selected_stage permissions; then
    run_permissions
  fi
  if selected_stage validate; then
    run_validation
  fi

  log "Fresh install stage complete"
  echo "Env file: ${ENV_FILE}"
  echo "Databricks host: ${DATABRICKS_HOST}"
  echo "Catalog: ${CATALOG_NAME}"
  echo "Warehouse: ${APP_WAREHOUSE_ID:-<not created>}"
}

main "$@"
