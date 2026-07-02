from __future__ import annotations

import json
from typing import Any

from chec_dashboard.services.agent_contract_service import validate_contract_payload
from chec_dashboard.services.capability_registry import CapabilityStatus
from chec_dashboard.services.citation_validation_service import validate_output_citations
from chec_dashboard.services.evidence_policy_service import classify_claim, contains_forbidden_claim, safe_claim_language


def validate_llm_output(
    output: str | dict[str, Any],
    *,
    contract_name: str | None = None,
    chunks: list[dict[str, Any]] | None = None,
    context_package: dict[str, Any] | None = None,
    capability_payload: dict[str, Any] | None = None,
    analysis_stage: str | None = None,
) -> dict[str, Any]:
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
    errors: list[str] = []
    warnings: list[str] = []
    schema_validation: dict[str, Any] | None = None

    if contract_name:
        payload = _coerce_payload(output)
        if payload is None:
            errors.append("invalid_json_output")
        else:
            schema_validation = validate_contract_payload(contract_name, payload)
            if not schema_validation["valid"]:
                errors.extend(f"schema:{error}" for error in schema_validation["errors"])

    if contains_forbidden_claim(text):
        claim_type = classify_claim(text)
        errors.append(f"forbidden_claim:{claim_type}")
        warnings.append(safe_claim_language(claim_type))

    citation_validation = validate_output_citations(text, chunks or [])
    if not citation_validation["valid"]:
        errors.extend(f"citation:{error}" for error in citation_validation["errors"])
        warnings.extend(citation_validation["warnings"])

    capability_status = str((capability_payload or {}).get("status") or "")
    if capability_status in {"unavailable", "not_configured", "not_provided"}:
        forbidden_present_claims = _unavailable_present_claim_errors(text, capability_status)
        errors.extend(forbidden_present_claims)
        if forbidden_present_claims:
            warnings.append("La salida afirma resultados de una capacidad que no se ejecuto.")

    unavailable_variables = set(str(item) for item in (context_package or {}).get("unavailable_variables", []) if item)
    for variable in unavailable_variables:
        if variable and variable.lower() in text.lower():
            errors.append(f"unavailable_variable_referenced:{variable}")

    return {
        "valid": not errors,
        "analysis_stage": analysis_stage,
        "validation_status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "schema_validation": schema_validation,
        "citation_validation": citation_validation,
        "fallback_text": fallback_text(capability_payload=capability_payload, errors=errors),
    }


def fallback_text(
    *,
    capability_payload: dict[str, Any] | None,
    errors: list[str] | None = None,
) -> str:
    payload = capability_payload or {}
    if payload.get("status") in {"unavailable", "not_configured", "not_provided"}:
        capability_id = str(payload.get("capability_id") or "capacidad")
        reason = str(payload.get("reason") or "La capacidad no esta disponible.")
        missing = payload.get("missing_requirements") or []
        missing_text = " ".join(str(item) for item in missing[:4])
        return (
            f"La etapa '{capability_id}' esta registrada en la arquitectura, pero todavia no tiene una "
            f"implementacion productiva conectada. {reason} No se generaron resultados inventados. "
            f"Requisitos faltantes: {missing_text or 'por definir'}."
        )
    if errors:
        return (
            "La salida del LLM no paso las validaciones de evidencia y seguridad. "
            "No se presenta como analisis autoritativo; revisa la metadata de validacion."
        )
    return ""


def _coerce_payload(output: str | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(output, dict):
        return output
    try:
        payload = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _unavailable_present_claim_errors(text: str, status: str) -> list[str]:
    lowered = text.lower()
    guarded_terms = (
        "se ejecuto simulacion",
        "se ejecutó simulación",
        "prediccion generada",
        "predicción generada",
        "deltas",
        "resultado what-if",
        "mascara calculada",
        "máscara calculada",
    )
    return [f"unavailable_capability_claimed_present:{status}" for term in guarded_terms if term in lowered]
