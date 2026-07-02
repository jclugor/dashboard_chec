from __future__ import annotations

import time
from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.agent_context_service import (
    build_chatbot_context_package,
    resolve_question,
    sanitize_briefing_type,
)
from chec_dashboard.services.agent_contract_service import contract_metadata
from chec_dashboard.services.agent_routing_service import execute_agent_route
from chec_dashboard.services.agent_trace_service import create_trace_id
from chec_dashboard.services.agent_workflow_service import build_workflow_trace
from chec_dashboard.services.answer_quality_service import build_answer_quality_metadata
from chec_dashboard.services.capability_registry import (
    CAPABILITY_REGISTRY,
    capability_for_stage,
    capability_metadata,
    unavailable_payload,
    utc_now,
)
from chec_dashboard.services.citation_service import citation_payload
from chec_dashboard.services.citation_validation_service import validate_output_citations
from chec_dashboard.services.conversation_service import (
    create_conversation,
    get_conversation_detail,
    recent_conversation_messages,
    record_conversation_turn,
    record_feedback,
    resolve_conversation_turn,
)
from chec_dashboard.services.llm_service import (
    generate_llm_answer,
    llm_configuration_message,
    llm_configured,
    llm_endpoint_configured,
    llm_endpoint_name,
    llm_provider,
    select_llm_tier,
)
from chec_dashboard.services.llm_output_validation_service import fallback_text, validate_llm_output
from chec_dashboard.services.evidence_report_service import build_evidence_report_context
from chec_dashboard.services.feature_mask_service import build_feature_mask_package
from chec_dashboard.services.intervention_candidate_service import build_intervention_candidate_context
from chec_dashboard.services.model_evidence_service import build_model_evidence_package
from chec_dashboard.services.observability_service import (
    context_hash,
    observability_status,
    record_feedback_observability,
    record_turn_observability,
    resolve_prompt_metadata,
)
from chec_dashboard.services.prompt_service import (
    ANSWER_PROMPT_TEMPLATE,
    STAGE_CONTRACT_NAMES,
    build_prompt,
    build_stage_prompt,
    stage_prompt_metadata,
)
from chec_dashboard.services.retrieval_service import (
    Corpus,
    corpus_runtime_diagnostics,
    load_chatbot_corpus,
    retriever_runtime_diagnostics,
)
from chec_dashboard.services.skill_service import SkillResolution, get_skill_status, resolve_skill
from chec_dashboard.services.three_way_synthesis_service import build_three_way_context
from chec_dashboard.services.what_if_service import run_what_if_simulation


_FALLBACK_STAGE_STATUSES = {"unavailable", "not_configured", "not_provided", "error"}


def get_chatbot_status(settings: Settings) -> dict[str, Any]:
    corpus_error = None
    retriever_diagnostics = retriever_runtime_diagnostics(settings)
    if retriever_diagnostics["retriever_backend"] == "databricks_ai_search":
        corpus = Corpus(chunks=[], documents=[], variables=[])
        corpus_available = bool(retriever_diagnostics["retriever_configured"])
    else:
        try:
            corpus = load_chatbot_corpus(settings)
        except Exception as exc:
            corpus = Corpus(chunks=[], documents=[], variables=[])
            corpus_error = str(exc)
        corpus_available = bool(corpus.chunks)
    diagnostics = corpus_runtime_diagnostics(settings)
    enabled = settings.chatbot_enabled
    provider = llm_provider(settings)
    configured = llm_configured(settings)
    endpoint_configured = llm_endpoint_configured(settings)
    gemini_configured = bool(settings.gemini_api_key)
    ready = enabled and configured and corpus_available

    if not enabled:
        message = "El asistente técnico está deshabilitado en esta instalación."
    elif not retriever_diagnostics["retriever_supported"]:
        message = f"Recuperador técnico no soportado: {retriever_diagnostics['retriever_backend']}."
    elif not retriever_diagnostics["retriever_configured"]:
        message = "El recuperador Databricks AI Search no está configurado. Define AI_SEARCH_INDEX_NAME."
    elif not corpus_available:
        message = "El corpus técnico no está disponible. Carga los documentos antes de analizar."
    elif not configured:
        message = llm_configuration_message(settings)
    else:
        message = "Asistente técnico listo para generar análisis."

    payload: dict[str, Any] = {
        "enabled": enabled,
        "llm_provider": provider,
        "llm_configured": configured,
        "llm_endpoint_configured": endpoint_configured,
        "model_endpoint_name": _model_endpoint_name(settings),
        "llm_max_tokens": settings.llm_max_tokens,
        "llm_temperature": settings.llm_temperature,
        "gemini_configured": gemini_configured,
        "corpus_available": corpus_available,
        "ready": ready,
        "documents_count": len(corpus.documents),
        "chunks_count": len(corpus.chunks),
        "message": message,
        **retriever_diagnostics,
        **diagnostics,
        "capabilities": {
            capability_id: capability_metadata(capability_id)
            for capability_id in CAPABILITY_REGISTRY
        },
    }
    if corpus_error:
        payload["corpus_load_error"] = corpus_error
    skill_status = get_skill_status(settings)
    payload.update(
        {
            "skills_available": skill_status["skills_available"],
            "skills_count": skill_status["skills_count"],
            "skill_errors_count": skill_status["skill_errors_count"],
        }
    )
    payload.update(observability_status(settings))
    return payload


