from __future__ import annotations

from typing import Any

from chec_dashboard.services.capability_registry import capability_metadata, utc_now


def build_evidence_report_context(
    *,
    structured_context: dict[str, Any] | None = None,
    critical_points: dict[str, Any] | list[dict[str, Any]] | None = None,
    documentary_evidence: dict[str, Any] | None = None,
    normative_evidence: dict[str, Any] | None = None,
    model_evidence: dict[str, Any] | None = None,
    feature_masks: dict[str, Any] | None = None,
    intervention_candidates: dict[str, Any] | None = None,
    what_if_results: dict[str, Any] | None = None,
    validation_metadata: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> dict[str, Any]:
    missing = []
    if not structured_context:
        missing.append("structured_context")
    if not documentary_evidence:
        missing.append("documentary_evidence")
    if not model_evidence or model_evidence.get("status") in {"unavailable", "not_configured", "not_provided"}:
        missing.append("model_evidence")
    if not what_if_results or what_if_results.get("status") in {"unavailable", "not_configured", "not_provided"}:
        missing.append("what_if_results")
    status = "partial" if missing else "available"
    return {
        "status": status,
        "capability_id": "evidence_report",
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "report_state": "draft_context_only" if missing else "ready_for_llm_draft",
        "selected_context": structured_context or {},
        "critical_points": critical_points or [],
        "documentary_evidence": documentary_evidence or {},
        "normative_evidence": normative_evidence or {},
        "model_evidence": model_evidence or {},
        "feature_masks": feature_masks or {},
        "intervention_candidates": intervention_candidates or {},
        "what_if_results": what_if_results or {},
        "validation_metadata": validation_metadata or {},
        "missing_evidence": missing,
        "limitations": [
            "El reporte no debe incluir conclusiones legales finales.",
            "No se deben inventar citas normativas, predicciones ni resultados de simulacion.",
        ],
        "warnings": ["Contexto de reporte parcial." if missing else "Contexto de reporte completo segun evidencias recibidas."],
        "trace_id": trace_id,
        "traceability": capability_metadata("evidence_report", status=status),
    }
