from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from chec_dashboard.core.config import Settings
from chec_dashboard.services.capability_registry import capability_metadata, unavailable_payload, utc_now
from chec_dashboard.services.retrieval_service import read_databricks_file_text


FORBIDDEN_VARIABLE_FRAGMENTS = (
    "id",
    "fecha",
    "date",
    "uiti",
    "saidi",
    "saifi",
    "target",
    "outcome",
    "causa",
)


def get_allowed_intervention_variables(settings: Settings | None = None) -> dict[str, Any]:
    if settings is None:
        return {}
    registry_path = _registry_path(settings)
    text = _read_text(registry_path)
    if not text:
        return {}
    try:
        payload = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(payload, dict):
        return {}
    variables = payload.get("variables") or []
    if not isinstance(variables, list):
        variables = []
    return {**payload, "variables": [item for item in variables if isinstance(item, dict)]}


def build_intervention_candidate_context(
    settings: Settings | None = None,
    *,
    evidence_context: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    registry = get_allowed_intervention_variables(settings)
    variables = registry.get("variables") if isinstance(registry, dict) else []
    if not variables:
        return unavailable_payload(
            capability_id="intervention_candidates",
            reason="No existe un registro productivo aprobado de variables intervenibles.",
            missing_requirements=["approved intervention variable registry"],
            next_steps=[
                "Definir variables tecnicamente intervenibles.",
                "Separar variables operacionales de variables solo de escenario.",
                "Agregar rangos permitidos y pruebas de validacion.",
            ],
            trace_id=trace_id,
        )
    candidates = []
    for variable in variables:
        name = str(variable.get("variable") or variable.get("name") or "").strip()
        if not name or _forbidden_variable(name):
            continue
        candidates.append(
            {
                "variable": name,
                "group": variable.get("group") or "operational",
                "rationale": variable.get("rationale") or "Variable incluida en registro aprobado.",
                "supporting_evidence": (evidence_context or {}).get("evidence", []),
                "constraints": variable.get("constraints") or [],
                "allowed_simulation_range": variable.get("allowed_simulation_range"),
                "warning": variable.get("warning"),
            }
        )
    status = "available" if candidates else "unavailable"
    return {
        "status": status,
        "capability_id": "intervention_candidates",
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "candidates": candidates,
        "evidence": (evidence_context or {}).get("evidence", []),
        "warnings": [] if candidates else ["El registro no contiene variables intervenibles validas."],
        "trace_id": trace_id,
        "traceability": capability_metadata("intervention_candidates", status=status),
    }


def _registry_path(settings: Settings) -> Path:
    if settings.chatbot_skills_dir is not None:
        return settings.chatbot_skills_dir.parent / "knowledge" / "intervention_variable_registry.yml"
    return Path(__file__).resolve().parents[1] / "agent_knowledge" / "intervention_variable_registry.yml"


def _read_text(path: Path) -> str | None:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return read_databricks_file_text(path)


def _forbidden_variable(name: str) -> bool:
    normalized = name.lower()
    return any(fragment in normalized for fragment in FORBIDDEN_VARIABLE_FRAGMENTS)
