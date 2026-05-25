#!/usr/bin/env bash
set -euo pipefail

APP_NAME="${APP_NAME:-chec-dash-parity}"
REVIEWER_PRINCIPAL="${REVIEWER_PRINCIPAL:-users}"
EDITOR_PRINCIPAL="${EDITOR_PRINCIPAL:-$(databricks current-user me -o json | jq -r '.userName')}"
CATALOG_NAME="${CATALOG_NAME:-chec_dbx_demo}"
APP_DATA_SCHEMAS="${APP_DATA_SCHEMAS:-gold,silver}"

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

echo "Applied app permissions for ${APP_NAME} and data grants for ${APP_SERVICE_PRINCIPAL_NAME:-$APP_UC_PRINCIPAL} (${APP_UC_PRINCIPAL})"
