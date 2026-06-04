#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-chec-dash-parity}"
REVIEWER_PRINCIPAL="${REVIEWER_PRINCIPAL:-users}"
EDITOR_PRINCIPAL="${EDITOR_PRINCIPAL:-$(databricks current-user me -o json | jq -r '.userName')}"
CATALOG_NAME="${CATALOG_NAME:-chec_dbx_demo}"
APP_DATA_SCHEMAS="${APP_DATA_SCHEMAS:-gold,silver}"
APP_CONVERSATION_SCHEMA="${APP_CONVERSATION_SCHEMA:-agent}"
APP_CONTEXT_TOOLS_SCHEMA="${APP_CONTEXT_TOOLS_SCHEMA:-agent_tools}"
APP_CONTEXT_TOOL_FUNCTIONS="${APP_CONTEXT_TOOL_FUNCTIONS:-get_dashboard_context,get_reliability_summary,get_compliance_context,get_event_context,get_asset_context,get_circuit_history}"
APP_CONTEXT_TOOL_VIEWS="${APP_CONTEXT_TOOL_VIEWS:-gold_agent_view_context,gold_agent_event_context,gold_agent_asset_context,gold_agent_circuit_history}"
GRANT_CHATBOT_CONVERSATION_ACCESS="${GRANT_CHATBOT_CONVERSATION_ACCESS:-true}"
GRANT_CHATBOT_CONTEXT_TOOL_ACCESS="${GRANT_CHATBOT_CONTEXT_TOOL_ACCESS:-true}"

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

SUPPORTED_LEVELS="$(databricks apps get-permission-levels "${APP_NAME}" -o json)"
REVIEWER_LEVEL="$(resolve_permission_level 'CAN_USE,CAN_READ' "${SUPPORTED_LEVELS}")"
EDITOR_LEVEL="$(resolve_permission_level 'CAN_MANAGE,CAN_EDIT' "${SUPPORTED_LEVELS}")"
APP_JSON="$(databricks apps get "${APP_NAME}" -o json)"
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

databricks apps set-permissions "${APP_NAME}" --json "@${ACL_FILE}"
rm -f "${ACL_FILE}"

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
databricks grants update catalog "${CATALOG_NAME}" --json "@${CATALOG_GRANTS_FILE}"
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
  databricks grants update schema "${CATALOG_NAME}.${schema_name}" --json "@${SCHEMA_GRANTS_FILE}"
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
  databricks grants update schema "${CATALOG_NAME}.${APP_CONVERSATION_SCHEMA}" --json "@${CONVERSATION_SCHEMA_GRANTS_FILE}"
  rm -f "${CONVERSATION_SCHEMA_GRANTS_FILE}"
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
  databricks grants update schema "${CATALOG_NAME}.${APP_CONTEXT_TOOLS_SCHEMA}" --json "@${CONTEXT_SCHEMA_GRANTS_FILE}"
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
    databricks grants update function "${CATALOG_NAME}.${APP_CONTEXT_TOOLS_SCHEMA}.${function_name}" --json "@${FUNCTION_GRANTS_FILE}"
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
    databricks grants update table "${CATALOG_NAME}.gold.${view_name}" --json "@${VIEW_GRANTS_FILE}"
    rm -f "${VIEW_GRANTS_FILE}"
  done
fi

echo "Applied app permissions for ${APP_NAME} and data grants for ${APP_SERVICE_PRINCIPAL_NAME:-$APP_UC_PRINCIPAL} (${APP_UC_PRINCIPAL})"
