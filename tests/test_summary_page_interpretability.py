from __future__ import annotations

import plotly.graph_objects as go

from chec_dashboard.pages.summary_page import (
    _apply_interpretability_markers,
    _interpretability_panel_from_payload,
    _selected_date_from_click,
)


def _payload() -> dict:
    return {
        "status_text": "ok",
        "metric_mode": "BOTH",
        "critical_points": [
            {
                "fecha_dia": "2024-01-03",
                "rank": 1,
                "criticality_score": 1.2,
                "criticality_types": ["saidi_high_outlier"],
                "metrics": {"SAIDI": 9.5, "SAIFI": 0.05},
                "daily_aggregates": {"event_count": 3, "duration_total_h": 4.0},
                "confidence": "low",
                "data_quality_flags": ["missing_event_attribution"],
            }
        ],
        "critical_periods": [
            {
                "start_date": "2024-01-02",
                "end_date": "2024-01-04",
                "metric": "SAIDI",
                "period_type": "sustained_saidi_elevated_period",
                "score": 0.8,
                "days": 3,
                "summary": "SAIDI elevado.",
            }
        ],
        "narrative": {
            "source": "deterministic",
            "headline": "Se detecto un punto critico.",
            "executive_summary": ["Resumen"],
            "point_narratives": [
                {
                    "fecha_dia": "2024-01-03",
                    "rank": 1,
                    "headline": "Punto #1",
                    "confidence": "low",
                    "why_marked": ["SAIDI alto"],
                    "likely_drivers": ["Sin atribucion"],
                    "missing_evidence": ["missing_event_attribution"],
                    "recommended_checks": ["Validar evento"],
                }
            ],
            "evidence_matrix": [
                {
                    "fecha_dia": "2024-01-03",
                    "signal": "Indicador",
                    "structured_evidence": "SAIDI=9.5",
                    "confidence": "low",
                }
            ],
            "data_gaps": ["missing_event_attribution"],
            "recommended_actions": ["Validar datos"],
            "limitations": ["Sin causalidad definitiva"],
        },
        "status": {"severity": "warning", "fallback_used": True},
        "interpretability_trace": {"fallback_used": True},
        "corpus_citations": [],
    }


def test_structured_interpretability_panel_renders() -> None:
    panel = _interpretability_panel_from_payload(_payload())

    assert "summary-interpretability-panel-v2" in panel.className
    assert len(panel.children) >= 5


def test_chart_markers_include_customdata_and_period_shape() -> None:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=["2024-01-03"], y=[9.5], mode="lines", name="SAIDI"))
    updated = _apply_interpretability_markers(fig, _payload(), "BOTH")

    marker_traces = [trace for trace in updated.data if "Puntos criticos" in str(trace.name)]
    assert marker_traces
    assert marker_traces[0].customdata[0] == "2024-01-03"
    assert updated.layout.shapes


def test_selected_date_from_click_uses_customdata() -> None:
    assert (
        _selected_date_from_click({"points": [{"customdata": "2024-01-03", "x": "2024-01-01"}]})
        == "2024-01-03"
    )
