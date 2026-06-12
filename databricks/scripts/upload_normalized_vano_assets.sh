#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHEC_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

SOURCE_DATASET_DIR="${CHEC_NORMALIZED_DATASET_DIR:-${CHEC_ROOT}/data/Indicadores_vano_v3_normalized}"
CATALOG_NAME="${CATALOG_NAME:-chec_dbx_demo}"
SOURCE_VOLUME_NAME="${SOURCE_VOLUME_NAME:-source_files}"
TARGET_ROOT="dbfs:/Volumes/${CATALOG_NAME}/raw/${SOURCE_VOLUME_NAME}/Indicadores_vano_v3_normalized"

NORMALIZED_FILES=(
  "normalization_manifest.json"
  "causas.parquet"
  "equipos_proteccion.parquet"
  "apoyos.parquet"
  "vanos.parquet"
  "transformador_profiles.parquet"
  "eventos.parquet"
  "evento_vano_trafo.parquet"
  "clima_vano_fecha.parquet"
)

OPTIONAL_NORMALIZED_FILES=(
  "municipio_enrichment/municipio_lookup_manifest.json"
  "municipio_enrichment/unresolved_vanos.csv"
  "municipio_enrichment/unresolved_transformador_profiles.csv"
  "municipio_enrichment/unresolved_evento_vano_trafo_sample.csv"
  "municipio_enrichment/legacy_apoyos_municipio_conflicts.csv"
  "municipio_enrichment/legacy_trafos_municipio_conflicts.csv"
  "municipio_enrichment/legacy_apoyos_municipio_conflict_examples.csv"
  "municipio_enrichment/legacy_trafos_municipio_conflict_examples.csv"
)

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

remote_file_size() {
  local target_dir="$1"
  local file_name="$2"
  local listing_output
  local listing_json

  if ! listing_output="$(
    run_with_retries 3 5 \
      databricks fs ls "${target_dir}" -l -o json
  )"; then
    echo ""
    return 0
  fi

  listing_json="$(extract_json_payload "${listing_output}")"
  if [[ -z "${listing_json}" ]]; then
    echo ""
    return 0
  fi

  echo "${listing_json}" | jq -r --arg file_name "${file_name}" '
    [.[] | select(.name == $file_name and (.is_directory | not))][0].size // empty
  '
}

upload_file() {
  local relative_path="$1"
  local source_path="${SOURCE_DATASET_DIR}/${relative_path}"
  local target_path="${TARGET_ROOT}/${relative_path}"
  local target_dir
  local local_size
  local remote_size

  if [[ ! -f "${source_path}" ]]; then
    echo "Missing local normalized file: ${source_path}" >&2
    exit 1
  fi

  target_dir="$(dirname "${target_path}")"
  local_size="$(stat -c %s "${source_path}")"

  run_with_retries 3 5 databricks fs mkdir "${target_dir}" >/dev/null

  remote_size="$(remote_file_size "${target_dir}" "$(basename "${relative_path}")")"
  if [[ -n "${remote_size}" && "${remote_size}" == "${local_size}" ]]; then
    echo "Skipping ${relative_path}; already uploaded (${local_size} bytes)."
    return 0
  fi

  run_with_retries 3 5 databricks fs cp "${source_path}" "${target_path}" --overwrite >/dev/null

  remote_size="$(remote_file_size "${target_dir}" "$(basename "${relative_path}")")"
  if [[ "${remote_size}" != "${local_size}" ]]; then
    echo "Upload verification failed for ${relative_path}: expected ${local_size} bytes, found ${remote_size:-missing}." >&2
    exit 1
  fi

  echo "Uploaded ${relative_path}"
}

require_command databricks
require_command jq

if [[ ! -d "${SOURCE_DATASET_DIR}" ]]; then
  echo "Normalized dataset directory not found: ${SOURCE_DATASET_DIR}" >&2
  exit 1
fi

echo "Uploading normalized vano dataset from ${SOURCE_DATASET_DIR}"
for relative_path in "${NORMALIZED_FILES[@]}"; do
  upload_file "${relative_path}"
done

for relative_path in "${OPTIONAL_NORMALIZED_FILES[@]}"; do
  if [[ -f "${SOURCE_DATASET_DIR}/${relative_path}" ]]; then
    upload_file "${relative_path}"
  fi
done

echo "Normalized vano dataset uploaded to ${TARGET_ROOT}"
