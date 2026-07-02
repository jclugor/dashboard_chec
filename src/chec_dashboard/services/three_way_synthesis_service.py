from __future__ import annotations

from typing import Any

from chec_dashboard.services.capability_registry import capability_metadata, utc_now


def build_three_way_context(
    *,
    structured_evidence: dict[str, Any] | None = None,
    documentary_evidence: dict[str, Any] | None = None,
    model_evidence: dict[str, Any] | None = None,
    feature_masks: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    structured_available = bool(structured_evidence)
    documentary_available = _available(documentary_evidence)
    model_available = _available(model_evidence)
    status = "available" if structured_available and documentary_available and model_available else "partial"
    missing = []
    if not structured_available:
        missing.append("structured historical/time-series evidence")
    if not documentary_available:
        missing.append("documentary or normative evidence")
    if not model_available:
        missing.append("model prediction evidence")
    if feature_masks and not _available(feature_masks):
        missing.append("feature relevance masks")
    return {
        "status": status,
        "capability_id": "three_way_synthesis",
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "selected_context": structured_evidence or {},
        "evidence": {
            "structured": structured_evidence or {},
            "documentary": documentary_evidence or {},
            "model": model_evidence or {},
            "feature_masks": feature_masks or {},
        },
        "missing_evidence": missing,
        "guardrails": {
            "no_definitive_causality": True,
            "cite_documentary_claims": True,
            "model_signals_not_causal_proof": True,
            "simulation_not_executed_unless_requested": True,
        },
        "limitations": [
            "La sintesis causal es una preparacion de contexto; la narrativa debe declarar limitaciones.",
            "Las senales del modelo no son prueba causal.",
        ],
        "warnings": ["La evidencia esta incompleta." if missing else "Todas las fuentes declaradas estan disponibles."],
        "trace_id": trace_id,
        "traceability": capability_metadata("three_way_synthesis", status=status),
    }


def _available(payload: dict[str, Any] | None) -> bool:
    return isinstance(payload, dict) and payload.get("status") not in {"unavailable", "not_configured", "not_provided", "error"} and bool(payload)