def _response_metadata(
    *,
    settings: Settings,
    conversation_id: str | None,
    skill_resolution: SkillResolution,
    analysis_stage: str | None = None,
) -> dict[str, Any]:
    conversation_turn = resolve_conversation_turn(conversation_id)
    if analysis_stage and analysis_stage != "guided_answer":
        stage_metadata = stage_prompt_metadata(analysis_stage)
        prompt_name = stage_metadata["prompt_name"]
        prompt_alias = analysis_stage
        prompt_version = stage_metadata["prompt_version"]
        prompt_hash = stage_metadata["prompt_hash"]
        prompt_source = stage_metadata["prompt_source"]
        prompt_registry_error = None
    else:
        prompt_metadata = resolve_prompt_metadata(settings, ANSWER_PROMPT_TEMPLATE)
        prompt_name = prompt_metadata.prompt_name
        prompt_alias = prompt_metadata.prompt_alias
        prompt_version = prompt_metadata.prompt_version
        prompt_hash = prompt_metadata.prompt_hash
        prompt_source = prompt_metadata.prompt_source
        prompt_registry_error = prompt_metadata.prompt_registry_error
    capability = capability_for_stage(analysis_stage)
    contract = _contract_metadata_for_stage(analysis_stage)
    llm_tier = select_llm_tier(settings)
    return {
        "conversation_id": conversation_turn.conversation_id,
        "turn_id": conversation_turn.turn_id,
        "analysis_stage": analysis_stage,
        "skill_id": skill_resolution.skill_id,
        "skill_version": skill_resolution.skill_version,
        "skill_hash": skill_resolution.skill_hash,
        "trace_id": create_trace_id(),
        "llm_provider": llm_provider(settings),
        "llm_tier": llm_tier,
        "model_endpoint_name": _model_endpoint_name(settings, llm_tier=llm_tier),
        "prompt_name": prompt_name,
        "prompt_alias": prompt_alias,
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
        "prompt_source": prompt_source,
        "prompt_registry_error": prompt_registry_error,
        "capability_id": capability.capability_id if capability else None,
        "capability_status": capability.status if capability else None,
        "capability_tier": capability.tier if capability else None,
        "safe_fallback_used": False,
        "validation_status": None,
        "missing_requirements": [],
        "contract_name": contract.get("contract_name"),
        "contract_version": contract.get("contract_version"),
        "contract_hash": contract.get("contract_hash"),
        "evidence_policy_validation": {},
        "llm_output_validation": {},
        "model_evidence": {},
        "feature_mask_summary": {},
        "report_artifact": {},
        "stage_metadata": {},
        "mlflow_trace_id": None,
        "mlflow_run_id": None,
        "observability_status": "pending" if settings.chatbot_observability_enabled else "disabled",
        "observability_error": None,
        "_turn_started_at": time.perf_counter(),
    }


def _model_endpoint_name(settings: Settings, *, llm_tier: str | None = None) -> str | None:
    endpoint_name = llm_endpoint_name(settings, tier=llm_tier)
    if endpoint_name:
        return endpoint_name
    if settings.llm_provider == "gemini":
        return settings.gemini_model
    if settings.llm_provider == "mock":
        return "mock"
    return None


def _chunk_ids(chunks: list[dict[str, Any]]) -> list[str]:
    return [str(chunk.get("chunk_id")) for chunk in chunks if chunk.get("chunk_id")]


def _guided_user_message(question: str | None) -> str:
    return question or "Generar análisis guiado del contexto seleccionado."


def _persist_response(
    settings: Settings,
    *,
    metadata: dict[str, Any],
    user_message: str,
    answer: str,
    briefing_type: str,
    question_id: str | None,
    context_package: dict[str, Any],
    citations: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    status_text: str,
    ready: bool,
    agent_tool_calls: list[dict[str, Any]] | None = None,
    agent_skipped_tools: list[dict[str, Any]] | None = None,
    agent_route_summary: dict[str, Any] | None = None,
    mode: str = "guided",
) -> None:
    quality = build_answer_quality_metadata(answer, citations, briefing_type=briefing_type)
    latency_ms = max(int((time.perf_counter() - float(metadata.get("_turn_started_at") or time.perf_counter())) * 1000), 0)
    metadata["latency_ms"] = latency_ms
    observability_result = record_turn_observability(
        settings,
        {
            "trace_id": metadata.get("trace_id"),
            "conversation_id": metadata.get("conversation_id"),
            "turn_id": metadata.get("turn_id"),
            "mode": mode,
            "briefing_type": briefing_type,
            "analysis_stage": metadata.get("analysis_stage"),
            "question_id": question_id,
            "user_message": user_message,
            "answer": answer,
            "ready": ready,
            "status_text": status_text,
            "skill_id": metadata.get("skill_id"),
            "skill_version": metadata.get("skill_version"),
            "skill_hash": metadata.get("skill_hash"),
            "context_snapshot_hash": context_hash(context_package),
            "prompt_name": metadata.get("prompt_name"),
            "prompt_alias": metadata.get("prompt_alias"),
            "prompt_version": metadata.get("prompt_version"),
            "prompt_hash": metadata.get("prompt_hash"),
            "prompt_source": metadata.get("prompt_source"),
            "llm_provider": metadata.get("llm_provider"),
            "llm_tier": metadata.get("llm_tier"),
            "model_endpoint_name": metadata.get("model_endpoint_name"),
            "capability_id": metadata.get("capability_id"),
            "capability_status": metadata.get("capability_status"),
            "capability_tier": metadata.get("capability_tier"),
            "safe_fallback_used": bool(metadata.get("safe_fallback_used")),
            "validation_status": metadata.get("validation_status"),
            "missing_requirements": metadata.get("missing_requirements") or [],
            "contract_name": metadata.get("contract_name"),
            "contract_version": metadata.get("contract_version"),
            "contract_hash": metadata.get("contract_hash"),
            "retriever_backend": settings.retriever_backend,
            "ai_search_index_name": settings.ai_search_index_name,
            "latency_ms": latency_ms,
            "citations": citations,
            "citation_count": len(citations),
            "retrieved_chunk_ids": _chunk_ids(chunks),
            "agent_tool_calls": agent_tool_calls or [],
            "agent_skipped_tools": agent_skipped_tools or [],
            "agent_route_summary": agent_route_summary or _empty_agent_route_summary(),
            "structured_answer": quality["structured_answer"],
            "answer_validation": quality["answer_validation"],
            "citation_validation": quality["citation_validation"],
            "compliance_validation": quality["compliance_validation"],
            "validation": {
                "answer_validation": quality["answer_validation"],
                "citation_validation": quality["citation_validation"],
                "compliance_validation": quality["compliance_validation"],
                "evidence_policy_validation": metadata.get("evidence_policy_validation") or {},
                "llm_output_validation": metadata.get("llm_output_validation") or {},
            },
            "model_evidence": metadata.get("model_evidence") or {},
            "feature_mask_summary": metadata.get("feature_mask_summary") or {},
            "report_artifact": metadata.get("report_artifact") or {},
            "stage_metadata": metadata.get("stage_metadata") or {},
        },
    )
    metadata.update(observability_result)
    record_conversation_turn(
        settings,
        conversation_id=metadata["conversation_id"],
        turn_id=metadata["turn_id"],
        user_message=user_message,
        assistant_message=answer,
        briefing_type=briefing_type,
        analysis_stage=metadata.get("analysis_stage"),
        question_id=question_id,
        context_snapshot=context_package,
        skill_id=metadata.get("skill_id"),
        skill_version=metadata.get("skill_version"),
        skill_hash=metadata.get("skill_hash"),
        trace_id=metadata.get("trace_id"),
        llm_provider=metadata.get("llm_provider"),
        model_endpoint_name=metadata.get("model_endpoint_name"),
        citations=citations,
        retrieved_chunk_ids=_chunk_ids(chunks),
        status_text=status_text,
        ready=ready,
        agent_tool_calls=agent_tool_calls or [],
        agent_skipped_tools=agent_skipped_tools or [],
        agent_route_summary=agent_route_summary or _empty_agent_route_summary(),
        structured_answer=quality["structured_answer"],
        answer_validation=quality["answer_validation"],
        citation_validation=quality["citation_validation"],
        compliance_validation=quality["compliance_validation"],
        prompt_name=metadata.get("prompt_name"),
        prompt_alias=metadata.get("prompt_alias"),
        prompt_version=metadata.get("prompt_version"),
        prompt_hash=metadata.get("prompt_hash"),
        mlflow_trace_id=metadata.get("mlflow_trace_id"),
        mlflow_run_id=metadata.get("mlflow_run_id"),
        latency_ms=latency_ms,
        mode=mode,
        capability_id=metadata.get("capability_id"),
        capability_status=metadata.get("capability_status"),
        capability_tier=metadata.get("capability_tier"),
        safe_fallback_used=metadata.get("safe_fallback_used"),
        validation_status=metadata.get("validation_status"),
        missing_requirements=metadata.get("missing_requirements") or [],
        contract_name=metadata.get("contract_name"),
        contract_version=metadata.get("contract_version"),
        contract_hash=metadata.get("contract_hash"),
        stage_metadata=metadata.get("stage_metadata") or {},
    )


