#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-chec-dash-parity}"
REVIEWER_PRINCIPAL="${REVIEWER_PRINCIPAL:-users}"
EDITOR_PRINCIPAL="${EDITOR_PRINCIPAL:-}"
CATALOG_NAME="${CATALOG_NAME:-chec_dbx_demo}"
APP_DATA_SCHEMAS="${APP_DATA_SCHEMAS:-gold,silver}"
APP_CONVERSATION_SCHEMA="${APP_CONVERSATION_SCHEMA:-agent}"
APP_CONTEXT_TOOLS_SCHEMA="${APP_CONTEXT_TOOLS_SCHEMA:-agent_tools}"
APP_TELEMETRY_SCHEMA="${APP_TELEMETRY_SCHEMA:-agent_observability}"
APP_CONTEXT_TOOL_FUNCTIONS="${APP_CONTEXT_TOOL_FUNCTIONS:-get_dashboard_context,get_reliability_summary,get_compliance_context,get_event_context,get_asset_context,get_circuit_history}"
APP_CONTEXT_TOOL_VIEWS="${APP_CONTEXT_TOOL_VIEWS:-gold_agent_view_context,gold_agent_event_context,gold_agent_asset_context,gold_agent_circuit_history}"
APP_AI_SEARCH_INDEX_FULL_NAME="${APP_AI_SEARCH_INDEX_FULL_NAME:-${CATALOG_NAME}.gold.technical_doc_chunks_current_index}"
APP_LLM_ENDPOINT_NAME="${APP_LLM_ENDPOINT_NAME:-databricks-qwen3-next-80b-a3b-instruct}"
APP_LLM_ENDPOINT_ID="${APP_LLM_ENDPOINT_ID:-}"
APP_MLFLOW_EXPERIMENT_NAME="${APP_MLFLOW_EXPERIMENT_NAME:-/Shared/chec_dash_parity/agent_observability}"
APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID:-${DATABRICKS_SQL_WAREHOUSE_ID:-${WAREHOUSE_ID:-}}}"
GRANT_APP_WAREHOUSE_ACCESS="${GRANT_APP_WAREHOUSE_ACCESS:-true}"
GRANT_CHATBOT_CONVERSATION_ACCESS="${GRANT_CHATBOT_CONVERSATION_ACCESS:-true}"
GRANT_CHATBOT_CONTEXT_TOOL_ACCESS="${GRANT_CHATBOT_CONTEXT_TOOL_ACCESS:-true}"
GRANT_CHATBOT_AI_SEARCH_ACCESS="${GRANT_CHATBOT_AI_SEARCH_ACCESS:-true}"
GRANT_CHATBOT_LLM_ENDPOINT_ACCESS="${GRANT_CHATBOT_LLM_ENDPOINT_ACCESS:-false}"
GRANT_CHATBOT_OBSERVABILITY_ACCESS="${GRANT_CHATBOT_OBSERVABILITY_ACCESS:-true}"
GRANT_CHATBOT_MLFLOW_EXPERIMENT_ACCESS="${GRANT_CHATBOT_MLFLOW_EXPERIMENT_ACCESS:-true}"

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

resolve_permission_level() {
  local desired_csv="$1"
  local supported_json="$2"
  local candidate
  IFS=',' read -ra candidates <<<"${desired_csv}"
  for candidate in "${candidates[@]}"; do
    if jq -e --arg level "${candidate}" '.permission_levels[] | select(.permission_level == $level)' \
      <<<"${supported_json}" >/dev/null; then
      echo "${candidate}"
      return 0
    fi
  done
  return 1
}

if [[ -z "${EDITOR_PRINCIPAL}" ]]; then
  EDITOR_PRINCIPAL="$(capture_with_retries databricks current-user me -o json | jq -r '.userName')"
fi

