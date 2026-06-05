#!/usr/bin/env bash

set -euo pipefail

REGION="${AZURE_REGION:-eastus}"
CATALOG_NAME="${CATALOG_NAME:-chec_dbx_demo}"
BOOTSTRAP_CLASSIC_SKU="${BOOTSTRAP_CLASSIC_SKU:-Standard_DC4as_v5}"
INGEST_CLASSIC_SKU="${INGEST_CLASSIC_SKU:-Standard_L4aos_v4}"
LEGACY_BLOCKED_SKU="${LEGACY_BLOCKED_SKU:-Standard_D4as_v5}"
CHECK_CLASSIC_SKU_FALLBACKS="${CHECK_CLASSIC_SKU_FALLBACKS:-true}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

run_with_retries() {
  local attempts="$1"
  local delay_seconds="$2"
  shift 2

  local attempt=1
  local output
  local status

  while true; do
    if output="$("$@" 2>&1)"; then
      printf '%s' "${output}"
      return 0
    fi

    status=$?
    if [[ "${attempt}" -ge "${attempts}" ]]; then
      echo "${output}" >&2
      return "${status}"
    fi

    echo "Transient failure running '$*' (attempt ${attempt}/${attempts}). Retrying in ${delay_seconds}s..." >&2
    echo "${output}" >&2
    sleep "${delay_seconds}"
    attempt=$((attempt + 1))
  done
}