def _assessment_payload(
    *,
    answer: str,
    citations: list[dict[str, Any]],
    status_text: str,
    ready: bool,
    briefing_type: str,
    metadata: dict[str, Any],
    agent_tool_calls: list[dict[str, Any]] | None = None,
    agent_skipped_tools: list[dict[str, Any]] | None = None,
    agent_route_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    quality = build_answer_quality_metadata(answer, citations, briefing_type=briefing_type)
    public_metadata = {key: value for key, value in metadata.items() if not key.startswith("_")}
    return {
        "answer": answer,
        "citations": citations,
        "status_text": status_text,
        "ready": ready,
        "briefing_type": briefing_type,
        "agent_tool_calls": agent_tool_calls or [],
        "agent_skipped_tools": agent_skipped_tools or [],
        "agent_route_summary": agent_route_summary or _empty_agent_route_summary(),
        "structured_answer": quality["structured_answer"],
        "answer_validation": quality["answer_validation"],
        "citation_validation": quality["citation_validation"],
        "compliance_validation": quality["compliance_validation"],
        **public_metadata,
    }


def _empty_agent_route_summary() -> dict[str, Any]:
    return {
        "route_mode": "direct_answer",
        "route_reason": "No se ejecutaron herramientas adicionales.",
        "requested_tools": [],
        "executed_tools": [],
        "skipped_tools": [],
        "documents_requested": False,
        "direct_answer": True,
        "read_only": True,
    }


def _route_fields(route: Any | None) -> dict[str, Any]:
    if route is None:
        return {
            "agent_tool_calls": [],
            "agent_skipped_tools": [],
            "agent_route_summary": _empty_agent_route_summary(),
        }
    return {
        "agent_tool_calls": route.agent_tool_calls,
        "agent_skipped_tools": route.agent_skipped_tools,
        "agent_route_summary": route.agent_route_summary,
    }


def _contract_metadata_for_stage(analysis_stage: str | None) -> dict[str, Any]:
    contract_name = STAGE_CONTRACT_NAMES.get(str(analysis_stage or ""))
    if not contract_name:
        return {}
    try:
        return contract_metadata(contract_name)
    except Exception as exc:
        return {
            "contract_name": contract_name,
            "contract_version": None,
            "contract_hash": None,
            "contract_error": str(exc),
        }


def _apply_stage_context(
    settings: Settings,
    *,
    analysis_stage: str | None,
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
    chunks: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not analysis_stage or analysis_stage == "guided_answer":
        metadata["analysis_stage"] = analysis_stage
        return context_package, None

    context_with_stage = dict(context_package)
    if chunks:
        context_with_stage["retrieved_chunks"] = chunks
        context_with_stage["documentary_evidence_context"] = _documentary_payload_from_chunks(
            chunks=chunks,
            citations=citations,
            trace_id=metadata.get("trace_id"),
        )

    stage_payload = _stage_payload(
        settings,
        analysis_stage=analysis_stage,
        selected_context=selected_context,
        context_package=context_with_stage,
        chunks=chunks,
        citations=citations,
        trace_id=metadata.get("trace_id"),
    )
    if stage_payload is None:
        stage_payload = unavailable_payload(
            capability_id="structured_context",
            reason="La etapa solicitada no esta registrada para el flujo actual.",
            missing_requirements=["registered analysis_stage"],
            trace_id=metadata.get("trace_id"),
        )
    context_key = _stage_context_key(analysis_stage)
    if context_key:
        context_with_stage[context_key] = stage_payload
    context_with_stage["analysis_stage_context"] = stage_payload

    workflow = build_workflow_trace(
        analysis_stage=analysis_stage,
        evidence_packages={
            "structured": bool(context_with_stage),
            "documentary": _payload_available(context_with_stage.get("documentary_evidence_context")),
            "model": _payload_available(context_with_stage.get("model_evidence")),
            "simulation": _payload_available(context_with_stage.get("what_if_results")),
            "report": _payload_available(context_with_stage.get("evidence_report_context")),
        },
    )
    context_with_stage["agent_workflow"] = workflow

    capability_id = str(stage_payload.get("capability_id") or metadata.get("capability_id") or "")
    capability_status = str(stage_payload.get("status") or metadata.get("capability_status") or "")
    if capability_id:
        capability = capability_metadata(capability_id, status=capability_status or None)
        metadata["capability_id"] = capability_id
        metadata["capability_status"] = capability_status or capability.get("capability_status")
        metadata["capability_tier"] = capability.get("capability_tier")
    metadata["safe_fallback_used"] = capability_status in _FALLBACK_STAGE_STATUSES
    metadata["validation_status"] = "not_run_no_llm_output" if metadata["safe_fallback_used"] else "pending"
    metadata["missing_requirements"] = _missing_requirements(stage_payload)
    metadata["stage_metadata"] = {
        "analysis_stage": analysis_stage,
        "capability_payload": _compact_payload(stage_payload),
        "agent_workflow": workflow,
        "prompt_metadata": stage_prompt_metadata(analysis_stage),
        "contract": _contract_metadata_for_stage(analysis_stage),
    }
    metadata["model_evidence"] = _compact_payload(context_with_stage.get("model_evidence") or {})
    metadata["feature_mask_summary"] = _compact_payload(context_with_stage.get("feature_masks") or {})
    metadata["report_artifact"] = _compact_payload(context_with_stage.get("evidence_report_context") or {})
    return context_with_stage, stage_payload


def _stage_payload(
    settings: Settings,
    *,
    analysis_stage: str,
    selected_context: dict[str, Any],
    context_package: dict[str, Any],
    chunks: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    trace_id: str | None,
) -> dict[str, Any] | None:
    if analysis_stage == "structured_context":
        return _structured_context_payload(context_package=context_package, trace_id=trace_id)
    if analysis_stage in {"critical_point_interpretation", "uiti_vano_behavior_explanation"}:
        return _critical_point_payload(
            analysis_stage=analysis_stage,
            context_package=context_package,
            trace_id=trace_id,
        )
    if analysis_stage == "documentary_analysis":
        return _documentary_payload_from_chunks(chunks=chunks, citations=citations, trace_id=trace_id)
    if analysis_stage == "predictive_interpretation":
        return context_package.get("model_evidence") or build_model_evidence_package(
            settings,
            features=_explicit_features(selected_context, context_package),
            context=context_package,
            trace_id=trace_id,
        )
    if analysis_stage == "feature_mask_interpretation":
        return context_package.get("feature_masks") or build_feature_mask_package(
            _raw_model_response(selected_context, context_package),
            trace_id=trace_id,
        )
    if analysis_stage == "three_way_causal_synthesis":
        return build_three_way_context(
            structured_evidence=context_package,
            documentary_evidence=context_package.get("documentary_evidence_context"),
            model_evidence=context_package.get("model_evidence"),
            feature_masks=context_package.get("feature_masks"),
            trace_id=trace_id,
        )
    if analysis_stage == "intervention_selection":
        return build_intervention_candidate_context(
            settings,
            evidence_context=context_package.get("three_way_synthesis_context") or context_package,
            trace_id=trace_id,
        )
    if analysis_stage == "what_if_simulation":
        return run_what_if_simulation(
            settings,
            request=_what_if_request(selected_context, context_package),
            baseline_features=_baseline_features(selected_context, context_package),
            trace_id=trace_id,
        )
    if analysis_stage == "evidence_report":
        return build_evidence_report_context(
            structured_context=context_package,
            critical_points=context_package.get("critical_points"),
            documentary_evidence=context_package.get("documentary_evidence_context"),
            normative_evidence=context_package.get("normative_evidence_context"),
            model_evidence=context_package.get("model_evidence"),
            feature_masks=context_package.get("feature_masks"),
            intervention_candidates=context_package.get("intervention_candidates"),
            what_if_results=context_package.get("what_if_results"),
            validation_metadata=context_package.get("validation"),
            trace_id=trace_id,
        )
    return None


def _structured_context_payload(*, context_package: dict[str, Any], trace_id: str | None) -> dict[str, Any]:
    return {
        "status": "available",
        "capability_id": "structured_context",
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "source": "dashboard_context",
        "selected_context": context_package.get("selected_context") or context_package,
        "evidence": context_package.get("agent_tool_evidence") or [],
        "limitations": context_package.get("limitations") or [],
        "warnings": [],
        "trace_id": trace_id,
        "traceability": capability_metadata("structured_context", status="available"),
    }


def _critical_point_payload(
    *,
    analysis_stage: str,
    context_package: dict[str, Any],
    trace_id: str | None,
) -> dict[str, Any]:
    capability_id = (
        "critical_point_interpretation"
        if analysis_stage == "critical_point_interpretation"
        else "uiti_vano_behavior_explanation"
    )
    evidence = _tool_evidence(context_package, "timeseries_interpretability")
    status = "available" if evidence else "partial"
    missing = [] if evidence else ["timeseries interpretability context"]
    return {
        "status": status,
        "capability_id": capability_id,
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "source": "timeseries_interpretability",
        "selected_context": context_package.get("selected_context") or {},
        "evidence": evidence,
        "missing_evidence": missing,
        "limitations": ["La interpretacion temporal no prueba causalidad definitiva."],
        "warnings": [] if evidence else ["No se encontro contexto interpretativo de serie temporal."],
        "trace_id": trace_id,
        "traceability": capability_metadata(capability_id, status=status),
    }


def _documentary_payload_from_chunks(
    *,
    chunks: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    trace_id: str | None,
) -> dict[str, Any]:
    if not chunks:
        return unavailable_payload(
            capability_id="documentary_normative_analysis",
            reason="No hay fragmentos documentales recuperados para esta etapa.",
            missing_requirements=["retrieved document chunks"],
            next_steps=["Configurar recuperacion o cargar corpus documental antes de analizar normativa."],
            trace_id=trace_id,
            status="not_provided",
        )
    return {
        "status": "available",
        "capability_id": "documentary_normative_analysis",
        "schema_version": "0.1.0",
        "generated_at": utc_now(),
        "source": "configured_retriever",
        "selected_context": {},
        "evidence": chunks,
        "citations": citations,
        "limitations": ["Solo se analizan los fragmentos recuperados y citables."],
        "warnings": [],
        "trace_id": trace_id,
        "traceability": capability_metadata("documentary_normative_analysis", status="available"),
    }


def _stage_context_key(analysis_stage: str) -> str | None:
    mapping = {
        "structured_context": "structured_context_package",
        "critical_point_interpretation": "critical_point_interpretation",
        "uiti_vano_behavior_explanation": "uiti_vano_behavior_explanation",
        "documentary_analysis": "documentary_evidence_context",
        "predictive_interpretation": "model_evidence",
        "feature_mask_interpretation": "feature_masks",
        "three_way_causal_synthesis": "three_way_synthesis_context",
        "intervention_selection": "intervention_candidates",
        "what_if_simulation": "what_if_results",
        "evidence_report": "evidence_report_context",
    }
    return mapping.get(analysis_stage)


def _should_short_circuit_stage(stage_payload: dict[str, Any] | None) -> bool:
    return str((stage_payload or {}).get("status") or "") in _FALLBACK_STAGE_STATUSES


def _validate_stage_answer(
    *,
    answer: str,
    analysis_stage: str | None,
    context_package: dict[str, Any],
    chunks: list[dict[str, Any]],
    stage_payload: dict[str, Any] | None,
    metadata: dict[str, Any],
) -> tuple[str, bool, str | None]:
    if not analysis_stage or analysis_stage == "guided_answer":
        return answer, True, None
    validation = validate_llm_output(
        answer,
        contract_name=None,
        chunks=chunks,
        context_package=context_package,
        capability_payload=stage_payload,
        analysis_stage=analysis_stage,
    )
    metadata["llm_output_validation"] = validation
    metadata["validation_status"] = validation["validation_status"]
    metadata["evidence_policy_validation"] = {
        "citation_validation": validation.get("citation_validation") or {},
        "warnings": validation.get("warnings") or [],
        "errors": validation.get("errors") or [],
    }
    if validation["valid"]:
        return answer, True, None
    metadata["safe_fallback_used"] = True
    return validation.get("fallback_text") or fallback_text(capability_payload=stage_payload, errors=validation["errors"]), False, (
        "La salida del LLM no paso las validaciones de gobernanza."
    )


def _tool_evidence(context_package: dict[str, Any], term: str) -> list[dict[str, Any]]:
    rows = []
    for item in context_package.get("agent_tool_evidence") or []:
        text = " ".join(str(item.get(key) or "") for key in ("tool_name", "source_function", "source_view"))
        if term in text:
            rows.append(item)
    return rows


def _payload_available(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("status") not in _FALLBACK_STAGE_STATUSES and bool(payload)


def _missing_requirements(payload: dict[str, Any]) -> list[str]:
    missing = payload.get("missing_requirements") or payload.get("missing_evidence") or []
    if isinstance(missing, list):
        return [str(item) for item in missing if str(item)]
    return [str(missing)] if missing else []


def _compact_payload(payload: Any, *, limit: int = 12) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    compact: dict[str, Any] = {}
    for key, value in payload.items():
        if key in {"evidence", "records", "citations"} and isinstance(value, list):
            compact[key] = value[:limit]
        elif isinstance(value, dict):
            compact[key] = _compact_payload(value, limit=limit)
        elif isinstance(value, list):
            compact[key] = value[:limit]
        else:
            compact[key] = value
    return compact


def _context_value(selected_context: dict[str, Any], context_package: dict[str, Any], *keys: str) -> Any:
    sources = [
        selected_context,
        context_package.get("selected_context") if isinstance(context_package.get("selected_context"), dict) else {},
        context_package,
    ]
    for key in keys:
        for source in sources:
            value = source.get(key) if isinstance(source, dict) else None
            if value not in (None, ""):
                return value
    return None


def _explicit_features(selected_context: dict[str, Any], context_package: dict[str, Any]) -> dict[str, Any] | None:
    value = _context_value(selected_context, context_package, "model_features", "features", "baseline_features")
    return value if isinstance(value, dict) else None


def _baseline_features(selected_context: dict[str, Any], context_package: dict[str, Any]) -> dict[str, Any] | None:
    value = _context_value(selected_context, context_package, "baseline_features")
    return value if isinstance(value, dict) else None


def _what_if_request(selected_context: dict[str, Any], context_package: dict[str, Any]) -> dict[str, Any] | None:
    value = _context_value(selected_context, context_package, "what_if_request", "scenario_request")
    return value if isinstance(value, dict) else None


def _raw_model_response(selected_context: dict[str, Any], context_package: dict[str, Any]) -> dict[str, Any] | None:
    model_evidence = context_package.get("model_evidence")
    if isinstance(model_evidence, dict) and isinstance(model_evidence.get("raw_response_subset"), dict):
        return model_evidence["raw_response_subset"]
    value = _context_value(selected_context, context_package, "raw_model_response")
    return value if isinstance(value, dict) else None


def assess_chatbot_context(
    settings: Settings,
    *,
    selected_context: dict[str, Any],
    question: str | None,
    briefing_type: str = "reliability",
    analysis_stage: str | None = None,
    question_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    briefing_type = sanitize_briefing_type(briefing_type)
    resolved_question = resolve_question(briefing_type, question_id, question)
    skill_resolution = resolve_skill(briefing_type, settings, analysis_stage=analysis_stage)
    metadata = _response_metadata(
        settings=settings,
        conversation_id=conversation_id,
        skill_resolution=skill_resolution,
        analysis_stage=analysis_stage,
    )
    status = get_chatbot_status(settings)
    if not selected_context:
        answer = "Selecciona primero un evento o elemento de red para analizar."
        status_text = "Falta contexto seleccionado."
        _persist_response(
            settings,
            metadata=metadata,
            user_message=_guided_user_message(resolved_question),
            answer=answer,
            briefing_type=briefing_type,
            question_id=question_id,
            context_package={},
            citations=[],
            chunks=[],
            status_text=status_text,
            ready=False,
            **_route_fields(None),
        )
        return _assessment_payload(
            answer=answer,
            citations=[],
            status_text=status_text,
            ready=False,
            briefing_type=briefing_type,
            metadata=metadata,
            **_route_fields(None),
        )

    context_package = build_chatbot_context_package(
        selected_context=selected_context,
        briefing_type=briefing_type,
        question_id=question_id,
    )
    user_message = _guided_user_message(resolved_question)
    route = execute_agent_route(
        settings,
        selected_context=selected_context,
        context_package=context_package,
        question=resolved_question,
        briefing_type=briefing_type,
        question_id=question_id,
        skill_resolution=skill_resolution,
        analysis_stage=analysis_stage,
    )
    context_package = route.context_package
    chunks = route.chunks
    citations = citation_payload(chunks)

    if not route.documents_executed:
        chunks = []
        citations = []
    context_package, stage_payload = _apply_stage_context(
        settings,
        analysis_stage=analysis_stage,
        selected_context=selected_context,
        context_package=context_package,
        chunks=chunks,
        citations=citations,
        metadata=metadata,
    )

    if not status["enabled"]:
        answer = (
            "El asistente técnico está deshabilitado. El contexto fue seleccionado, "
            "pero no se generó análisis. Activa CHATBOT_ENABLED para usar esta pestaña."
        )
        status_text = status["message"]
        _persist_response(
            settings,
            metadata=metadata,
            user_message=user_message,
            answer=answer,
            briefing_type=briefing_type,
            question_id=question_id,
            context_package=context_package,
            citations=citations,
            chunks=chunks,
            status_text=status_text,
            ready=False,
            **_route_fields(route),
        )
        return _assessment_payload(
            answer=answer,
            citations=citations,
            status_text=status_text,
            ready=False,
            briefing_type=briefing_type,
            metadata=metadata,
            **_route_fields(route),
        )
    if _should_short_circuit_stage(stage_payload):
        answer = fallback_text(capability_payload=stage_payload, errors=[])
        status_text = str((stage_payload or {}).get("reason") or "Etapa no disponible para ejecucion productiva.")
        metadata["safe_fallback_used"] = True
        metadata["validation_status"] = "not_run_no_llm_output"
        metadata["llm_output_validation"] = {
            "valid": True,
            "validation_status": "not_run_no_llm_output",
            "errors": [],
            "warnings": (stage_payload or {}).get("warnings") or [],
        }
        _persist_response(
            settings,
            metadata=metadata,
            user_message=user_message,
            answer=answer,
            briefing_type=briefing_type,
            question_id=question_id,
            context_package=context_package,
            citations=citations,
            chunks=chunks,
            status_text=status_text,
            ready=False,
            **_route_fields(route),
        )
        return _assessment_payload(
            answer=answer,
            citations=citations,
            status_text=status_text,
            ready=False,
            briefing_type=briefing_type,
            metadata=metadata,
            **_route_fields(route),
        )
    if route.documents_executed and not status.get("retriever_configured", True):
        answer = (
            "El recuperador técnico seleccionado no está configurado. "
            "Revisa RETRIEVER_BACKEND y AI_SEARCH_INDEX_NAME antes de solicitar el análisis."
        )
        status_text = status["message"]
        _persist_response(
            settings,
            metadata=metadata,
            user_message=user_message,
            answer=answer,
            briefing_type=briefing_type,
            question_id=question_id,
            context_package=context_package,
            citations=[],
            chunks=[],
            status_text=status_text,
            ready=False,
            **_route_fields(route),
        )
        return _assessment_payload(
            answer=answer,
            citations=[],
            status_text=status_text,
            ready=False,
            briefing_type=briefing_type,
            metadata=metadata,
            **_route_fields(route),
        )
    if route.documents_executed and not chunks:
        answer = (
            "No se encontraron documentos técnicos relevantes en el corpus. "
            "Carga o reconstruye el corpus antes de solicitar el análisis."
        )
        status_text = "Corpus técnico sin resultados para este contexto."
        _persist_response(
            settings,
            metadata=metadata,
            user_message=user_message,
            answer=answer,
            briefing_type=briefing_type,
            question_id=question_id,
            context_package=context_package,
            citations=[],
            chunks=[],
            status_text=status_text,
            ready=False,
            **_route_fields(route),
        )
        return _assessment_payload(
            answer=answer,
            citations=[],
            status_text=status_text,
            ready=False,
            briefing_type=briefing_type,
            metadata=metadata,
            **_route_fields(route),
        )
    if not status["llm_configured"]:
        answer = (
            "El proveedor LLM seleccionado no está configurado para generar el análisis. "
            "Ya se recuperó contexto técnico y citas iniciales."
        )
        status_text = status["message"]
        _persist_response(
            settings,
            metadata=metadata,
            user_message=user_message,
            answer=answer,
            briefing_type=briefing_type,
            question_id=question_id,
            context_package=context_package,
            citations=citations,
            chunks=chunks,
            status_text=status_text,
            ready=False,
            **_route_fields(route),
        )
        return _assessment_payload(
            answer=answer,
            citations=citations,
            status_text=status_text,
            ready=False,
            briefing_type=briefing_type,
            metadata=metadata,
            **_route_fields(route),
        )

    if analysis_stage and analysis_stage != "guided_answer":
        prompt = build_stage_prompt(
            context_package=context_package,
            question=resolved_question,
            briefing_type=briefing_type,
            analysis_stage=analysis_stage,
            chunks=chunks,
            skill_resolution=skill_resolution,
            settings=settings,
        )
    else:
        prompt = build_prompt(
            context_package=context_package,
            question=resolved_question,
            briefing_type=briefing_type,
            chunks=chunks,
            skill_resolution=skill_resolution,
            settings=settings,
        )
    llm_tier = select_llm_tier(settings, prompt=prompt)
    metadata["llm_tier"] = llm_tier
    metadata["model_endpoint_name"] = _model_endpoint_name(settings, llm_tier=llm_tier)
    try:
        answer = generate_llm_answer(
            settings,
            prompt=prompt,
            context_package=context_package,
            question=resolved_question,
            citations=citations,
            skill_resolution=skill_resolution,
            trace_id=metadata.get("trace_id"),
            llm_tier=llm_tier,
        )
    except Exception as exc:
        answer = f"No fue posible generar el análisis con el proveedor LLM '{status['llm_provider']}': {exc}"
        status_text = "Error al consultar el proveedor LLM."
        _persist_response(
            settings,
            metadata=metadata,
            user_message=user_message,
            answer=answer,
            briefing_type=briefing_type,
            question_id=question_id,
            context_package=context_package,
            citations=citations,
            chunks=chunks,
            status_text=status_text,
            ready=False,
            **_route_fields(route),
        )
        return _assessment_payload(
            answer=answer,
            citations=citations,
            status_text=status_text,
            ready=False,
            briefing_type=briefing_type,
            metadata=metadata,
            **_route_fields(route),
        )

    answer, valid_stage_output, validation_status_text = _validate_stage_answer(
        answer=answer,
        analysis_stage=analysis_stage,
        context_package=context_package,
        chunks=chunks,
        stage_payload=stage_payload,
        metadata=metadata,
    )
    if not valid_stage_output:
        _persist_response(
            settings,
            metadata=metadata,
            user_message=user_message,
            answer=answer,
            briefing_type=briefing_type,
            question_id=question_id,
            context_package=context_package,
            citations=citations,
            chunks=chunks,
            status_text=validation_status_text or "Salida LLM invalidada por gobernanza.",
            ready=False,
            **_route_fields(route),
        )
        return _assessment_payload(
            answer=answer,
            citations=citations,
            status_text=validation_status_text or "Salida LLM invalidada por gobernanza.",
            ready=False,
            briefing_type=briefing_type,
            metadata=metadata,
            **_route_fields(route),
        )

    if chunks:
        status_text = "Análisis generado con documentos técnicos recuperados."
    elif route.agent_tool_calls:
        status_text = "Análisis generado con herramientas gobernadas de contexto."
    else:
        status_text = "Respuesta generada con contexto existente e historial disponible."
    _persist_response(
        settings,
        metadata=metadata,
        user_message=user_message,
        answer=answer,
        briefing_type=briefing_type,
        question_id=question_id,
        context_package=context_package,
        citations=citations,
        chunks=chunks,
        status_text=status_text,
        ready=True,
        **_route_fields(route),
    )
    return _assessment_payload(
        answer=answer,
        citations=citations,
        status_text=status_text,
        ready=True,
        briefing_type=briefing_type,
        metadata=metadata,
        **_route_fields(route),
    )


def create_chatbot_conversation(
    settings: Settings,
    *,
    selected_context: dict[str, Any] | None = None,
    briefing_type: str = "reliability",
    analysis_stage: str | None = None,
    mode: str = "guided",
) -> dict[str, Any]:
    briefing_type = sanitize_briefing_type(briefing_type)
    skill_resolution = resolve_skill(briefing_type, settings, analysis_stage=analysis_stage)
    context_snapshot = (
        build_chatbot_context_package(
            selected_context=selected_context,
            briefing_type=briefing_type,
            question_id=None,
        )
        if selected_context
        else {}
    )
    conversation = create_conversation(
        settings,
        mode=mode,
        briefing_type=briefing_type,
        analysis_stage=analysis_stage,
        selected_context=context_snapshot,
        title="Conversación técnica",
        skill_id=skill_resolution.skill_id,
        skill_version=skill_resolution.skill_version,
        skill_hash=skill_resolution.skill_hash,
        llm_provider=llm_provider(settings),
        model_endpoint_name=_model_endpoint_name(settings),
    )
    detail = get_conversation_detail(settings, conversation.conversation_id)
    return detail or {
        "conversation_id": conversation.conversation_id,
        "mode": mode,
        "briefing_type": briefing_type,
        "analysis_stage": analysis_stage,
        "messages": [],
    }


def get_chatbot_conversation(settings: Settings, conversation_id: str) -> dict[str, Any] | None:
    return get_conversation_detail(settings, conversation_id)


def send_chatbot_message(
    settings: Settings,
    *,
    conversation_id: str,
    message: str,
    briefing_type: str | None = None,
    analysis_stage: str | None = None,
    selected_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    message = " ".join((message or "").split())
    if not message:
        return None
    conversation = get_conversation_detail(settings, conversation_id)
    if conversation is None:
        return None

    resolved_briefing_type = sanitize_briefing_type(
        briefing_type or conversation.get("briefing_type") or "reliability"
    )
    resolved_analysis_stage = analysis_stage or conversation.get("analysis_stage")
    skill_resolution = resolve_skill(resolved_briefing_type, settings, analysis_stage=resolved_analysis_stage)
    metadata = _response_metadata(
        settings=settings,
        conversation_id=conversation_id,
        skill_resolution=skill_resolution,
        analysis_stage=resolved_analysis_stage,
    )
    context_package = (
        build_chatbot_context_package(
            selected_context=selected_context,
            briefing_type=resolved_briefing_type,
            question_id=None,
        )
        if selected_context
        else (conversation.get("context_snapshot") or {})
    )
    if not context_package:
        answer = "No hay contexto guardado para continuar la conversación."
        status_text = "Falta contexto de conversación."
        _persist_response(
            settings,
            metadata=metadata,
            user_message=message,
            answer=answer,
            briefing_type=resolved_briefing_type,
            question_id=None,
            context_package={},
            citations=[],
            chunks=[],
            status_text=status_text,
            ready=False,
            **_route_fields(None),
            mode="free_form",
        )
        return _assessment_payload(
            answer=answer,
            citations=[],
            status_text=status_text,
            ready=False,
            briefing_type=resolved_briefing_type,
            metadata=metadata,
            **_route_fields(None),
        )

    status = get_chatbot_status(settings)
    history = recent_conversation_messages(settings, conversation_id)
    route = execute_agent_route(
        settings,
        selected_context=selected_context or {},
        context_package=context_package,
        question=message,
        briefing_type=resolved_briefing_type,
        question_id=None,
        skill_resolution=skill_resolution,
        analysis_stage=resolved_analysis_stage,
        conversation_history=history,
    )
    context_package = route.context_package
    chunks = route.chunks
    citations = citation_payload(chunks)
    if not route.documents_executed:
        chunks = []
        citations = []
    context_package, stage_payload = _apply_stage_context(
        settings,
        analysis_stage=resolved_analysis_stage,
        selected_context=selected_context or {},
        context_package=context_package,
        chunks=chunks,
        citations=citations,
        metadata=metadata,
    )

    if not status["enabled"]:
        answer = "El asistente técnico está deshabilitado para continuar la conversación."
        status_text = status["message"]
        ready = False
    elif _should_short_circuit_stage(stage_payload):
        answer = fallback_text(capability_payload=stage_payload, errors=[])
        status_text = str((stage_payload or {}).get("reason") or "Etapa no disponible para ejecucion productiva.")
        metadata["safe_fallback_used"] = True
        metadata["validation_status"] = "not_run_no_llm_output"
        metadata["llm_output_validation"] = {
            "valid": True,
            "validation_status": "not_run_no_llm_output",
            "errors": [],
            "warnings": (stage_payload or {}).get("warnings") or [],
        }
        ready = False
    elif route.documents_executed and not status.get("retriever_configured", True):
        answer = (
            "El recuperador técnico seleccionado no está configurado para continuar la conversación."
        )
        citations = []
        status_text = status["message"]
        ready = False
    elif route.documents_executed and not chunks:
        answer = (
            "No se encontraron documentos técnicos relevantes para esta pregunta. "
            "Puedes reformularla o seleccionar otro contexto."
        )
        citations = []
        status_text = "Corpus técnico sin resultados para el seguimiento."
        ready = False
    elif not status["llm_configured"]:
        answer = (
            "El proveedor LLM seleccionado no está configurado para continuar la conversación. "
            "Ya se recuperó contexto técnico y citas iniciales."
        )
        status_text = status["message"]
        ready = False
    else:
        if resolved_analysis_stage and resolved_analysis_stage != "guided_answer":
            prompt = build_stage_prompt(
                context_package=context_package,
                question=message,
                briefing_type=resolved_briefing_type,
                analysis_stage=resolved_analysis_stage,
                chunks=chunks,
                skill_resolution=skill_resolution,
                conversation_history=history,
                settings=settings,
            )
        else:
            prompt = build_prompt(
                context_package=context_package,
                question=message,
                briefing_type=resolved_briefing_type,
                chunks=chunks,
                skill_resolution=skill_resolution,
                conversation_history=history,
                settings=settings,
            )
        llm_tier = select_llm_tier(settings, prompt=prompt)
        metadata["llm_tier"] = llm_tier
        metadata["model_endpoint_name"] = _model_endpoint_name(settings, llm_tier=llm_tier)
        try:
            answer = generate_llm_answer(
                settings,
                prompt=prompt,
                context_package=context_package,
                question=message,
                citations=citations,
                skill_resolution=skill_resolution,
                trace_id=metadata.get("trace_id"),
                llm_tier=llm_tier,
            )
            if chunks:
                status_text = "Respuesta de seguimiento generada con memoria y documentos recuperados."
            elif route.agent_tool_calls:
                status_text = "Respuesta de seguimiento generada con memoria y herramientas gobernadas."
            else:
                status_text = "Respuesta de seguimiento generada con memoria de conversación."
            ready = True
        except Exception as exc:
            answer = f"No fue posible continuar la conversación con el proveedor LLM '{status['llm_provider']}': {exc}"
            status_text = "Error al consultar el proveedor LLM."
            ready = False
        if ready:
            answer, valid_stage_output, validation_status_text = _validate_stage_answer(
                answer=answer,
                analysis_stage=resolved_analysis_stage,
                context_package=context_package,
                chunks=chunks,
                stage_payload=stage_payload,
                metadata=metadata,
            )
            if not valid_stage_output:
                status_text = validation_status_text or "Salida LLM invalidada por gobernanza."
                ready = False

    _persist_response(
        settings,
        metadata=metadata,
        user_message=message,
        answer=answer,
        briefing_type=resolved_briefing_type,
        question_id=None,
        context_package=context_package,
        citations=citations,
        chunks=chunks,
        status_text=status_text,
        ready=ready,
        **_route_fields(route),
        mode="free_form",
    )
    return _assessment_payload(
        answer=answer,
        citations=citations,
        status_text=status_text,
        ready=ready,
        briefing_type=resolved_briefing_type,
        metadata=metadata,
        **_route_fields(route),
    )


def submit_chatbot_feedback(
    settings: Settings,
    *,
    conversation_id: str,
    turn_id: str,
    rating: str,
    comment: str | None = None,
) -> dict[str, Any]:
    rating = (rating or "").strip().lower()
    if rating not in {"helpful", "not_helpful"}:
        raise ValueError("rating debe ser 'helpful' o 'not_helpful'.")
    payload = record_feedback(
        settings,
        conversation_id=conversation_id,
        turn_id=turn_id,
        rating=rating,
        comment=comment,
    )
    turn_metadata = _feedback_turn_metadata(settings, conversation_id, turn_id)
    payload.update(turn_metadata)
    record_feedback_observability(settings, payload)
    return payload


def _feedback_turn_metadata(settings: Settings, conversation_id: str, turn_id: str) -> dict[str, Any]:
    detail = get_conversation_detail(settings, conversation_id) or {}
    for message in detail.get("messages") or []:
        if message.get("role") == "assistant" and message.get("turn_id") == turn_id:
            return {
                "trace_id": message.get("trace_id"),
                "mlflow_trace_id": message.get("mlflow_trace_id"),
                "mlflow_run_id": message.get("mlflow_run_id"),
                "prompt_name": message.get("prompt_name"),
                "prompt_version": message.get("prompt_version"),
                "skill_id": message.get("skill_id"),
                "skill_hash": message.get("skill_hash"),
                "llm_provider": message.get("llm_provider"),
                "model_endpoint_name": message.get("model_endpoint_name"),
            }
    return {}