SUPPORTED_LEVELS="$(capture_with_retries databricks apps get-permission-levels "${APP_NAME}" -o json)"
REVIEWER_LEVEL="$(resolve_permission_level 'CAN_USE,CAN_READ' "${SUPPORTED_LEVELS}")"
EDITOR_LEVEL="$(resolve_permission_level 'CAN_MANAGE,CAN_EDIT' "${SUPPORTED_LEVELS}")"
APP_JSON="$(capture_with_retries databricks apps get "${APP_NAME}" -o json)"
APP_SERVICE_PRINCIPAL_NAME="$(jq -r '.service_principal_name // empty' <<<"${APP_JSON}")"
APP_SERVICE_PRINCIPAL_APPLICATION_ID="$(jq -r '.service_principal_client_id // .id // empty' <<<"${APP_JSON}")"
APP_UC_PRINCIPAL="${APP_UC_PRINCIPAL:-${APP_SERVICE_PRINCIPAL_APPLICATION_ID}}"

if [[ -z "${APP_UC_PRINCIPAL}" ]]; then
  echo "Could not determine Databricks App service principal identifier for ${APP_NAME}." >&2
  exit 1
fi

ACL_FILE="$(mktemp)"

if [[ "${EDITOR_PRINCIPAL}" == "${REVIEWER_PRINCIPAL}" ]]; then
  jq -n \
    --arg principal "${EDITOR_PRINCIPAL}" \
    --arg level "${EDITOR_LEVEL}" \
    '{
      access_control_list: [
        {
          user_name: $principal,
          permission_level: $level
        }
      ]
    }' >"${ACL_FILE}"
else
  jq -n \
    --arg reviewer_principal "${REVIEWER_PRINCIPAL}" \
    --arg reviewer_level "${REVIEWER_LEVEL}" \
    --arg editor_principal "${EDITOR_PRINCIPAL}" \
    --arg editor_level "${EDITOR_LEVEL}" \
    '{
      access_control_list: [
        {
          group_name: $reviewer_principal,
          permission_level: $reviewer_level
        },
        {
          user_name: $editor_principal,
          permission_level: $editor_level
        }
      ]
    }' >"${ACL_FILE}"
fi

run_with_retries databricks apps set-permissions "${APP_NAME}" --json "@${ACL_FILE}"
rm -f "${ACL_FILE}"

if [[ "${GRANT_APP_WAREHOUSE_ACCESS}" == "true" ]]; then
  if [[ -z "${APP_WAREHOUSE_ID}" ]]; then
    echo "Set APP_WAREHOUSE_ID, DATABRICKS_SQL_WAREHOUSE_ID, or WAREHOUSE_ID before granting app SQL warehouse access." >&2
    exit 1
  fi
  WAREHOUSE_PERMISSIONS_FILE="$(mktemp)"
  jq -n \
    --arg principal "${APP_SERVICE_PRINCIPAL_APPLICATION_ID}" \
    '{
      access_control_list: [
        {
          service_principal_name: $principal,
          permission_level: "CAN_USE"
        }
      ]
    }' >"${WAREHOUSE_PERMISSIONS_FILE}"
  run_with_retries databricks permissions update warehouses "${APP_WAREHOUSE_ID}" --json "@${WAREHOUSE_PERMISSIONS_FILE}"
  rm -f "${WAREHOUSE_PERMISSIONS_FILE}"
fi

CATALOG_GRANTS_FILE="$(mktemp)"
  jq -n \
  --arg principal "${APP_UC_PRINCIPAL}" \
  '{
    changes: [
      {
        principal: $principal,
        add: ["USE_CATALOG"]
      }
    ]
  }' >"${CATALOG_GRANTS_FILE}"
run_with_retries databricks grants update catalog "${CATALOG_NAME}" --json "@${CATALOG_GRANTS_FILE}"
rm -f "${CATALOG_GRANTS_FILE}"

IFS=',' read -ra schema_names <<<"${APP_DATA_SCHEMAS}"
for schema_name in "${schema_names[@]}"; do
  schema_name="$(echo "${schema_name}" | xargs)"
  [[ -z "${schema_name}" ]] && continue

  SCHEMA_GRANTS_FILE="$(mktemp)"
  jq -n \
    --arg principal "${APP_UC_PRINCIPAL}" \
    '{
      changes: [
        {
          principal: $principal,
          add: ["USE_SCHEMA", "SELECT"]
        }
      ]
    }' >"${SCHEMA_GRANTS_FILE}"
  run_with_retries databricks grants update schema "${CATALOG_NAME}.${schema_name}" --json "@${SCHEMA_GRANTS_FILE}"
  rm -f "${SCHEMA_GRANTS_FILE}"