extract_json_payload() {
  local raw_output="$1"

  printf '%s\n' "${raw_output}" | awk '
    BEGIN {printing = 0}
    /^[[:space:]]*[\[{]/ {printing = 1}
    printing {print}
  '
}

require_command az
require_command databricks
require_command jq

echo "== CHEC phase 1 deploy preflight =="
echo "Region: ${REGION}"
echo "Target catalog: ${CATALOG_NAME}"
echo

account_json="$(extract_json_payload "$(run_with_retries 3 5 az account show -o json)")"
subscription_name="$(echo "${account_json}" | jq -r '.name')"
subscription_id="$(echo "${account_json}" | jq -r '.id')"
signed_in_user="$(echo "${account_json}" | jq -r '.user.name // "unknown"')"

echo "Azure subscription: ${subscription_name} (${subscription_id})"
echo "Azure principal: ${signed_in_user}"
echo

metastore_json="$(extract_json_payload "$(run_with_retries 3 5 databricks metastores current -o json)")"
metastore_id="$(echo "${metastore_json}" | jq -r '.metastore_id // empty')"
default_catalog_name="$(echo "${metastore_json}" | jq -r '.default_catalog_name // empty')"
workspace_id="$(echo "${metastore_json}" | jq -r '.workspace_id // empty')"

if [[ -z "${metastore_id}" ]]; then
  echo "Databricks Unity Catalog check failed: no metastore is attached to the current workspace." >&2
  exit 1
fi

echo "Databricks workspace ID: ${workspace_id}"
echo "Metastore ID: ${metastore_id}"
if [[ -n "${default_catalog_name}" ]]; then
  echo "Current default catalog: ${default_catalog_name}"
fi
if [[ "${CATALOG_NAME}" != "${default_catalog_name}" ]]; then
  echo "Catalog note: ${CATALOG_NAME} is not the current default managed catalog. Pre-create it in the UI or pass a managed catalog name before running bootstrap."
fi
echo

if [[ "${CHECK_CLASSIC_SKU_FALLBACKS}" == "true" ]]; then
  node_types_json="$(extract_json_payload "$(run_with_retries 3 5 databricks clusters list-node-types -o json)")"
  enabled_small_node_types="$(
    echo "${node_types_json}" | jq -r '
      [.node_types[]
        | select((.node_info.status // []) | length == 0)
        | select(.num_cores <= 4)
        | "\(.node_type_id)\t\(.num_cores)\t\(.memory_mb)\t\(.category)"
      ] | .[]
    '
  )"

  if [[ -z "${enabled_small_node_types}" ]]; then
    echo "Databricks node type check failed: no enabled 4-core-or-smaller node types were returned." >&2
    exit 1
  fi

  echo "Enabled Databricks node types with <=4 cores:"
  printf '  %s\n' "${enabled_small_node_types//$'\n'/$'\n''  '}"
  echo

  for approved_sku in "${BOOTSTRAP_CLASSIC_SKU}" "${INGEST_CLASSIC_SKU}"; do
    if ! echo "${enabled_small_node_types}" | cut -f1 | grep -qx "${approved_sku}"; then
      echo "Databricks node type check failed: ${approved_sku} is not enabled in this workspace." >&2
      exit 1
    fi
  done
else
  echo "Skipping Databricks node type and classic fallback SKU checks because CHECK_CLASSIC_SKU_FALLBACKS=false."
fi

check_sku_restrictions() {
  local sku="$1"
  local sku_json
  local restriction_count

  sku_json="$(extract_json_payload "$(
    run_with_retries 3 5 \
    az vm list-skus \
      --location "${REGION}" \
      --size "${sku}" \
      --resource-type virtualMachines \
      --all \
      --query "[].{name:name,restrictions:restrictions}" \
      -o json
  )")"
  if [[ "$(echo "${sku_json}" | jq 'length')" -eq 0 ]]; then
    echo "Azure SKU check failed: ${sku} was not returned for region ${REGION}." >&2
    exit 1
  fi

  restriction_count="$(echo "${sku_json}" | jq '.[0].restrictions // [] | length')"
  if [[ "${restriction_count}" -ne 0 ]]; then
    echo "Azure SKU check failed: ${sku} has restrictions in ${REGION}." >&2
    echo "${sku_json}" | jq '.[0].restrictions'
    exit 1
  fi

  echo "Approved classic SKU ${sku} is unrestricted in ${REGION}."
}

if [[ "${CHECK_CLASSIC_SKU_FALLBACKS}" == "true" ]]; then
  usage_json="$(extract_json_payload "$(run_with_retries 3 5 az vm list-usage -l "${REGION}" -o json)")"
  regional_limit="$(echo "${usage_json}" | jq -r 'map(select(.name.localizedValue == "Total Regional vCPUs"))[0].limit // 0')"

  if [[ "${regional_limit}" -lt 4 ]]; then
    echo "Azure quota check failed: Total Regional vCPUs in ${REGION} is ${regional_limit}, but phase 1 needs at least 4." >&2
    exit 1
  fi

  echo "Relevant Azure vCPU quota rows:"
  echo "${usage_json}" | jq -r '
    map(select(
      .name.localizedValue == "Total Regional vCPUs"
      or (.name.localizedValue | test("DCASv5|Laosv4|NCASv3_T4"; "i"))
    ))
    | .[]
    | "  \(.name.localizedValue): current=\(.currentValue) limit=\(.limit)"
  '
  echo

  check_sku_restrictions "${BOOTSTRAP_CLASSIC_SKU}"
  check_sku_restrictions "${INGEST_CLASSIC_SKU}"

  legacy_sku_json="$(extract_json_payload "$(
    run_with_retries 3 5 \
    az vm list-skus \
      --location "${REGION}" \
      --size "${LEGACY_BLOCKED_SKU}" \
      --resource-type virtualMachines \
      --all \
      --query "[].{name:name,restrictions:restrictions}" \
      -o json
  )")"
  legacy_restrictions="$(echo "${legacy_sku_json}" | jq '.[0].restrictions // []')"

  if [[ "$(echo "${legacy_restrictions}" | jq 'length')" -gt 0 ]]; then
    echo "Legacy D-series check: ${LEGACY_BLOCKED_SKU} remains restricted in ${REGION}, so serverless-first is still the correct default."
  else
    echo "Legacy D-series check: ${LEGACY_BLOCKED_SKU} is currently unrestricted in ${REGION}; rerun a bundle preflight before changing defaults."
  fi
else
  echo "Skipping Azure vCPU quota and SKU restriction checks for classic fallback jobs."
fi
echo

echo "Preflight PASSED."
echo "Recommended deploy path:"
echo "  1. databricks bundle validate -t dev"
echo "  2. databricks bundle deploy -t dev"
echo "  3. databricks bundle run -t dev chec_phase1_bootstrap"
echo "  4. bash scripts/upload_phase1_assets.sh"
echo "  5. databricks bundle run -t dev chec_phase1_ingest_validation"
echo
echo "Classic fallback jobs are available if serverless is blocked later:"
echo "  - chec_phase1_bootstrap_classic (${BOOTSTRAP_CLASSIC_SKU})"
echo "  - chec_phase1_ingest_validation_classic (${INGEST_CLASSIC_SKU})"
