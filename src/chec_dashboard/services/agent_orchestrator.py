from __future__ import annotations

import time
from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.agent_context_service import (
    build_chatbot_context_package,
    resolve_question,
    sanitize_briefing_type,
)
from chec_dashboard.services.agent_routing_service import execute_agent_route
from chec_dashboard.services.agent_trace_service import create_trace_id
from chec_dashboard.services.answer_quality_service import build_answer_quality_metadata
from chec_dashboard.services.citation_service import citation_payload
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
)
from chec_dashboard.services.observability_service import (
    context_hash,
    observability_status,
    record_feedback_observability,
    record_turn_observability,
    resolve_prompt_metadata,
)
from chec_dashboard.services.prompt_service import ANSWER_PROMPT_TEMPLATE, build_prompt
from chec_dashboard.services.retrieval_service import (
    Corpus,
    corpus_runtime_diagnostics,
    load_chatbot_corpus,
    retriever_runtime_diagnostics,
)
from chec_dashboard.services.skill_service import SkillResolution, get_skill_status, resolve_skill


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
) -> dict[str, Any]:
    conversation_turn = resolve_conversation_turn(conversation_id)
    prompt_metadata = resolve_prompt_metadata(settings, ANSWER_PROMPT_TEMPLATE)
    return {
        "conversation_id": conversation_turn.conversation_id,
        "turn_id": conversation_turn.turn_id,
        "skill_id": skill_resolution.skill_id,
        "skill_version": skill_resolution.skill_version,
        "skill_hash": skill_resolution.skill_hash,
        "trace_id": create_trace_id(),
        "llm_provider": llm_provider(settings),
        "model_endpoint_name": _model_endpoint_name(settings),
        "prompt_name": prompt_metadata.prompt_name,
        "prompt_alias": prompt_metadata.prompt_alias,
        "prompt_version": prompt_metadata.prompt_version,
        "prompt_hash": prompt_metadata.prompt_hash,
        "prompt_source": prompt_metadata.prompt_source,
        "prompt_registry_error": prompt_metadata.prompt_registry_error,
        "mlflow_trace_id": None,
        "mlflow_run_id": None,
        "observability_status": "pending" if settings.chatbot_observability_enabled else "disabled",
        "observability_error": None,
        "_turn_started_at": time.perf_counter(),
    }


def _model_endpoint_name(settings: Settings) -> str | None:
    endpoint_name = llm_endpoint_name(settings)
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
            "model_endpoint_name": metadata.get("model_endpoint_name"),
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
            },
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


def assess_chatbot_context(
    settings: Settings,
    *,
    selected_context: dict[str, Any],
    question: str | None,
    briefing_type: str = "reliability",
    question_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    briefing_type = sanitize_briefing_type(briefing_type)
    resolved_question = resolve_question(briefing_type, question_id, question)
    skill_resolution = resolve_skill(briefing_type, settings)
    metadata = _response_metadata(settings=settings, conversation_id=conversation_id, skill_resolution=skill_resolution)
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
    )
    context_package = route.context_package
    chunks = route.chunks
    citations = citation_payload(chunks)

    if not route.documents_executed:
        chunks = []
        citations = []

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

    prompt = build_prompt(
        context_package=context_package,
        question=resolved_question,
        briefing_type=briefing_type,
        chunks=chunks,
        skill_resolution=skill_resolution,
        settings=settings,
    )
    try:
        answer = generate_llm_answer(
            settings,
            prompt=prompt,
            context_package=context_package,
            question=resolved_question,
            citations=citations,
            skill_resolution=skill_resolution,
            trace_id=metadata.get("trace_id"),
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
    mode: str = "guided",
) -> dict[str, Any]:
    briefing_type = sanitize_briefing_type(briefing_type)
    skill_resolution = resolve_skill(briefing_type, settings)
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
    skill_resolution = resolve_skill(resolved_briefing_type, settings)
    metadata = _response_metadata(settings=settings, conversation_id=conversation_id, skill_resolution=skill_resolution)
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
        conversation_history=history,
    )
    context_package = route.context_package
    chunks = route.chunks
    citations = citation_payload(chunks)
    if not route.documents_executed:
        chunks = []
        citations = []

    if not status["enabled"]:
        answer = "El asistente técnico está deshabilitado para continuar la conversación."
        status_text = status["message"]
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
        prompt = build_prompt(
            context_package=context_package,
            question=message,
            briefing_type=resolved_briefing_type,
            chunks=chunks,
            skill_resolution=skill_resolution,
            conversation_history=history,
            settings=settings,
        )
        try:
            answer = generate_llm_answer(
                settings,
                prompt=prompt,
                context_package=context_package,
                question=message,
                citations=citations,
                skill_resolution=skill_resolution,
                trace_id=metadata.get("trace_id"),
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
