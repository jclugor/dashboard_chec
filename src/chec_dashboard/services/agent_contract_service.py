from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from chec_dashboard.core.config import Settings


CONTRACT_SCHEMA_VERSION = "0.1.0"

CONTRACT_FILES = {
    "structured_context": "structured_context.schema.json",
    "critical_point_interpretation": "critical_point_interpretation.schema.json",
    "rag_evidence": "rag_evidence.schema.json",
    "documentary_analysis": "documentary_analysis.schema.json",
    "model_evidence": "model_evidence.schema.json",
    "feature_masks": "feature_masks.schema.json",
    "three_way_synthesis": "three_way_synthesis.schema.json",
    "intervention_candidates": "intervention_candidates.schema.json",
    "what_if_request": "what_if_request.schema.json",
    "what_if_result": "what_if_result.schema.json",
    "evidence_report": "evidence_report.schema.json",
    "llm_validation": "llm_validation.schema.json",
}


def contracts_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "agent_contracts"


def load_contract_schema(contract_name: str) -> dict[str, Any]:
    file_name = CONTRACT_FILES.get(contract_name, f"{contract_name}.schema.json")
    path = contracts_dir() / file_name
    return json.loads(path.read_text(encoding="utf-8"))


def contract_hash(payload: dict[str, Any] | str) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def contract_metadata(contract_name: str) -> dict[str, Any]:
    schema = load_contract_schema(contract_name)
    return {
        "contract_name": contract_name,
        "contract_version": str(schema.get("schema_version") or CONTRACT_SCHEMA_VERSION),
        "contract_hash": contract_hash(schema),
    }


def validate_contract_payload(contract_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    schema = load_contract_schema(contract_name)
    required = list(schema.get("required") or [])
    missing = [field for field in required if field not in payload]
    required_properties = schema.get("properties") or {}
    type_errors: list[str] = []
    for field_name, rules in required_properties.items():
        if field_name not in payload or not isinstance(rules, dict):
            continue
        expected_type = rules.get("type")
        if expected_type and not _matches_json_type(payload[field_name], str(expected_type)):
            type_errors.append(f"{field_name}:expected_{expected_type}")
    errors = [f"missing:{field}" for field in missing] + type_errors
    return {
        "valid": not errors,
        "contract_name": contract_name,
        "contract_version": str(schema.get("schema_version") or CONTRACT_SCHEMA_VERSION),
        "contract_hash": contract_hash(schema),
        "errors": errors,
        "warnings": [],
    }


def save_contract_artifact(
    settings: Settings,
    *,
    contract_name: str,
    payload: dict[str, Any],
    artifact_name: str | None = None,
) -> Path:
    output_dir = settings.output_dir / "agent_contracts"
    output_dir.mkdir(parents=True, exist_ok=True)
    name = artifact_name or f"{contract_name}-{contract_hash(payload)}.json"
    path = output_dir / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def _matches_json_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return True
