from __future__ import annotations

from copy import deepcopy
from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.capability_registry import capability_metadata, unavailable_payload, utc_now
from chec_dashboard.services.intervention_candidate_service import get_allowed_intervention_variables
from chec_dashboard.services.model_evidence_service import build_model_evidence_package, is_model_backend_available


def validate_what_if_request(
    request: dict[str, Any],
    *,
    allowed_variables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    allowed_lookup = {
        str(item.get("variable") or item.get("name") or ""): item
        for item in (allowed_variables or [])
        if isinstance(item, dict)
    }
    changes = deepcopy(request.get("changes") or request.get("scenario_values") or {})
    if not isinstance(changes, dict):
        return {"valid": False, "errors": ["changes_must_be_object"], "unsupported_variables": [], "validated_changes": {}}
    unsupported = [name for name in changes if name not in allowed_lookup]
    errors = [f"unsupported_variable:{name}" for name in unsupported]
    validated = {name: value for name, value in changes.items() if name in allowed_lookup}
    return {
        "valid": not errors,
        "errors": errors,
        "unsupported_variables": unsupported,
        "validated_changes": validated,
    }


def run_what_if_simulation(
    settings: Settings | None = None,
    *,
    request: dict[str, Any] | None = None,
    baseline_features: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    request_copy = deepcopy(request or {})
    registry = get_allowed_intervention_variables(settings)
    allowed_variables = registry.get("variables") if isinstance(registry, dict) else []
    if not allowed_variables:
        return unavailable_payload(
            capability_id="what_if_simulation",
            reason="What-if requiere un registro aprobado de variables intervenibles.",
            missing_requirements=["allowed intervention variable registry"],
            next_steps=["Definir el registro productivo de variables intervenibles."],
            trace_id=trace_id,
        )
    validation = validate_what_if_request(request_copy, allowed_variables=allowed_variables)
    if not validation["valid"]:
        return {
            **unavailable_payload(
                capability_id="what_if_simulation",
                reason="La solicitud contiene variables no permitidas para simulacion.",
                missing_requirements=["scenario request with allowed variables only"],
                next_steps=["Seleccionar variables desde el registro de intervenciones permitido."],
                trace_id=trace_id,
            ),
            "validation": validation,
        }
    if settings is None or not is_model_backend_available(settings):
        return unavailable_payload(
            capability_id="what_if_simulation",
            reason="What-if requiere un backend predictivo configurado.",
            missing_requirements=["DATABRICKS_MODEL_ENDPOINT or equivalent model backend"],
            next_steps=["Conectar endpoint predictivo y pruebas con backend mock/local."],
            trace_id=trace_id,
            status="not_configured",
        )
    if not baseline_features:
        return unavailable_payload(
            capability_id="what_if_simulation",
            reason="What-if requiere un vector base de inferencia.",
            missing_requirements=["baseline feature vector builder"],
            next_steps=["Construir vector base desde el contexto seleccionado sin mutar la fuente."],
            trace_id=trace_id,
        )

    scenario_features = deepcopy(baseline_features)
    scenario_features.update(validation["validated_changes"])
    baseline = build_model_evidence_package(settings, features=baseline_features, trace_id=trace_id)
    scenario = build_model_evidence_package(settings, features=scenario_features, trace_id=trace_id)
    deltas: dict[str, Any] = {}
    if baseline.get("status") == "available" and scenario.get("status") == "available":
        base_prediction = (baseline.get("prediction_values") or {}).get("prediction")
        scenario_prediction = (scenario.get("prediction_values") or {}).get("prediction")
        if isinstance(base_prediction, (int, float)) and isinstance(scenario_prediction, (int, float)):
            deltas["prediction"] = round(float(scenario_prediction) - float(base_prediction), 6)
    return {
        "status": "available" if deltas else "partial",
        "capability_id": "what_if_simulation",
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "baseline_model_evidence": baseline,
        "scenario_model_evidence": scenario,
        "deltas": deltas,
        "validation": validation,
        "unsupported_variables": validation["unsupported_variables"],
        "warnings": [
            "No se modifico la fuente de datos.",
            "Los deltas son senales del modelo, no prueba causal.",
        ],
        "trace_id": trace_id,
        "traceability": capability_metadata("what_if_simulation", status="available" if deltas else "partial"),
    }
