#!/usr/bin/env bash
set -euo pipefail

DASHBOARD_NAME_SUFFIX="${DASHBOARD_NAME_SUFFIX:-CHEC Summary Pilot}"
OUTPUT_PATH="${OUTPUT_PATH:-/home/jclugor/unal/CHEC/dashboard/databricks/dashboards/chec_summary_pilot.lvdash.json}"
TMP_DIR="${TMP_DIR:-/tmp}"

DASHBOARD_ID="$(databricks lakeview list -o json | jq -r --arg suffix "${DASHBOARD_NAME_SUFFIX}" '.[] | select(.display_name | endswith($suffix)) | .dashboard_id' | head -n 1)"
if [[ -z "${DASHBOARD_ID}" ]]; then
  echo "Could not find dashboard whose display name ends with '${DASHBOARD_NAME_SUFFIX}'." >&2
  exit 1
fi

mkdir -p "$(dirname "${OUTPUT_PATH}")"
timestamp="$(date +%Y%m%d%H%M%S)"
backup_path="${TMP_DIR}/$(basename "${OUTPUT_PATH}").${timestamp}.bak"
if [[ -f "${OUTPUT_PATH}" ]]; then
  cp "${OUTPUT_PATH}" "${backup_path}"
  echo "Backed up existing dashboard JSON to ${backup_path}"
fi

raw_tmp="${TMP_DIR}/chec_phase2_dashboard_${timestamp}.raw.json"
pretty_tmp="${TMP_DIR}/chec_phase2_dashboard_${timestamp}.pretty.json"

databricks lakeview get "${DASHBOARD_ID}" -o json > "${raw_tmp}"
jq -r '.serialized_dashboard' "${raw_tmp}" | jq '.' > "${pretty_tmp}"
cp "${pretty_tmp}" "${OUTPUT_PATH}"

echo "Synced dashboard ${DASHBOARD_ID} to ${OUTPUT_PATH}"
