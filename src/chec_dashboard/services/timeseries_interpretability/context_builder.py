from __future__ import annotations

from typing import Any

from chec_dashboard.services.timeseries_interpretability.deterministic_narrative import (
    build_deterministic_narrative,
    flatten_narrative_to_text,
)


def _append_label(scores: dict[str, float], label: Any, weight: Any = 1.0) -> None:
    text = str(label or "").strip()
    if not text:
        return
    try:
        numeric_weight = float(weight or 0.0)
    except (TypeError, ValueError):
        numeric_weight = 1.0
    scores[text] = scores.get(text, 0.0) + max(numeric_weight, 0.0)


def top_labels(points: list[dict[str, Any]], key: str, *, limit: int = 5) -> list[str]:
    scores: dict[str, float] = {}
    for point in points:
        for item in point.get(key) or []:
            if not isinstance(item, dict):
                continue
            metric_totals = item.get("metric_totals")
            if isinstance(metric_totals, dict):
                weight = float(metric_totals.get("UITI") or 0.0) + float(metric_totals.get("UITI_VANO") or 0.0)
            else:
                weight = float(item.get("uiti_total") or 0.0)
                weight += float(item.get("uiti_vano_total") or 0.0)
            if weight <= 0:
                weight = item.get("event_count", 1)
            _append_label(scores, item.get("label"), weight)
    return [
        label
        for label, _ in sorted(scores.items(), key=lambda item: (item[1], item[0]), reverse=True)[:limit]
    ]


def build_retrieval_hints(points: list[dict[str, Any]], periods: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "dominant_causes": top_labels(points, "top_causes", limit=5),
        "dominant_event_families": top_labels(points, "top_event_families", limit=5),
        "dominant_equipment": top_labels(points, "top_equipment", limit=5),
        "dominant_circuits": top_labels(points, "top_circuits", limit=5),
        "criticality_types": sorted(
            {
                str(item)
                for point in points
                for item in (point.get("criticality_types") or [])
                if str(item).strip()
            }
        ),
        "period_types": sorted(
            {
                str(period.get("period_type"))
                for period in periods
                if isinstance(period, dict) and str(period.get("period_type") or "").strip()
            }
        ),
    }


def build_timeseries_context_package_v2(payload: dict[str, Any]) -> dict[str, Any]:
    points = payload.get("critical_points") or []
    periods = payload.get("critical_periods") or []
    global_flags = sorted(
        {
            str(flag)
            for point in points
            for flag in (point.get("data_quality_flags") or [])
            if str(flag).strip()
        }
    )
    fallback_text = flatten_narrative_to_text(build_deterministic_narrative(payload))
    retrieval_hints = build_retrieval_hints(points, periods)

    return {
        "tipo_analisis": "reliability",
        "nombre_analisis": "Interpretabilidad de impacto UITI",
        "kind": "timeseries_criticality",
        "context_kind": "timeseries_criticality",
        "tool_name": "get_timeseries_interpretability_context",
        "source_function": "local.agent_tools.get_timeseries_interpretability_context",
        "source_view": "local.summary_interpretability_payload",
        "selected_context": {
            "circuito": payload.get("circuit_label"),
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
            "metric_key": payload.get("metric_key") or "UITI",
            "selected_date": payload.get("selected_date"),
            "analysis_focus": payload.get("analysis_focus") or "circuit_period",
        },
        "summary": {
            "text": fallback_text,
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
            "circuit_label": payload.get("circuit_label"),
            "metric_key": payload.get("metric_key") or "UITI",
        },
        "window_summary": {
            "critical_point_count": len(points),
            "critical_period_count": len(periods),
            "global_data_quality_flags": global_flags,
            "status_text": payload.get("status_text"),
        },
        "critical_points": points,
        "critical_periods": periods,
        "analysis_focus": payload.get("analysis_focus") or "circuit_period",
        "circuit_history_12m": payload.get("circuit_history_12m") or {},
        "available_history": payload.get("circuit_history_12m") or {},
        "agent_workflow": payload.get("agent_workflow") or [],
        "variable_context": payload.get("variable_context") or {},
        "variable_interactions": payload.get("variable_interactions") or {},
        "records": points,
        "metrics": {
            "critical_point_count": len(points),
            "critical_period_count": len(periods),
            "global_data_quality_flags": global_flags,
        },
        "retrieval_hints": retrieval_hints,
        "response_guardrails": {
            "do_not_detect_new_anomalies": True,
            "do_not_change_criticality_types": True,
            "do_not_claim_causality": True,
            "cite_documentary_claims": False,
            "report_missing_evidence": False,
            "treat_event_gaps_as_structural": True,
            "do_not_warn_about_window_length": True,
        },
        "traceability": {
            "claim_scope": "summary_time_series_interpretability",
            "read_only": True,
            "source_tables": [
                "gold_impact_daily",
                "gold_timeseries_daily_attribution",
                "gold_timeseries_event_details",
                "gold_timeseries_environment_daily",
            ],
        },
    }