done

if [[ "${GRANT_CHATBOT_CONVERSATION_ACCESS}" == "true" ]]; then
  CONVERSATION_SCHEMA_GRANTS_FILE="$(mktemp)"
  jq -n \
    --arg principal "${APP_UC_PRINCIPAL}" \
    '{
      changes: [
        {
          principal: $principal,
          add: ["USE_SCHEMA", "SELECT", "MODIFY"]
        }
      ]
    }' >"${CONVERSATION_SCHEMA_GRANTS_FILE}"
  run_with_retries databricks grants update schema "${CATALOG_NAME}.${APP_CONVERSATION_SCHEMA}" --json "@${CONVERSATION_SCHEMA_GRANTS_FILE}"
  rm -f "${CONVERSATION_SCHEMA_GRANTS_FILE}"
fi

if [[ "${GRANT_CHATBOT_OBSERVABILITY_ACCESS}" == "true" ]]; then
  OBSERVABILITY_SCHEMA_GRANTS_FILE="$(mktemp)"
  jq -n \
    --arg principal "${APP_UC_PRINCIPAL}" \
    '{
      changes: [
        {
          principal: $principal,
          add: ["USE_SCHEMA", "SELECT", "MODIFY"]
        }
      ]
    }' >"${OBSERVABILITY_SCHEMA_GRANTS_FILE}"
  run_with_retries databricks grants update schema "${CATALOG_NAME}.${APP_TELEMETRY_SCHEMA}" --json "@${OBSERVABILITY_SCHEMA_GRANTS_FILE}"
  rm -f "${OBSERVABILITY_SCHEMA_GRANTS_FILE}"
fi

if [[ "${GRANT_CHATBOT_CONTEXT_TOOL_ACCESS}" == "true" ]]; then
  CONTEXT_SCHEMA_GRANTS_FILE="$(mktemp)"
  jq -n \
    --arg principal "${APP_UC_PRINCIPAL}" \
    '{
      changes: [
        {
          principal: $principal,
          add: ["USE_SCHEMA", "EXECUTE"]
        }
      ]
    }' >"${CONTEXT_SCHEMA_GRANTS_FILE}"
  run_with_retries databricks grants update schema "${CATALOG_NAME}.${APP_CONTEXT_TOOLS_SCHEMA}" --json "@${CONTEXT_SCHEMA_GRANTS_FILE}"
  rm -f "${CONTEXT_SCHEMA_GRANTS_FILE}"

  IFS=',' read -ra context_function_names <<<"${APP_CONTEXT_TOOL_FUNCTIONS}"
  for function_name in "${context_function_names[@]}"; do
    function_name="$(echo "${function_name}" | xargs)"
    [[ -z "${function_name}" ]] && continue
    FUNCTION_GRANTS_FILE="$(mktemp)"
    jq -n \
      --arg principal "${APP_UC_PRINCIPAL}" \
      '{
        changes: [
          {
            principal: $principal,
            add: ["EXECUTE"]
          }
        ]
      }' >"${FUNCTION_GRANTS_FILE}"
    run_with_retries databricks grants update function "${CATALOG_NAME}.${APP_CONTEXT_TOOLS_SCHEMA}.${function_name}" --json "@${FUNCTION_GRANTS_FILE}"
    rm -f "${FUNCTION_GRANTS_FILE}"
  done

  IFS=',' read -ra context_view_names <<<"${APP_CONTEXT_TOOL_VIEWS}"
  for view_name in "${context_view_names[@]}"; do
    view_name="$(echo "${view_name}" | xargs)"
    [[ -z "${view_name}" ]] && continue
    VIEW_GRANTS_FILE="$(mktemp)"
    jq -n \
      --arg principal "${APP_UC_PRINCIPAL}" \
      '{
        changes: [
          {
            principal: $principal,
            add: ["SELECT"]
          }
        ]
      }' >"${VIEW_GRANTS_FILE}"
    run_with_retries databricks grants update table "${CATALOG_NAME}.gold.${view_name}" --json "@${VIEW_GRANTS_FILE}"
    rm -f "${VIEW_GRANTS_FILE}"
  done
