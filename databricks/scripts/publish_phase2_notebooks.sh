#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_NOTEBOOK_DIR="${ROOT_DIR}/notebooks"
TARGET_WORKSPACE_DIR="${TARGET_WORKSPACE_DIR:-/Shared/CHEC Phase2 Pilot/Notebooks}"

NOTEBOOKS=(
  "04_probability_explorer.py"
  "06_map_explorer.py"
)

echo "Publishing Phase 2 pilot notebooks to ${TARGET_WORKSPACE_DIR}"
databricks workspace mkdirs "${TARGET_WORKSPACE_DIR}"

for notebook_name in "${NOTEBOOKS[@]}"; do
  source_path="${LOCAL_NOTEBOOK_DIR}/${notebook_name}"
  target_path="${TARGET_WORKSPACE_DIR}/${notebook_name%.py}"
  databricks workspace import "${target_path}" \
    --file "${source_path}" \
    --format SOURCE \
    --language PYTHON \
    --overwrite
  echo "Published ${notebook_name} -> ${target_path}"
done
