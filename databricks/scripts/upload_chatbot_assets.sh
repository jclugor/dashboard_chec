#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHEC_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

CATALOG_NAME="${CATALOG_NAME:-chec_dbx_demo}"
SOURCE_VOLUME_NAME="${SOURCE_VOLUME_NAME:-source_files}"
DOCS_SOURCE_DIR="${CHATBOT_SOURCE_DOCS_DIR:-${CHEC_ROOT}/Dashboard_CHEC/Unstructured_Files}"
VARIABLES_SOURCE_DIR="${CHATBOT_VARIABLES_SOURCE_DIR:-${CHEC_ROOT}/data/arbol_decision_recomendaciones}"
CORPUS_SOURCE_DIR="${CHATBOT_CORPUS_SOURCE_DIR:-${CHEC_ROOT}/data/chatbot_corpus}"
SKILLS_SOURCE_DIR="${CHATBOT_SKILLS_SOURCE_DIR:-${CHEC_ROOT}/dashboard/src/chec_dashboard/agent_skills/active}"
KNOWLEDGE_SOURCE_DIR="${CHATBOT_KNOWLEDGE_SOURCE_DIR:-${CHEC_ROOT}/dashboard/src/chec_dashboard/agent_knowledge}"
PROMPTS_SOURCE_DIR="${CHATBOT_PROMPTS_SOURCE_DIR:-${CHEC_ROOT}/dashboard/src/chec_dashboard/agent_prompts}"
CONTRACTS_SOURCE_DIR="${CHATBOT_CONTRACTS_SOURCE_DIR:-${CHEC_ROOT}/dashboard/src/chec_dashboard/agent_contracts}"
VALIDATE_CHATBOT_SKILLS="${VALIDATE_CHATBOT_SKILLS:-true}"

DOCS_TARGET_ROOT="dbfs:/Volumes/${CATALOG_NAME}/raw/${SOURCE_VOLUME_NAME}/chatbot_documents"
CORPUS_TARGET_ROOT="dbfs:/Volumes/${CATALOG_NAME}/raw/${SOURCE_VOLUME_NAME}/chatbot_corpus"
SKILLS_VOLUME_ROOT="dbfs:/Volumes/${CATALOG_NAME}/agent_config/skills"
SKILLS_TARGET_ROOT="${SKILLS_VOLUME_ROOT}/active"
KNOWLEDGE_TARGET_ROOT="${SKILLS_VOLUME_ROOT}/knowledge"
PROMPTS_TARGET_ROOT="${SKILLS_VOLUME_ROOT}/prompts"
CONTRACTS_TARGET_ROOT="${SKILLS_VOLUME_ROOT}/contracts"

CURATED_DOCS=(
  "retie.pdf"
  "resolucion_40117.pdf"
  "resolucion_creg_0015_2018.pdf"
  "capitulo_2.pdf"
  "capitulo_3_4f307f3c-549f-4545-818a-6b780177afab.pdf"
  "normativa_apoyos_1df64bf1-f470-4a41-8350-a8340597edf8.pdf"
)

CORPUS_FILES=(
  "chunks.jsonl"
  "documents_manifest.json"
  "variables_manifest.json"
)

SKILL_FILES=(
  "confiabilidad.yml"
  "cumplimiento.yml"
  "mantenimiento.yml"
  "time_series_interpretability.yml"
  "free_form_chat.yml"
  "global_policy.yml"
  "retrieval_policy.yml"
  "structured_context_builder.yml"
  "critical_point_interpreter.yml"
  "uiti_vano_behavior_explainer.yml"
  "domain_grounding_guardrails.yml"
  "citation_and_evidence_policy.yml"
  "rag_evidence_retrieval.yml"
  "documentary_normative_analyst.yml"
  "predictive_model_interpreter.yml"
  "feature_mask_interpreter.yml"
  "three_way_causal_synthesis.yml"
  "intervention_candidate_selector.yml"
  "what_if_simulation_assistant.yml"
  "evidence_report_writer.yml"
  "llm_output_validator.yml"
)

KNOWLEDGE_FILES=(
  "variable_context.yml"
  "variable_context.md"
  "variable_interactions.yml"
  "variable_interactions.md"
  "intervention_variable_registry.example.yml"
)

PROMPT_FILES=(
  "structured_context_builder.v1.md"
  "critical_point_interpreter.v1.md"
  "uiti_vano_behavior_explainer.v1.md"
  "documentary_normative_analyst.v1.md"
  "predictive_model_interpreter.v1.md"
  "feature_mask_interpreter.v1.md"
  "three_way_causal_synthesis.v1.md"
  "intervention_candidate_selector.v1.md"
  "what_if_simulation_assistant.v1.md"
  "evidence_report_writer.v1.md"
)

