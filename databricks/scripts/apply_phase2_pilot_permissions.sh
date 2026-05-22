#!/usr/bin/env bash
set -euo pipefail

CATALOG_NAME="${CATALOG_NAME:-chec_dbx_demo}"
DASHBOARD_NAME_SUFFIX="${DASHBOARD_NAME_SUFFIX:-CHEC Summary Pilot}"
NOTEBOOK_WORKSPACE_DIR="${NOTEBOOK_WORKSPACE_DIR:-/Shared/CHEC Phase2 Pilot/Notebooks}"
JOB_NAME_SUFFIX="${JOB_NAME_SUFFIX:-chec-phase2-pilot-refresh}"
PILOT_REVIEWER_PRINCIPAL="${PILOT_REVIEWER_PRINCIPAL:-users}"
PILOT_EDITOR_PRINCIPAL="${PILOT_EDITOR_PRINCIPAL:-$(databricks current-user me -o json | jq -r '.user_name // .userName // .emails[0].value')}"
GRANT_REVIEWER_NOTEBOOK_ACCESS="${GRANT_REVIEWER_NOTEBOOK_ACCESS:-false}"
GRANT_REVIEWER_DATA_ACCESS="${GRANT_REVIEWER_DATA_ACCESS:-false}"

resolve_permission_level() {
  local object_type="$1"
  local object_id="$2"
  shift 2

  local available_levels
  available_levels="$(
    databricks permissions get-permission-levels "${object_type}" "${object_id}" -o json \
      | jq -r '.permission_levels[].permission_level'
  )"

  local candidate
  for candidate in "$@"; do
    if grep -Fxq "${candidate}" <<<"${available_levels}"; then
      echo "${candidate}"
      return 0
    fi
  done

  echo "Could not resolve a supported permission level for ${object_type} ${object_id}." >&2
  echo "Available levels:" >&2
  echo "${available_levels}" >&2
  exit 1
}

DASHBOARD_ID="$(databricks lakeview list -o json | jq -r --arg suffix "${DASHBOARD_NAME_SUFFIX}" '.[] | select(.display_name | endswith($suffix)) | .dashboard_id' | head -n 1)"
if [[ -z "${DASHBOARD_ID}" ]]; then
  echo "Could not find dashboard whose display name ends with '${DASHBOARD_NAME_SUFFIX}'."
  exit 1
fi

NOTEBOOK_DIR_OBJECT_ID="$(databricks workspace get-status "${NOTEBOOK_WORKSPACE_DIR}" -o json | jq -r '.object_id // .object_id')"
JOB_ID="$(databricks jobs list -o json | jq -r --arg suffix "${JOB_NAME_SUFFIX}" '.[] | select(.settings.name | endswith($suffix)) | .job_id' | head -n 1)"

DASHBOARD_EDITOR_PERMISSION="$(resolve_permission_level dashboards "${DASHBOARD_ID}" CAN_EDIT CAN_MANAGE CAN_RUN CAN_READ)"
DASHBOARD_REVIEWER_PERMISSION="$(resolve_permission_level dashboards "${DASHBOARD_ID}" CAN_READ CAN_RUN CAN_EDIT)"
DIRECTORY_EDITOR_PERMISSION="$(resolve_permission_level directories "${NOTEBOOK_DIR_OBJECT_ID}" CAN_EDIT CAN_MANAGE CAN_RUN CAN_READ)"

DIRECTORY_REVIEWER_ACL=""
if [[ "${GRANT_REVIEWER_NOTEBOOK_ACCESS}" == "true" ]]; then
  DIRECTORY_REVIEWER_PERMISSION="$(resolve_permission_level directories "${NOTEBOOK_DIR_OBJECT_ID}" CAN_READ CAN_RUN)"
  DIRECTORY_REVIEWER_ACL="$(cat <<JSON
    ,
    {
      "group_name": "${PILOT_REVIEWER_PRINCIPAL}",
      "permission_level": "${DIRECTORY_REVIEWER_PERMISSION}"
    }
JSON
)"
fi

JOB_EDITOR_PERMISSION=""
JOB_OWNER_USER_NAME=""
JOB_OWNER_GROUP_NAME=""
if [[ -n "${JOB_ID}" ]]; then
  JOB_EDITOR_PERMISSION="$(resolve_permission_level jobs "${JOB_ID}" CAN_MANAGE_RUN CAN_MANAGE CAN_VIEW)"
  JOB_OWNER_USER_NAME="$(
    databricks permissions get jobs "${JOB_ID}" -o json \
      | jq -r '
          .access_control_list[]
          | select(any(.all_permissions[]?; .permission_level == "IS_OWNER"))
          | .user_name // empty
        ' \
      | head -n 1
  )"
  JOB_OWNER_GROUP_NAME="$(
    databricks permissions get jobs "${JOB_ID}" -o json \
      | jq -r '
          .access_control_list[]
          | select(any(.all_permissions[]?; .permission_level == "IS_OWNER"))
          | .group_name // empty
        ' \
      | head -n 1
  )"
  if [[ -z "${JOB_OWNER_USER_NAME}" && -z "${JOB_OWNER_GROUP_NAME}" ]]; then
    echo "Could not determine the current job owner for ${JOB_ID}; refusing to update job permissions." >&2
    exit 1
  fi
