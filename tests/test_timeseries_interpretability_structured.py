from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.services.time_series_interpretability_agent import (
    attach_interpretability_narrative,
)
from chec_dashboard.services.time_series_interpretability_service import (
    build_summary_interpretability_payload,
)
from chec_dashboard.services.timeseries_interpretability.context_builder import (
    build_timeseries_context_package_v2,
)
from chec_dashboard.services.timeseries_interpretability.context_tool import (
    get_timeseries_interpretability_context_tool,
)
from chec_dashboard.services.timeseries_interpretability.contracts import (
    PointNarrative,
    TimeseriesInterpretabilityNarrative,
)
from chec_dashboard.services.timeseries_interpretability.deterministic_narrative import (
    build_deterministic_narrative,
    flatten_narrative_to_text,
)
from chec_dashboard.services.timeseries_interpretability.orchestrator import (
    TimeseriesInterpretabilityOrchestrator,
)
from chec_dashboard.services.timeseries_interpretability.prompts import (
    render_timeseries_prompt,
)
from chec_dashboard.services.timeseries_interpretability.retrieval_query import (
    build_timeseries_retrieval_query,
)
from chec_dashboard.services.timeseries_interpretability.validators import (
    validate_narrative,
)
from chec_dashboard.services.llm_service import STRUCTURED_JSON_SUFFIX