CONTRACT_FILES=(
  "structured_context.schema.json"
  "critical_point_interpretation.schema.json"
  "rag_evidence.schema.json"
  "documentary_analysis.schema.json"
  "model_evidence.schema.json"
  "feature_masks.schema.json"
  "three_way_synthesis.schema.json"
  "intervention_candidates.schema.json"
  "what_if_request.schema.json"
  "what_if_result.schema.json"
  "evidence_report.schema.json"
  "llm_validation.schema.json"
)

SKILL_LIFECYCLE_DIRS=(
  "active"
  "draft"
  "archive"
  "knowledge"
  "prompts"
  "contracts"
)

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

upload_file() {
  local source_path="$1"
  local target_path="$2"
  local target_dir

  if [[ ! -f "${source_path}" ]]; then
    echo "Skipping missing file: ${source_path}" >&2
    return 0
  fi

  target_dir="$(dirname "${target_path}")"
  databricks fs mkdir "${target_dir}" >/dev/null
  databricks fs cp "${source_path}" "${target_path}" --overwrite >/dev/null
  echo "Uploaded ${source_path} -> ${target_path}"
}

ensure_directory() {
  local target_dir="$1"
  databricks fs mkdir "${target_dir}" >/dev/null
}

validate_chatbot_skills() {
  local python_bin="${PYTHON_BIN:-${CHEC_ROOT}/dashboard/.venv/bin/python}"
  if [[ "${VALIDATE_CHATBOT_SKILLS}" != "true" ]]; then
    echo "Skipping governed chatbot skill validation."
    return 0
  fi
  if [[ ! -x "${python_bin}" ]]; then
    python_bin="${PYTHON_BIN:-python3}"
  fi
  PYTHONPATH="${CHEC_ROOT}/dashboard/src${PYTHONPATH:+:${PYTHONPATH}}" \
    "${python_bin}" "${CHEC_ROOT}/dashboard/databricks/scripts/validate_chatbot_skills.py" "${SKILLS_SOURCE_DIR}"
}

require_command databricks

validate_chatbot_skills

echo "Uploading curated chatbot documents from ${DOCS_SOURCE_DIR}"
for relative_path in "${CURATED_DOCS[@]}"; do
  upload_file "${DOCS_SOURCE_DIR}/${relative_path}" "${DOCS_TARGET_ROOT}/${relative_path}"
done

echo "Uploading variable mapping workbooks from ${VARIABLES_SOURCE_DIR}"
if [[ -d "${VARIABLES_SOURCE_DIR}" ]]; then
  while IFS= read -r workbook; do
    relative_path="${workbook#${VARIABLES_SOURCE_DIR}/}"
    upload_file "${workbook}" "${DOCS_TARGET_ROOT}/arbol_decision_recomendaciones/${relative_path}"
  done < <(find "${VARIABLES_SOURCE_DIR}" -type f -name '*.xlsx' | sort)
else
  echo "Skipping missing variable mapping directory: ${VARIABLES_SOURCE_DIR}" >&2
fi

echo "Uploading generated chatbot corpus from ${CORPUS_SOURCE_DIR}"
for relative_path in "${CORPUS_FILES[@]}"; do
  upload_file "${CORPUS_SOURCE_DIR}/${relative_path}" "${CORPUS_TARGET_ROOT}/${relative_path}"
done

echo "Ensuring governed chatbot skill lifecycle directories under ${SKILLS_VOLUME_ROOT}"
for relative_path in "${SKILL_LIFECYCLE_DIRS[@]}"; do
  ensure_directory "${SKILLS_VOLUME_ROOT}/${relative_path}"
done

echo "Uploading governed chatbot skills from ${SKILLS_SOURCE_DIR}"
for relative_path in "${SKILL_FILES[@]}"; do
  upload_file "${SKILLS_SOURCE_DIR}/${relative_path}" "${SKILLS_TARGET_ROOT}/${relative_path}"
done

echo "Uploading governed agent knowledge from ${KNOWLEDGE_SOURCE_DIR}"
for relative_path in "${KNOWLEDGE_FILES[@]}"; do
  upload_file "${KNOWLEDGE_SOURCE_DIR}/${relative_path}" "${KNOWLEDGE_TARGET_ROOT}/${relative_path}"
done

echo "Uploading governed stage prompts from ${PROMPTS_SOURCE_DIR}"
for relative_path in "${PROMPT_FILES[@]}"; do
  upload_file "${PROMPTS_SOURCE_DIR}/${relative_path}" "${PROMPTS_TARGET_ROOT}/${relative_path}"
done

echo "Uploading governed agent contracts from ${CONTRACTS_SOURCE_DIR}"
for relative_path in "${CONTRACT_FILES[@]}"; do
  upload_file "${CONTRACTS_SOURCE_DIR}/${relative_path}" "${CONTRACTS_TARGET_ROOT}/${relative_path}"
done

echo "Chatbot assets uploaded to ${DOCS_TARGET_ROOT}, ${CORPUS_TARGET_ROOT}, ${SKILLS_TARGET_ROOT}, ${KNOWLEDGE_TARGET_ROOT}, ${PROMPTS_TARGET_ROOT}, and ${CONTRACTS_TARGET_ROOT}"