fi

echo "Resolved dashboard permissions: editor=${DASHBOARD_EDITOR_PERMISSION}, reviewer=${DASHBOARD_REVIEWER_PERMISSION}"
echo "Resolved notebook directory permission: editor=${DIRECTORY_EDITOR_PERMISSION}"
if [[ -n "${JOB_EDITOR_PERMISSION}" ]]; then
  echo "Resolved job permission: editor=${JOB_EDITOR_PERMISSION}"
fi
if [[ "${NOTEBOOK_WORKSPACE_DIR}" == /Shared/* ]]; then
  echo "Note: ${NOTEBOOK_WORKSPACE_DIR} is under /Shared, so the workspace 'users' group may still inherit broader access from parent folders." >&2
fi
if [[ "${GRANT_REVIEWER_DATA_ACCESS}" == "true" && "${PILOT_REVIEWER_PRINCIPAL}" == "users" ]]; then
  echo "Warning: reviewer data access is enabled for the default 'users' group, which grants read access broadly across the workspace." >&2
fi

cat > /tmp/chec_phase2_dashboard_permissions.json <<JSON
{
  "access_control_list": [
    {
      "user_name": "${PILOT_EDITOR_PRINCIPAL}",
      "permission_level": "${DASHBOARD_EDITOR_PERMISSION}"
    },
    {
      "group_name": "${PILOT_REVIEWER_PRINCIPAL}",
      "permission_level": "${DASHBOARD_REVIEWER_PERMISSION}"
    }
  ]
}
JSON

databricks permissions update dashboards "${DASHBOARD_ID}" --json @/tmp/chec_phase2_dashboard_permissions.json

cat > /tmp/chec_phase2_directory_permissions.json <<JSON
{
  "access_control_list": [
    {
      "user_name": "${PILOT_EDITOR_PRINCIPAL}",
      "permission_level": "${DIRECTORY_EDITOR_PERMISSION}"
    }
${DIRECTORY_REVIEWER_ACL}
  ]
}
JSON

databricks permissions update directories "${NOTEBOOK_DIR_OBJECT_ID}" --json @/tmp/chec_phase2_directory_permissions.json

if [[ -n "${JOB_ID}" ]]; then
  job_owner_acl="$(
    if [[ -n "${JOB_OWNER_USER_NAME}" ]]; then
      cat <<JSON
    {
      "user_name": "${JOB_OWNER_USER_NAME}",
      "permission_level": "IS_OWNER"
    }
JSON
    else
      cat <<JSON
    {
      "group_name": "${JOB_OWNER_GROUP_NAME}",
      "permission_level": "IS_OWNER"
    }
JSON
    fi
  )"

  job_editor_acl=""
  if [[ "${PILOT_EDITOR_PRINCIPAL}" != "${JOB_OWNER_USER_NAME}" ]]; then
    job_editor_acl="$(cat <<JSON
    ,
    {
      "user_name": "${PILOT_EDITOR_PRINCIPAL}",
      "permission_level": "${JOB_EDITOR_PERMISSION}"
    }
JSON
)"
  fi

  cat > /tmp/chec_phase2_job_permissions.json <<JSON
{
  "access_control_list": [
${job_owner_acl}
${job_editor_acl}
  ]
}
JSON
  databricks permissions update jobs "${JOB_ID}" --json @/tmp/chec_phase2_job_permissions.json
fi

reviewer_catalog_change=""
if [[ "${GRANT_REVIEWER_DATA_ACCESS}" == "true" ]]; then
  reviewer_catalog_change="$(cat <<JSON
    ,
    {
      "principal": "${PILOT_REVIEWER_PRINCIPAL}",
      "add": ["USE_CATALOG"]
    }
JSON
)"
fi

cat > /tmp/chec_phase2_catalog_grants.json <<JSON
{
  "changes": [
    {
      "principal": "${PILOT_EDITOR_PRINCIPAL}",
      "add": ["USE_CATALOG"]
    }
${reviewer_catalog_change}
  ]
}
JSON

databricks grants update catalog "${CATALOG_NAME}" --json @/tmp/chec_phase2_catalog_grants.json

for schema_name in gold silver; do
  reviewer_schema_change=""
  if [[ "${GRANT_REVIEWER_DATA_ACCESS}" == "true" ]]; then
    reviewer_schema_change="$(cat <<JSON
    ,
    {
      "principal": "${PILOT_REVIEWER_PRINCIPAL}",
      "add": ["USE_SCHEMA", "SELECT"]
    }
JSON
)"
  fi

  cat > "/tmp/chec_phase2_${schema_name}_grants.json" <<JSON
{
  "changes": [
    {
      "principal": "${PILOT_EDITOR_PRINCIPAL}",
      "add": ["USE_SCHEMA", "SELECT"]
    }
${reviewer_schema_change}
  ]
}
JSON
  databricks grants update schema "${CATALOG_NAME}.${schema_name}" --json @"/tmp/chec_phase2_${schema_name}_grants.json"
done

echo "Applied pilot permissions for dashboard, shared notebooks, scheduled refresh job, and gold/silver read access."
