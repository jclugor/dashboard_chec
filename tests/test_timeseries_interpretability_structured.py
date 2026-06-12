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


def test_deterministic_narrative_has_stable_shape() -> None:
    narrative = build_deterministic_narrative(_payload())
    text = flatten_narrative_to_text(narrative)

    assert narrative.source == "deterministic"
    assert narrative.point_narratives
    assert narrative.evidence_matrix
    assert "Se detectaron" in text


def test_context_builder_and_retrieval_query_include_grounded_facts() -> None:
    payload = _payload()
    context = build_timeseries_context_package_v2(payload)
    query = build_timeseries_retrieval_query(context)

    assert context["context_kind"] == "timeseries_criticality"
    assert context["critical_points"] == payload["critical_points"]
    assert "UITI" in query
    assert "UITI_VANO" in query
    assert "confiabilidad" in query


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
    point = payload["critical_points"][0]
    raw_narrative = {
        "source": "llm",
        "headline": "Resumen validado",
        "executive_summary": ["Se explica solo el punto calculado."],
        "point_narratives": [
            {
                "fecha_dia": point["fecha_dia"],
                "rank": point["rank"],
                "headline": "Punto calculado",
                "confidence": point["confidence"],
                "why_marked": ["UITI alto segun el detector."],
                "observed_values": ["UITI=6.0"],
                "likely_drivers": ["Revision operativa soportada por la evidencia estructurada."],
                "domain_support": ["UITI conecta eventos con impacto regulatorio en el periodo."],
                "documentary_support": [],
                "missing_evidence": point["data_quality_flags"],
                "recommended_checks": ["Validar registros operativos."],
                "citations_used": [],
            }
        ],
        "evidence_matrix": [
            {
                "fecha_dia": point["fecha_dia"],
                "signal": "Contexto de dominio",
                "structured_evidence": "Punto critico calculado por el sistema.",
                "domain_evidence": "Descripcion UITI y relacion Eventos -> Indicadores.",
                "documentary_evidence": None,
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
    assert run.narrative.source == "llm"
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
    assert run.narrative.point_narratives
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
        "executive_summary": "Se explica el punto calculado.",
        "point_narratives": {
            "fecha_dia": point["fecha_dia"],
            "rank": point["rank"],
            "headline": "Punto calculado",
            "confidence": point["confidence"],
            "why_marked": "UITI alto segun el detector.",
            "observed_values": "UITI=6.0",
            "likely_drivers": "La evidencia estructurada muestra concentracion del impacto UITI.",
            "domain_support": "UITI describe impacto regulatorio y se relaciona con eventos.",
            "documentary_support": "",
            "missing_evidence": "sin_bitacoras_modelo_simulacion",
            "recommended_checks": "Validar registros operativos.",
            "citations_used": "",
        },
        "evidence_matrix": {
            "fecha_dia": point["fecha_dia"],
            "signal": "Indicador",
            "structured_evidence": "Punto critico calculado por el sistema.",
            "domain_evidence": "Variable UITI y modo de indicadores.",
            "documentary_evidence": "",
            "confidence": "medium",
            "citations_used": "",
        },
        "data_gaps": "sin_bitacoras_modelo_simulacion",
        "recommended_actions": "Validar registros operativos.",
        "limitations": "No causalidad definitiva.",
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
    assert run.narrative.executive_summary == ["Se explica el punto calculado."]
    assert run.narrative.recommended_actions == ["Validar registros operativos."]
    assert run.trace.validation["valid"] is True
    assert run.trace.validation["repair_applied"] == "schema_shape_coercion"


def test_orchestrator_sanitizes_uncited_documentary_claims(tmp_path: Path, monkeypatch) -> None:
    settings = replace(_settings(tmp_path), chatbot_enabled=True)
    payload = _payload()
    point = payload["critical_points"][0]
    raw_narrative = {
        "source": "llm",
        "headline": "Resumen con soporte insuficiente",
        "executive_summary": ["Se explica el punto calculado."],
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
        "executive_summary": ["Se explica el punto calculado."],
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
    point = payload["critical_points"][0]
    raw_narrative = {
        "source": "llm",
        "headline": "Resumen semantico por circuito",
        "executive_summary": ["Se explica el punto calculado usando evidencia estructurada y dominio."],
        "point_narratives": [
            {
                "fecha_dia": point["fecha_dia"],
                "rank": point["rank"],
                "headline": "Punto calculado",
                "confidence": point["confidence"],
                "why_marked": ["UITI alto segun el detector."],
                "observed_values": ["UITI=6.0"],
                "likely_drivers": ["La evidencia estructurada muestra concentracion del impacto UITI."],
                "domain_support": ["UITI pertenece al modo de indicadores y resume impacto al usuario."],
                "documentary_support": [],
                "missing_evidence": ["sin_bitacoras_modelo_simulacion"],
                "recommended_checks": ["Validar registros operativos."],
                "citations_used": [],
            }
        ],
        "evidence_matrix": [
            {
                "fecha_dia": point["fecha_dia"],
                "signal": "Indicador",
                "structured_evidence": "Punto critico calculado por el sistema.",
                "domain_evidence": "Descripcion de UITI en ContextoProyectoSimuladorCHEC.",
                "documentary_evidence": None,
                "confidence": "medium",
                "citations_used": [],
            }
        ],
        "data_gaps": ["sin_bitacoras_modelo_simulacion"],
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
    assert run.status.severity == "ok"
    assert "no_retrieved_documents" not in run.status.data_quality_flags
    assert run.narrative.source == "llm"
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
