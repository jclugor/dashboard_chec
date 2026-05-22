#!/usr/bin/env bash
set -euo pipefail

DASHBOARD_NAME_SUFFIX="${DASHBOARD_NAME_SUFFIX:-CHEC Summary Pilot}"
WAREHOUSE_ID="${WAREHOUSE_ID:-4437a6195e05c59c}"
PUBLISH_EMBED_CREDENTIALS="${PUBLISH_EMBED_CREDENTIALS:-true}"

DASHBOARD_ID="$(databricks lakeview list -o json | jq -r --arg suffix "${DASHBOARD_NAME_SUFFIX}" '.[] | select(.display_name | endswith($suffix)) | .dashboard_id' | head -n 1)"

if [[ -z "${DASHBOARD_ID}" ]]; then
  echo "Could not find dashboard whose display name ends with '${DASHBOARD_NAME_SUFFIX}'."
  exit 1
fi

echo "Publishing dashboard suffix ${DASHBOARD_NAME_SUFFIX} (${DASHBOARD_ID})"
if [[ "${PUBLISH_EMBED_CREDENTIALS}" == "true" ]]; then
  databricks lakeview publish "${DASHBOARD_ID}" --warehouse-id "${WAREHOUSE_ID}" --embed-credentials
else
  databricks lakeview publish "${DASHBOARD_ID}" --warehouse-id "${WAREHOUSE_ID}"
fi

databricks lakeview get-published "${DASHBOARD_ID}" -o json
