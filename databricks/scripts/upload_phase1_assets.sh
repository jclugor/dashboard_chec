#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHEC_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

SOURCE_DATA_DIR="${CHEC_SOURCE_DATA_DIR:-${CHEC_ROOT}/data}"
CATALOG_NAME="${CATALOG_NAME:-chec_dbx_demo}"
SOURCE_VOLUME_NAME="${SOURCE_VOLUME_NAME:-source_files}"
ARTIFACT_VOLUME_NAME="${ARTIFACT_VOLUME_NAME:-artifacts}"

RAW_TARGET_ROOT="dbfs:/Volumes/${CATALOG_NAME}/raw/${SOURCE_VOLUME_NAME}"
ARTIFACT_TARGET_ROOT="dbfs:/Volumes/${CATALOG_NAME}/ml/${ARTIFACT_VOLUME_NAME}"

RAW_FILES=(
  "TRAFOS.pkl"
  "APOYOS.pkl"
  "SWITCHES.pkl"
  "REDMT.pkl"
  "SuperEventos_Criticidad_AguasAbajo_CODEs.pkl"
  "Eventos_interruptor.pkl"
  "Eventos_tramo_linea.pkl"
  "Eventos_transformador.pkl"
  "Vegetacion.pkl"
  "Rayos.pkl"
  "arbol_decision_recomendaciones/variables_apoyo.xlsx"
  "arbol_decision_recomendaciones/variables_interruptor.xlsx"
  "arbol_decision_recomendaciones/variables_transformador.xlsx"
  "arbol_decision_recomendaciones/variables_tramo de linea.xlsx"
  "arbol_decision_recomendaciones/Temporal/variables_apoyos.xlsx"
  "arbol_decision_recomendaciones/Temporal/variables_interruptores.xlsx"
  "arbol_decision_recomendaciones/Temporal/variables_transformadores.xlsx"
)

ARTIFACT_FILES=(
  "model.pth"
  "mask.npy"
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
  local source_root="$1"
  local relative_path="$2"
  local target_root="$3"
  local source_path="${source_root}/${relative_path}"
  local target_path="${target_root}/${relative_path}"
  local target_dir
  local local_size
  local remote_size

  if [[ ! -f "${source_path}" ]]; then
    echo "Missing local file: ${source_path}" >&2
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

if [[ ! -d "${SOURCE_DATA_DIR}" ]]; then
  echo "Source data directory not found: ${SOURCE_DATA_DIR}" >&2
  exit 1
fi

echo "Uploading raw phase 1 assets from ${SOURCE_DATA_DIR}"
for relative_path in "${RAW_FILES[@]}"; do
  upload_file "${SOURCE_DATA_DIR}" "${relative_path}" "${RAW_TARGET_ROOT}"
done

echo "Uploading ML artifacts from ${SOURCE_DATA_DIR}"
for relative_path in "${ARTIFACT_FILES[@]}"; do
  upload_file "${SOURCE_DATA_DIR}" "${relative_path}" "${ARTIFACT_TARGET_ROOT}"
done

echo "Phase 1 assets uploaded to ${RAW_TARGET_ROOT} and ${ARTIFACT_TARGET_ROOT}"
