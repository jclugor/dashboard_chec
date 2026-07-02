from __future__ import annotations

from typing import Any


STAGE_INCLUDED_STEPS = {
    "structured_context": [1],
    "critical_point_interpretation": [1, 2],
    "uiti_vano_behavior_explanation": [1, 2, 3],
    "documentary_analysis": [1, 2, 3, 4, 5],
    "predictive_interpretation": [1, 2, 3, 4, 5, 6],
    "feature_mask_interpretation": [1, 2, 3, 4, 5, 6],
    "three_way_causal_synthesis": [1, 2, 3, 4, 5, 6, 7],
    "intervention_selection": [1, 2, 3, 4, 5, 6, 7, 8],
    "what_if_simulation": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "evidence_report": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
}


def build_workflow_trace(
    *,
    analysis_stage: str | None,
    evidence_packages: dict[str, bool] | None = None,
) -> dict[str, Any]:
    stage = analysis_stage or "guided_answer"
    return {
        "workflow_id": "criticidad_full_flow_v1",
        "analysis_stage": stage,
        "included_steps": STAGE_INCLUDED_STEPS.get(stage, []),
        "excluded_steps": [],
        "evidence_packages": {
            "structured": False,
            "documentary": False,
            "model": False,
            "simulation": False,
            "report": False,
            **(evidence_packages or {}),
        },
        "guardrails": {
            "no_definitive_causality": True,
            "cite_documentary_claims": True,
            "model_signals_not_causal_proof": True,
        },
    }
