from __future__ import annotations

from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.agent_context_service import (
    build_chatbot_context_package,
    resolve_question,
    sanitize_briefing_type,
)
from chec_dashboard.services.agent_trace_service import create_trace_id
from chec_dashboard.services.citation_service import citation_payload
from chec_dashboard.services.conversation_service import resolve_conversation_turn
from chec_dashboard.services.llm_service import (
    generate_llm_answer,
    llm_configuration_message,
    llm_configured,
    llm_provider,
)
from chec_dashboard.services.prompt_service import build_prompt
from chec_dashboard.services.retrieval_service import (
    Corpus,
    corpus_runtime_diagnostics,
    load_chatbot_corpus,
    retrieve_chatbot_chunks,
)
from chec_dashboard.services.skill_service import SkillResolution, get_skill_status, resolve_skill


def get_chatbot_status(settings: Settings) -> dict[str, Any]:
    corpus_error = None
    try:
        corpus = load_chatbot_corpus(settings)
    except Exception as exc:
        corpus = Corpus(chunks=[], documents=[], variables=[])
        corpus_error = str(exc)
    diagnostics = corpus_runtime_diagnostics(settings)
    enabled = settings.chatbot_enabled
    provider = llm_provider(settings)
    configured = llm_configured(settings)
    gemini_configured = bool(settings.gemini_api_key)
    corpus_available = bool(corpus.chunks)
    ready = enabled and configured and corpus_available

    if not enabled:
        message = "El asistente técnico está deshabilitado en esta instalación."
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
        "gemini_configured": gemini_configured,
        "corpus_available": corpus_available,
        "ready": ready,
        "documents_count": len(corpus.documents),
        "chunks_count": len(corpus.chunks),
        "message": message,
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
    return payload


def _response_metadata(
    *,
    conversation_id: str | None,
    skill_resolution: SkillResolution,
) -> dict[str, Any]:
    conversation_turn = resolve_conversation_turn(conversation_id)
    return {
        "conversation_id": conversation_turn.conversation_id,
        "turn_id": conversation_turn.turn_id,
        "skill_id": skill_resolution.skill_id,
        "skill_version": skill_resolution.skill_version,
        "skill_hash": skill_resolution.skill_hash,
        "trace_id": create_trace_id(),
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
    metadata = _response_metadata(conversation_id=conversation_id, skill_resolution=skill_resolution)
    status = get_chatbot_status(settings)
    if not selected_context:
        return {
            "answer": "Selecciona primero un evento o elemento de red para analizar.",
            "citations": [],
            "status_text": "Falta contexto seleccionado.",
            "ready": False,
            "briefing_type": briefing_type,
            **metadata,
        }

    context_package = build_chatbot_context_package(
        selected_context=selected_context,
        briefing_type=briefing_type,
        question_id=question_id,
    )
    chunks = retrieve_chatbot_chunks(
        settings,
        selected_context=context_package,
        question=resolved_question,
        skill_resolution=skill_resolution,
    )
    citations = citation_payload(chunks)

    if not status["enabled"]:
        return {
            "answer": (
                "El asistente técnico está deshabilitado. El contexto fue seleccionado, "
                "pero no se generó análisis. Activa CHATBOT_ENABLED para usar esta pestaña."
            ),
            "citations": citations,
            "status_text": status["message"],
            "ready": False,
            "briefing_type": briefing_type,
            **metadata,
        }
    if not chunks:
        return {
            "answer": (
                "No se encontraron documentos técnicos relevantes en el corpus. "
                "Carga o reconstruye el corpus antes de solicitar el análisis."
            ),
            "citations": [],
            "status_text": "Corpus técnico sin resultados para este contexto.",
            "ready": False,
            "briefing_type": briefing_type,
            **metadata,
        }
    if not status["llm_configured"]:
        return {
            "answer": (
                "El proveedor LLM seleccionado no está configurado para generar el análisis. "
                "Ya se recuperó contexto técnico y citas iniciales."
            ),
            "citations": citations,
            "status_text": status["message"],
            "ready": False,
            "briefing_type": briefing_type,
            **metadata,
        }

    prompt = build_prompt(
        context_package=context_package,
        question=resolved_question,
        briefing_type=briefing_type,
        chunks=chunks,
        skill_resolution=skill_resolution,
    )
    try:
        answer = generate_llm_answer(
            settings,
            prompt=prompt,
            context_package=context_package,
            question=resolved_question,
            citations=citations,
            skill_resolution=skill_resolution,
        )
    except Exception as exc:
        return {
            "answer": f"No fue posible generar el análisis con el proveedor LLM '{status['llm_provider']}': {exc}",
            "citations": citations,
            "status_text": "Error al consultar el proveedor LLM.",
            "ready": False,
            "briefing_type": briefing_type,
            **metadata,
        }

    return {
        "answer": answer,
        "citations": citations,
        "status_text": "Análisis generado con documentos técnicos recuperados.",
        "ready": True,
        "briefing_type": briefing_type,
        **metadata,
    }