def _settings(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    return replace(
        base_settings,
        cache_enabled=False,
        chatbot_enabled=False,
        chatbot_corpus_dir=corpus_dir,
    )


def _payload() -> dict:
    return build_summary_interpretability_payload(
        daily_frame=pd.DataFrame(
            {
                "fecha_dia": pd.date_range("2024-01-01", periods=10, freq="D"),
                "UITI": [0.2, 0.2, 0.2, 6.0, 0.2, 0.2, 0.2, 1.0, 0.2, 0.2],
                "UITI_VANO": [0.1, 0.1, 0.1, 2.5, 0.1, 0.1, 0.1, 0.2, 0.1, 0.1],
                "event_count": [0, 0, 0, 4, 0, 0, 0, 1, 0, 0],
            }
        ),
        start_date="2024-01-01",
        end_date="2024-01-10",
        circuit_label="CIR-1",
        metric_key="UITI",
        generated_at="2026-06-04T00:00:00Z",
    )


def _raw_period_narrative(payload: dict, *, source: str = "llm", headline: str = "Resumen validado") -> dict:
    points = payload["critical_points"]
    referenced_events = [
        {
            "date": point["fecha_dia"],
            "indicator_value": point["metrics"]["UITI"],
            "selection_reason": point["selection_reason"],
        }
        for point in points
    ]
    return {
        "source": source,
        "headline": headline,
        "section_title": "Hallazgos del periodo",
        "executive_summary": ["Se explica el comportamiento del periodo con evidencia estructurada."],
        "key_findings": [
            {
                "title": "Evolucion del periodo",
                "text": "El indicador se concentra en los eventos seleccionados y se interpreta a nivel de periodo.",
                "referenced_events": referenced_events,
                "variable_groups_used": ["Evento/Impacto"],
            }
        ],
        "period_synthesis": "Sintesis descriptiva del periodo analizado.",
        "point_narratives": [],
        "period_narratives": [],
        "evidence_matrix": [],
        "data_gaps": [],
        "recommended_actions": [],
        "limitations": [],
        "citations_used": [],
    }


def test_deterministic_narrative_has_stable_shape() -> None:
    narrative = build_deterministic_narrative(_payload())
    text = flatten_narrative_to_text(narrative)

    assert narrative.source == "deterministic"
    assert narrative.section_title == "Hallazgos del periodo"
    assert narrative.key_findings
    assert narrative.key_findings[0].referenced_events
    assert narrative.evidence_matrix
    assert "Hallazgos del periodo" in text


def test_context_builder_and_retrieval_query_include_grounded_facts() -> None:
    payload = _payload()
    context = build_timeseries_context_package_v2(payload)
    query = build_timeseries_retrieval_query(context)

    assert context["context_kind"] == "timeseries_criticality"
    assert context["critical_points"] == payload["critical_points"]
    assert "UITI" in query
    assert "UITI_VANO" in query
    assert "confiabilidad" in query


def test_context_keeps_all_selected_events_for_period_synthesis() -> None:
    payload = _payload()
    context = build_timeseries_context_package_v2(payload)

    assert len(context["critical_points"]) == len(payload["critical_points"])
    assert [point["fecha_dia"] for point in context["critical_points"]] == [
        point["fecha_dia"] for point in payload["critical_points"]
    ]
    assert all(point["selection_reason"] for point in context["critical_points"])


def test_prompt_and_structured_suffix_do_not_cap_period_events(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    context = get_timeseries_interpretability_context_tool(settings, context_package=_payload())
    prompt, _ = render_timeseries_prompt(
        context_package=context,
        docs_text="",
        question_text="Analiza el periodo.",
    )
    prompt_and_suffix = f"{prompt}\n{STRUCTURED_JSON_SUFFIX}".lower()

    forbidden_caps = ["maximo 2", "maximo 3", "top 2", "top 3", "narra los 2"]
    assert not any(cap in prompt_and_suffix for cap in forbidden_caps)
    assert "hallazgos del periodo" in prompt_and_suffix


def test_deterministic_flattened_text_excludes_out_of_scope_warnings() -> None:
    text = flatten_narrative_to_text(build_deterministic_narrative(_payload())).lower()

    forbidden = [
        "calidad de datos",
        "valores faltantes",
        "datos incompletos",
        "12 meses",
        "bitacora",
        "rag",
        "modelo predictivo",
        "simulacion",
        "reporte final",
    ]
    assert not any(item in text for item in forbidden)


def test_validator_rejects_unseen_date_and_invalid_citation() -> None:
    narrative = TimeseriesInterpretabilityNarrative(
        source="llm",
        headline="Resumen",
        point_narratives=[
            PointNarrative(
                fecha_dia="2099-01-01",
                rank=1,
                headline="Fecha inventada",
                citations_used=[2],
            )
        ],
    )

    result = validate_narrative(
        narrative=narrative,
        deterministic_payload=_payload(),
        citations=[{"id": "doc-1"}],
    )

    assert not result.valid
    assert any("point_narrative_date_not_grounded" in error for error in result.errors)
    assert "invalid_citation:2" in result.errors


def test_orchestrator_and_public_bridge_fallback_when_disabled(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    payload = _payload()

    run = TimeseriesInterpretabilityOrchestrator().run(
        settings,
        deterministic_payload=payload,
        include_agent_text=True,
    )
    attached = attach_interpretability_narrative(settings, payload, include_agent_text=True)

    assert run.status.fallback_used
    assert run.narrative.source == "deterministic"
    assert attached["narrative"]["source"] == "deterministic"
    assert attached["deterministic_narrative"]["source"] == "deterministic"
    assert attached["interpretability_trace"]["fallback_used"] is True
    assert attached["insight_text"]


def test_orchestrator_accepts_valid_structured_llm(tmp_path: Path, monkeypatch) -> None:
    settings = replace(_settings(tmp_path), chatbot_enabled=True)
    payload = _payload()
    raw_narrative = _raw_period_narrative(payload)

    monkeypatch.setattr(
        "chec_dashboard.services.timeseries_interpretability.orchestrator.generate_llm_structured_answer",
        lambda *args, **kwargs: raw_narrative,
    )

    run = TimeseriesInterpretabilityOrchestrator().run(
        settings,
        deterministic_payload=payload,
        include_agent_text=True,
    )

    assert not run.status.fallback_used
    assert run.narrative.source == "llm"
    assert run.narrative.section_title == "Hallazgos del periodo"
    assert run.narrative.key_findings
    assert run.trace.mode == "llm_structured_semantic"
    assert run.trace.citation_count == 0
    assert run.citations == []
    assert run.trace.validation["valid"] is True


def test_orchestrator_repairs_tool_payload_shape_from_llm(tmp_path: Path, monkeypatch) -> None:
    settings = replace(_settings(tmp_path), chatbot_enabled=True)
    payload = _payload()
    raw_narrative = {
        "tipo_analisis": "reliability",
        "nombre_analisis": "Interpretabilidad de impacto UITI",
        "kind": "timeseries_criticality",
        "analysis": [
            "El punto principal presenta UITI alto con eventos concentrados.",
            "La interpretacion se limita a evidencia estructurada.",
            "No se afirma causalidad definitiva.",
            "La causa dominante debe validarse con registros operativos.",
        ],
        "observations": [
            "La serie muestra un pico aislado.",
        ],
        "operational_hypotheses": [
            "Contrastar con bitacoras de interrupciones.",
        ],
        "missing_evidence": [
            "Falta trazabilidad documental especifica para el punto.",
        ],
        "data_quality_flags": [
            "missing_dates",
        ],
    }

    monkeypatch.setattr(
        "chec_dashboard.services.timeseries_interpretability.orchestrator.generate_llm_structured_answer",
        lambda *args, **kwargs: raw_narrative,
    )

    run = TimeseriesInterpretabilityOrchestrator().run(
        settings,
        deterministic_payload=payload,
        include_agent_text=True,
    )

    assert not run.status.fallback_used
    assert run.narrative.source == "validated_repair"
    assert run.narrative.executive_summary[0].startswith("El punto principal")
    assert run.narrative.key_findings
    assert run.trace.mode == "llm_structured_semantic"
    assert run.trace.validation["valid"] is True
    assert run.trace.validation["repair_applied"] == "tool_payload_shape"


def test_orchestrator_coerces_scalar_schema_lists_from_llm(tmp_path: Path, monkeypatch) -> None:
    settings = replace(_settings(tmp_path), chatbot_enabled=True)
    payload = _payload()
    point = payload["critical_points"][0]
    raw_narrative = {
        "source": "llm",
        "headline": "Resumen compacto",
        "section_title": "Hallazgos del periodo",
        "executive_summary": "Se explica el periodo analizado.",
        "key_findings": {
            "title": "Hallazgo consolidado",
            "text": "El evento seleccionado se interpreta dentro de la evolucion del periodo.",
            "referenced_events": [
                {
                    "date": point["fecha_dia"],
                    "indicator_value": point["metrics"]["UITI"],
                    "selection_reason": point["selection_reason"],
                }
            ],
            "variable_groups_used": ["Evento/Impacto"],
        },
        "period_synthesis": "Sintesis del periodo.",
        "citations_used": "",
    }

    monkeypatch.setattr(
        "chec_dashboard.services.timeseries_interpretability.orchestrator.generate_llm_structured_answer",
        lambda *args, **kwargs: raw_narrative,
    )

    run = TimeseriesInterpretabilityOrchestrator().run(
        settings,
        deterministic_payload=payload,
        include_agent_text=True,
    )

    assert not run.status.fallback_used
    assert run.narrative.source == "llm"
    assert run.narrative.executive_summary == ["Se explica el periodo analizado."]
    assert run.narrative.key_findings[0].title == "Hallazgo consolidado"
    assert run.trace.validation["valid"] is True
    assert run.trace.validation["repair_applied"] == "schema_shape_coercion"


def test_orchestrator_sanitizes_uncited_documentary_claims(tmp_path: Path, monkeypatch) -> None:
    settings = replace(_settings(tmp_path), chatbot_enabled=True)
    payload = _payload()
    point = payload["critical_points"][0]
    raw_narrative = {
        "source": "llm",
        "headline": "Resumen con soporte insuficiente",
        "section_title": "Hallazgos del periodo",
        "executive_summary": ["Se explica el punto calculado."],
        "key_findings": _raw_period_narrative(payload)["key_findings"],
        "point_narratives": [
            {
                "fecha_dia": point["fecha_dia"],
                "rank": point["rank"],
                "headline": "Punto calculado",
                "confidence": point["confidence"],
                "why_marked": ["UITI alto segun el detector."],
                "observed_values": ["UITI=6.0"],
                "likely_drivers": ["La evidencia estructurada muestra concentracion del impacto UITI."],
                "documentary_support": ["Un documento regulatorio respalda esta lectura."],
                "missing_evidence": [],
                "recommended_checks": ["Validar registros operativos."],
                "citations_used": [],
            }
        ],
        "evidence_matrix": [
            {
                "fecha_dia": point["fecha_dia"],
                "signal": "Documento",
                "structured_evidence": "Punto critico calculado por el sistema.",
                "documentary_evidence": "Documento regulatorio sin cita.",
                "confidence": "medium",
                "citations_used": [],
            }
        ],
        "recommended_actions": ["Validar registros operativos."],
        "limitations": ["No causalidad definitiva."],
        "citations_used": [],
    }

    monkeypatch.setattr(
        "chec_dashboard.services.timeseries_interpretability.orchestrator.generate_llm_structured_answer",
        lambda *args, **kwargs: raw_narrative,
    )

    run = TimeseriesInterpretabilityOrchestrator().run(
        settings,
        deterministic_payload=payload,
        include_agent_text=True,
    )

    assert not run.status.fallback_used
    assert run.narrative.point_narratives[0].documentary_support == [
        "Sin soporte documental suficiente para este punto."
    ]
    assert run.narrative.evidence_matrix[0].documentary_evidence == "Sin soporte documental suficiente."
    assert run.trace.validation["valid"] is True
    assert run.trace.validation["repair_applied"] == "uncited_documentary_claim_sanitized"


def test_orchestrator_sanitizes_out_of_range_citations(tmp_path: Path, monkeypatch) -> None:
    settings = replace(_settings(tmp_path), chatbot_enabled=True)
    payload = _payload()
    point = payload["critical_points"][0]
    raw_narrative = {
        "source": "llm",
        "headline": "Resumen con cita fuera de rango",
        "section_title": "Hallazgos del periodo",
        "executive_summary": ["Se explica el punto calculado."],
        "key_findings": _raw_period_narrative(payload)["key_findings"],
        "point_narratives": [
            {
                "fecha_dia": point["fecha_dia"],
                "rank": point["rank"],
                "headline": "Punto calculado",
                "confidence": point["confidence"],
                "why_marked": ["UITI alto segun el detector."],
                "observed_values": ["UITI=6.0"],
                "likely_drivers": ["La evidencia estructurada muestra concentracion del impacto UITI."],
                "documentary_support": ["Documento regulatorio [99]."],
                "missing_evidence": [],
                "recommended_checks": ["Validar registros operativos."],
                "citations_used": [99],
            }
        ],
        "evidence_matrix": [
            {
                "fecha_dia": point["fecha_dia"],
                "signal": "Documento",
                "structured_evidence": "Punto critico calculado por el sistema.",
                "documentary_evidence": "Documento regulatorio [99].",
                "confidence": "medium",
                "citations_used": [99],
            }
        ],
        "recommended_actions": ["Validar registros operativos."],
        "limitations": ["No causalidad definitiva."],
        "citations_used": [99],
    }

    monkeypatch.setattr(
        "chec_dashboard.services.timeseries_interpretability.orchestrator.generate_llm_structured_answer",
        lambda *args, **kwargs: raw_narrative,
    )

    run = TimeseriesInterpretabilityOrchestrator().run(
        settings,
        deterministic_payload=payload,
        include_agent_text=True,
    )

    assert not run.status.fallback_used
    assert run.narrative.citations_used == []
    assert run.narrative.point_narratives[0].citations_used == []
    assert run.narrative.point_narratives[0].documentary_support == [
        "Sin soporte documental suficiente para este punto."
    ]
    assert run.narrative.evidence_matrix[0].citations_used == []
    assert run.narrative.evidence_matrix[0].documentary_evidence == "Sin soporte documental suficiente."
    assert run.trace.validation["valid"] is True
    assert run.trace.validation["repair_applied"] == "uncited_documentary_claim_sanitized"


def test_orchestrator_uses_llm_without_document_retrieval(tmp_path: Path, monkeypatch) -> None:
    settings = replace(_settings(tmp_path), chatbot_enabled=True)
    payload = _payload()
    raw_narrative = _raw_period_narrative(payload, headline="Resumen semantico por circuito")

    monkeypatch.setattr(
        "chec_dashboard.services.timeseries_interpretability.orchestrator.generate_llm_structured_answer",
        lambda *args, **kwargs: raw_narrative,
    )

    run = TimeseriesInterpretabilityOrchestrator().run(
        settings,
        deterministic_payload=payload,
        include_agent_text=True,
    )

    assert not run.status.fallback_used
    assert run.status.severity == "ok"
    assert "no_retrieved_documents" not in run.status.data_quality_flags
    assert run.narrative.source == "llm"
    assert run.narrative.key_findings
    assert run.trace.mode == "llm_structured_semantic"
    assert run.trace.citation_count == 0
    assert run.trace.validation["valid"] is True


def test_prompt_renderer_and_context_tool(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    payload = _payload()
    context = get_timeseries_interpretability_context_tool(
        settings,
        context_package=payload,
        selected_date=payload["critical_points"][0]["fecha_dia"],
    )
    prompt, metadata = render_timeseries_prompt(
        context_package=context,
        docs_text="Sin documentos recuperados.",
        question_text="Explica el pico.",
    )

    assert context["tool_name"] == "get_timeseries_interpretability_context"
    assert len(context["critical_points"]) == 1
    assert "{{context_json}}" not in prompt
    assert "Documentos recuperados" not in prompt
    assert metadata["prompt_name"] == "time_series_interpretability"