fi

if [[ "${GRANT_CHATBOT_AI_SEARCH_ACCESS}" == "true" ]]; then
  AI_SEARCH_GRANTS_FILE="$(mktemp)"
  jq -n \
    --arg principal "${APP_UC_PRINCIPAL}" \
    '{
      changes: [
        {
          principal: $principal,
          add: ["SELECT"]
        }
      ]
    }' >"${AI_SEARCH_GRANTS_FILE}"
  run_with_retries databricks grants update table "${APP_AI_SEARCH_INDEX_FULL_NAME}" --json "@${AI_SEARCH_GRANTS_FILE}"
  rm -f "${AI_SEARCH_GRANTS_FILE}"
fi

if [[ "${GRANT_CHATBOT_LLM_ENDPOINT_ACCESS}" == "true" ]]; then
  if [[ -z "${APP_LLM_ENDPOINT_ID}" ]]; then
    echo "Set APP_LLM_ENDPOINT_ID before enabling GRANT_CHATBOT_LLM_ENDPOINT_ACCESS. App resource binding grants CAN_QUERY by endpoint name during deployment." >&2
    exit 1
  fi
  LLM_ENDPOINT_PERMISSIONS_FILE="$(mktemp)"
  jq -n \
    --arg principal "${APP_SERVICE_PRINCIPAL_APPLICATION_ID}" \
    '{
      access_control_list: [
        {
          service_principal_name: $principal,
          permission_level: "CAN_QUERY"
        }
      ]
    }' >"${LLM_ENDPOINT_PERMISSIONS_FILE}"
  run_with_retries databricks serving-endpoints update-permissions "${APP_LLM_ENDPOINT_ID}" --json "@${LLM_ENDPOINT_PERMISSIONS_FILE}"
  rm -f "${LLM_ENDPOINT_PERMISSIONS_FILE}"
fi

if [[ "${GRANT_CHATBOT_MLFLOW_EXPERIMENT_ACCESS}" == "true" ]]; then
  EXPERIMENT_JSON="$(capture_with_retries databricks experiments get-by-name "${APP_MLFLOW_EXPERIMENT_NAME}" -o json 2>/dev/null || true)"
  EXPERIMENT_ID="$(jq -r '.experiment.experiment_id // .experiment_id // empty' <<<"${EXPERIMENT_JSON}")"
  if [[ -n "${EXPERIMENT_ID}" && "${EXPERIMENT_ID}" != "null" ]]; then
    MLFLOW_EXPERIMENT_PERMISSIONS_FILE="$(mktemp)"
    jq -n \
      --arg principal "${APP_SERVICE_PRINCIPAL_APPLICATION_ID}" \
      '{
        access_control_list: [
          {
            service_principal_name: $principal,
            permission_level: "CAN_EDIT"
          }
        ]
      }' >"${MLFLOW_EXPERIMENT_PERMISSIONS_FILE}"
    run_with_retries databricks experiments update-permissions "${EXPERIMENT_ID}" --json "@${MLFLOW_EXPERIMENT_PERMISSIONS_FILE}"
    rm -f "${MLFLOW_EXPERIMENT_PERMISSIONS_FILE}"
  else
    echo "MLflow experiment '${APP_MLFLOW_EXPERIMENT_NAME}' was not found; run setup_phase9_observability.py before granting experiment access." >&2
  fi
fi

echo "Applied app permissions for ${APP_NAME}, warehouse access, and data grants for ${APP_SERVICE_PRINCIPAL_NAME:-$APP_UC_PRINCIPAL} (${APP_UC_PRINCIPAL})"
