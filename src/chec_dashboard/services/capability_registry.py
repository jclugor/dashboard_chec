from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal


CapabilityTier = Literal[
    "existing_integrated",
    "implement_now",
    "skeleton_only",
    "deferred_external_dependency",
]

CapabilityStatus = Literal[
    "available",
    "partial",
    "unavailable",
    "not_configured",
    "not_provided",
    "error",
]


@dataclass(frozen=True)
class CapabilityDefinition:
    capability_id: str
    tier: CapabilityTier
    status: CapabilityStatus
    message: str
    required_settings: tuple[str, ...] = ()
    required_services: tuple[str, ...] = ()
    required_environment_variables: tuple[str, ...] = ()
    safe_to_call: bool = True
    fallback_behavior: str = "structured_unavailable_payload"


CAPABILITY_IDS = [
    "structured_context",
    "critical_point_interpretation",
    "uiti_vano_behavior_explanation",
    "rag_evidence_retrieval",
    "documentary_normative_analysis",
    "model_prediction",
    "feature_masks",
    "three_way_synthesis",
    "intervention_candidates",
    "what_if_simulation",
    "evidence_report",
]


CAPABILITY_REGISTRY: dict[str, CapabilityDefinition] = {
    "structured_context": CapabilityDefinition(
        "structured_context",
        "existing_integrated",
        "available",
        "El contexto estructurado del dashboard esta integrado mediante herramientas gobernadas.",
        required_services=("agent_context_service",),
    ),
    "critical_point_interpretation": CapabilityDefinition(
        "critical_point_interpretation",
        "existing_integrated",
        "available",
        "La interpretabilidad de puntos criticos de serie esta integrada para contexto de UITI.",
        required_services=("timeseries_interpretability",),
    ),
    "uiti_vano_behavior_explanation": CapabilityDefinition(
        "uiti_vano_behavior_explanation",
        "existing_integrated",
        "available",
        "La explicacion temporal de UITI_VANO usa el servicio de interpretabilidad existente.",
        required_services=("timeseries_interpretability",),
    ),
    "rag_evidence_retrieval": CapabilityDefinition(
        "rag_evidence_retrieval",
        "existing_integrated",
        "available",
        "La recuperacion documental usa JSONL local o Databricks AI Search cuando esta configurado.",
        required_settings=("retriever_backend",),
        required_services=("retrieval_service",),
    ),
    "documentary_normative_analysis": CapabilityDefinition(
        "documentary_normative_analysis",
        "implement_now",
        "partial",
        "El analisis documental se limita a fragmentos recuperados y citas validadas.",
        required_services=("retrieval_service", "citation_validation_service"),
    ),
    "model_prediction": CapabilityDefinition(
        "model_prediction",
        "skeleton_only",
        "unavailable",
        "La prediccion para etapas del chatbot requiere vector de inferencia y backend aprobado.",
        required_settings=("model_backend",),
        required_services=("inference_service", "model_evidence_service"),
        required_environment_variables=("MODEL_BACKEND",),
    ),
    "feature_masks": CapabilityDefinition(
        "feature_masks",
        "skeleton_only",
        "not_provided",
        "Las mascaras de relevancia solo se presentan si vienen en la respuesta real del modelo.",
        required_services=("feature_mask_service",),
    ),
    "three_way_synthesis": CapabilityDefinition(
        "three_way_synthesis",
        "skeleton_only",
        "partial",
        "La sintesis causal puede prepararse con evidencia parcial, sin causalidad definitiva.",
        required_services=("three_way_synthesis_service",),
    ),
    "intervention_candidates": CapabilityDefinition(
        "intervention_candidates",
        "skeleton_only",
        "unavailable",
        "La seleccion de intervenciones requiere un registro aprobado de variables intervenibles.",
        required_services=("intervention_candidate_service",),
    ),
    "what_if_simulation": CapabilityDefinition(
        "what_if_simulation",
        "skeleton_only",
        "unavailable",
        "La simulacion What-If requiere endpoint predictivo, variables permitidas y vector base.",
        required_settings=("model_backend", "databricks_model_endpoint"),
        required_services=("what_if_service", "inference_service"),
        required_environment_variables=("MODEL_BACKEND", "DATABRICKS_MODEL_ENDPOINT"),
    ),
    "evidence_report": CapabilityDefinition(
        "evidence_report",
        "skeleton_only",
        "partial",
        "El reporte se construye como contexto borrador hasta que todas las evidencias esten validadas.",
        required_services=("evidence_report_service",),
    ),
}


ANALYSIS_STAGE_CAPABILITY_IDS: dict[str, str] = {
    "structured_context": "structured_context",
    "critical_point_interpretation": "critical_point_interpretation",
    "uiti_vano_behavior_explanation": "uiti_vano_behavior_explanation",
    "documentary_analysis": "documentary_normative_analysis",
    "predictive_interpretation": "model_prediction",
    "feature_mask_interpretation": "feature_masks",
    "three_way_causal_synthesis": "three_way_synthesis",
    "intervention_selection": "intervention_candidates",
    "what_if_simulation": "what_if_simulation",
    "evidence_report": "evidence_report",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def get_capability_definition(capability_id: str) -> CapabilityDefinition:
    return CAPABILITY_REGISTRY.get(
        capability_id,
        CapabilityDefinition(
            capability_id,
            "skeleton_only",
            "unavailable",
            "La capacidad solicitada no esta registrada para ejecucion productiva.",
            safe_to_call=False,
        ),
    )


def capability_for_stage(analysis_stage: str | None) -> CapabilityDefinition | None:
    if not analysis_stage or analysis_stage == "guided_answer":
        return None
    capability_id = ANALYSIS_STAGE_CAPABILITY_IDS.get(str(analysis_stage))
    if capability_id is None:
        return None
    return get_capability_definition(capability_id)


def capability_metadata(
    capability_id: str,
    *,
    status: CapabilityStatus | None = None,
) -> dict[str, Any]:
    definition = get_capability_definition(capability_id)
    return {
        "capability_id": definition.capability_id,
        "capability_tier": definition.tier,
        "capability_status": status or definition.status,
        "capability_message": definition.message,
        "required_settings": list(definition.required_settings),
        "required_services": list(definition.required_services),
        "required_environment_variables": list(definition.required_environment_variables),
        "safe_to_call": definition.safe_to_call,
        "fallback_behavior": definition.fallback_behavior,
    }


def unavailable_payload(
    *,
    capability_id: str,
    reason: str,
    missing_requirements: list[str] | None = None,
    next_steps: list[str] | None = None,
    trace_id: str | None = None,
    status: CapabilityStatus = "unavailable",
) -> dict[str, Any]:
    definition = get_capability_definition(capability_id)
    return {
        "status": status,
        "capability_id": capability_id,
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "reason": reason,
        "missing_requirements": missing_requirements or [],
        "next_steps": next_steps or [],
        "trace_id": trace_id,
        "evidence": [],
        "warnings": [
            "Esta funcionalidad esta registrada en la arquitectura, pero aun no tiene una implementacion productiva conectada."
        ],
        "traceability": {
            "capability_tier": definition.tier,
            "safe_to_present": True,
        },
    }
