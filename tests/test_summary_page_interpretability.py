from __future__ import annotations

import plotly.graph_objects as go

from chec_dashboard.pages.summary_page import (
    _apply_interpretability_markers,
    _interpretability_panel_from_payload,
    _selected_date_from_click,
)


def _component_text(component) -> str:
    parts: list[str] = []

    def walk(item) -> None:
        if item is None:
            return
        if isinstance(item, str):
            parts.append(item)
            return
        children = getattr(item, "children", None)
        if isinstance(children, list):
            for child in children:
                walk(child)
        else:
            walk(children)

    walk(component)
    return "\n".join(parts)


def _payload() -> dict:
    return {
        "status_text": "ok",
        "metric_key": "UITI",
        "critical_points": [
            {
                "fecha_dia": "2024-01-03",
                "rank": 1,
                "criticality_score": 1.2,
                "criticality_types": ["uiti_high_outlier"],
                "metrics": {"UITI": 9.5, "UITI_VANO": 0.05},
                "daily_aggregates": {"event_count": 3, "duration_raw_total": 4.0},
                "confidence": "low",
                "data_quality_flags": ["missing_event_attribution"],
            }
        ],
        "critical_periods": [
            {
                "start_date": "2024-01-02",
                "end_date": "2024-01-04",
                "metric": "UITI",
                "period_type": "sustained_uiti_elevated_period",
                "score": 0.8,
                "days": 3,
                "summary": "UITI elevado.",
            }
        ],
        "narrative": {
            "source": "deterministic",
            "headline": "Se detecto un punto critico.",
            "section_title": "Hallazgos del periodo",
            "executive_summary": ["Resumen"],
            "key_findings": [
                {
                    "title": "Evolucion del periodo",
                    "text": "El indicador se concentra en el evento seleccionado dentro del periodo analizado.",
                    "referenced_events": [
                        {
                            "date": "2024-01-03",
                            "indicator_value": 9.5,
                            "selection_reason": "UITI alto",
                        }
                    ],
                    "variable_groups_used": ["Evento/Impacto"],
                }
            ],
            "period_synthesis": "Sintesis descriptiva del periodo.",
            "point_narratives": [
                {
                    "fecha_dia": "2024-01-03",
                    "rank": 1,
                    "headline": "Punto #1",
                    "confidence": "low",
                    "why_marked": ["UITI alto"],
                    "likely_drivers": ["Sin atribucion"],
                    "domain_support": ["UITI resume impacto al usuario."],
                    "missing_evidence": ["missing_event_attribution"],
                    "recommended_checks": ["Validar evento"],
                }
            ],
            "evidence_matrix": [
                {
                    "fecha_dia": "2024-01-03",
                    "signal": "Indicador",
                    "structured_evidence": "UITI=9.5",
                    "domain_evidence": "Variable UITI del modo de indicadores.",
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
    text = _component_text(panel)

    assert "summary-interpretability-panel-v2" in panel.className
    assert len(panel.children) == 2
    assert "Hallazgos del periodo" in text
    assert "Evolucion del periodo" in text
    assert "Por que se marco" not in text


def test_circuit_period_semantic_context_renders_without_event_focus() -> None:
    panel = _interpretability_panel_from_payload(
        {
            "status_text": "Sin puntos criticos detectados.",
            "critical_points": [],
            "critical_periods": [],
            "insight_text": "Analisis de circuito y periodo.",
            "analysis_focus": "circuit_period",
            "selected_event": None,
            "agent_workflow": [
                {
                    "label": "Paso 1",
                    "status": "completed",
                    "summary": "Circuito y periodo seleccionados.",
                }
            ],
            "variable_context": {
                "matched_modes": [
                    {
                        "mode_id": "C",
                        "label": "Indicadores",
                        "matched_variables": ["UITI"],
                    }
                ],
                "matched_variables": [
                    {
                        "name": "UITI",
                        "mode_label": "Indicadores",
                        "description": "Indice de tiempo de interrupcion por usuario.",
                    }
                ],
            },
            "variable_interactions": {
                "matched_rules": [
                    {
                        "relation_type": "Calculo Regulatorio",
                        "weight": 1.0,
                        "origin_group": "Eventos",
                        "destination_group": "Indicadores",
                    }
                ]
            },
        }
    )

    text = _component_text(panel)
    assert "Evento seleccionado" not in text
    assert "Hallazgos del periodo" in text
    assert "Flujo agentico" not in text
    assert "Interacciones de variables" not in text


def test_chart_markers_include_customdata_and_period_shape() -> None:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=["2024-01-03"], y=[9.5], mode="lines", name="UITI"))
    updated = _apply_interpretability_markers(fig, _payload(), "UITI")

    marker_traces = [trace for trace in updated.data if "Puntos criticos" in str(trace.name)]
    assert marker_traces
    assert marker_traces[0].customdata[0] == "2024-01-03"
    assert updated.layout.shapes


def test_selected_date_from_click_uses_customdata() -> None:
    assert (
        _selected_date_from_click({"points": [{"customdata": "2024-01-03", "x": "2024-01-01"}]})
        == "2024-01-03"
    )
