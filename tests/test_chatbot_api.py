from __future__ import annotations

import pytest

from chec_dashboard.api.routes import chatbot as chatbot_routes
from chec_dashboard.api.schemas.chatbot import (
    ChatbotAssessmentRequest,
    ChatbotAssessmentResponse,
    ChatbotConversationCreateRequest,
    ChatbotConversationMessageRequest,
    ChatbotFeedbackRequest,
    ChatbotContextOptionsRequest,
    ChatbotSkillStatusResponse,
)


@pytest.mark.parametrize("context_kind", ["view", "event", "asset"])
def test_chatbot_context_schema_accepts_supported_kinds(context_kind: str) -> None:
    request = ChatbotContextOptionsRequest(
        context_kind=context_kind,
        selected_period="2024-01",
        selected_municipio="Manizales",
    )

    assert request.context_kind == context_kind


def test_chatbot_status_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chatbot_routes,
        "get_chatbot_status",
        lambda settings: {
            "enabled": True,
            "llm_provider": "mock",
            "llm_configured": True,
            "gemini_configured": False,
            "corpus_available": True,
            "ready": True,
            "skills_available": True,
            "skills_count": 6,
            "skill_errors_count": 0,
            "documents_count": 2,
            "chunks_count": 5,
            "message": "Asistente técnico listo.",
        },
    )

    response = chatbot_routes.chatbot_status()

    assert response.chunks_count == 5
    assert response.llm_provider == "mock"
    assert response.ready is True


def test_chatbot_context_options_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chatbot_routes,
        "get_chatbot_context_options",
        lambda **_: {
            "items": [
                {
                    "id": "event-1",
                    "label": "EQ-1 | CKT-1",
                    "kind": "view",
                    "summary": "Vista de prueba",
                    "context": {"kind": "view", "selected_period": "2024-01"},
                }
            ],
            "status_text": "Se encontraron 1 vistas filtradas.",
        },
    )

    response = chatbot_routes.chatbot_context_options(
        ChatbotContextOptionsRequest(
            context_kind="view",
            selected_period="2024-01",
            selected_municipio="Manizales",
            selected_circuits=["CKT-1"],
        )
    )

    assert response.items[0].id == "event-1"
    assert response.items[0].kind == "view"


def test_chatbot_assess_route_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chatbot_routes,
        "assess_chatbot_context",
        lambda **_: {
            "answer": "Gemini no está configurado todavía.",
            "citations": [],
            "status_text": "Gemini no está configurado.",
            "ready": False,
            "briefing_type": "compliance",
            "conversation_id": "conv-1",
            "turn_id": "turn-1",
            "skill_id": "cumplimiento",
            "skill_version": "builtin-1.0",
            "skill_hash": "abc123",
            "trace_id": "trace-1",
            "agent_tool_calls": [{"tool_name": "get_event_context", "status": "executed"}],
            "agent_skipped_tools": [],
            "agent_route_summary": {"route_mode": "tool_augmented_context", "read_only": True},
            "structured_answer": {"estado_observado": ["Gemini no está configurado todavía."]},
            "answer_validation": {"valid": False, "missing_sections": ["datos_faltantes"]},
            "citation_validation": {"valid": True, "warnings": []},
            "compliance_validation": {"valid": True, "warnings": []},
        },
    )

    response = chatbot_routes.chatbot_assess(
        ChatbotAssessmentRequest(
            selected_context={"equipo_ope": "EQ-1"},
            question="estado",
            briefing_type="compliance",
            question_id="compliance_risk_flags",
        )
    )

    assert response.ready is False
    assert response.briefing_type == "compliance"
    assert response.conversation_id == "conv-1"
    assert response.skill_id == "cumplimiento"
    assert response.skill_hash == "abc123"
    assert response.agent_tool_calls[0]["tool_name"] == "get_event_context"
    assert response.agent_route_summary["read_only"] is True
    assert response.structured_answer["estado_observado"][0].startswith("Gemini")
    assert response.answer_validation["valid"] is False
    assert response.citation_validation["valid"] is True
    assert response.compliance_validation["valid"] is True
    assert "Gemini no está configurado" in response.answer


def test_chatbot_assessment_schema_accepts_conversation_metadata() -> None:
    request = ChatbotAssessmentRequest(
        selected_context={"equipo_ope": "EQ-1"},
        question="estado",
        conversation_id="conv-existing",
    )
    response = ChatbotAssessmentResponse(
        answer="Respuesta",
        citations=[],
        status_text="ok",
        ready=True,
        conversation_id=request.conversation_id,
        turn_id="turn-1",
        skill_id="confiabilidad",
        skill_version="builtin-1.0",
        skill_hash="hash-1",
        trace_id="trace-1",
        agent_tool_calls=[{"tool_name": "search_regulatory_documents", "status": "executed"}],
        agent_skipped_tools=[{"tool_name": "get_asset_context", "skip_reason": "blocked_by_skill_policy"}],
        agent_route_summary={"route_mode": "tool_augmented_retrieval", "read_only": True},
        structured_answer={"estado_observado": ["Respuesta"]},
        answer_validation={"valid": True},
        citation_validation={"valid": True},
        compliance_validation={"valid": True},
    )

    assert response.conversation_id == "conv-existing"
    assert response.trace_id == "trace-1"
    assert response.skill_hash == "hash-1"
    assert response.agent_tool_calls[0]["tool_name"] == "search_regulatory_documents"
    assert response.agent_skipped_tools[0]["skip_reason"] == "blocked_by_skill_policy"
    assert response.structured_answer["estado_observado"] == ["Respuesta"]
    assert response.answer_validation["valid"] is True


def test_chatbot_conversation_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chatbot_routes,
        "create_chatbot_conversation",
        lambda **_: {
            "conversation_id": "conv-1",
            "mode": "guided",
            "briefing_type": "reliability",
            "context_snapshot": {"selected_context": {"equipo_ope": "EQ-1"}},
            "skill_id": "confiabilidad",
            "skill_version": "1.0",
            "skill_hash": "hash-1",
            "llm_provider": "mock",
            "model_endpoint_name": "mock",
            "messages": [],
        },
    )
    monkeypatch.setattr(
        chatbot_routes,
        "get_chatbot_conversation",
        lambda settings, conversation_id: {
            "conversation_id": conversation_id,
            "mode": "guided",
            "briefing_type": "reliability",
            "context_snapshot": {},
            "skill_id": "confiabilidad",
            "skill_version": "1.0",
            "skill_hash": "hash-1",
            "llm_provider": "mock",
            "model_endpoint_name": "mock",
            "messages": [
                {
                    "conversation_id": conversation_id,
                    "turn_id": "turn-1",
                    "role": "assistant",
                    "content": "Respuesta",
                    "briefing_type": "reliability",
                    "citations": [],
                    "retrieved_chunk_ids": [],
                    "skill_id": "confiabilidad",
                    "skill_version": "1.0",
                    "skill_hash": "hash-1",
                    "trace_id": "trace-1",
                    "llm_provider": "mock",
                    "model_endpoint_name": "mock",
                    "ready": True,
                    "agent_tool_calls": [{"tool_name": "get_event_context", "status": "executed"}],
                    "agent_skipped_tools": [],
                    "agent_route_summary": {"route_mode": "tool_augmented_context", "read_only": True},
                    "structured_answer": {"estado_observado": ["Respuesta"]},
                    "answer_validation": {"valid": True},
                    "citation_validation": {"valid": True},
                    "compliance_validation": {"valid": True},
                }
            ],
        },
    )

    created = chatbot_routes.chatbot_create_conversation(
        ChatbotConversationCreateRequest(selected_context={"equipo_ope": "EQ-1"})
    )
    detail = chatbot_routes.chatbot_get_conversation("conv-1")

    assert created.conversation_id == "conv-1"
    assert created.llm_provider == "mock"
    assert detail.messages[0].turn_id == "turn-1"
    assert detail.messages[0].skill_hash == "hash-1"
    assert detail.messages[0].agent_tool_calls[0]["tool_name"] == "get_event_context"
    assert detail.messages[0].structured_answer["estado_observado"] == ["Respuesta"]


def test_chatbot_conversation_get_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chatbot_routes, "get_chatbot_conversation", lambda settings, conversation_id: None)

    with pytest.raises(chatbot_routes.HTTPException) as exc_info:
        chatbot_routes.chatbot_get_conversation("missing")

    assert exc_info.value.status_code == 404


def test_chatbot_send_message_route_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chatbot_routes,
        "send_chatbot_message",
        lambda **_: {
            "answer": "Seguimiento",
            "citations": [],
            "status_text": "ok",
            "ready": True,
            "briefing_type": "reliability",
            "conversation_id": "conv-1",
            "turn_id": "turn-2",
            "skill_id": "confiabilidad",
            "skill_version": "1.0",
            "skill_hash": "hash-1",
            "trace_id": "trace-2",
            "llm_provider": "mock",
            "model_endpoint_name": "mock",
            "agent_tool_calls": [{"tool_name": "search_technical_documents", "status": "executed"}],
            "agent_skipped_tools": [],
            "agent_route_summary": {"route_mode": "tool_augmented_retrieval", "read_only": True},
            "structured_answer": {"estado_observado": ["Seguimiento"]},
            "answer_validation": {"valid": True},
            "citation_validation": {"valid": True},
            "compliance_validation": {"valid": True},
        },
    )

    response = chatbot_routes.chatbot_send_message(
        "conv-1",
        ChatbotConversationMessageRequest(message="Que sigue?"),
    )

    assert response.answer == "Seguimiento"
    assert response.conversation_id == "conv-1"
    assert response.llm_provider == "mock"
    assert response.agent_tool_calls[0]["tool_name"] == "search_technical_documents"
    assert response.structured_answer["estado_observado"] == ["Seguimiento"]
    with pytest.raises(chatbot_routes.HTTPException) as exc_info:
        chatbot_routes.chatbot_send_message("conv-1", ChatbotConversationMessageRequest(message="   "))
    assert exc_info.value.status_code == 400


def test_chatbot_send_message_missing_conversation_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chatbot_routes, "send_chatbot_message", lambda **_: None)

    with pytest.raises(chatbot_routes.HTTPException) as exc_info:
        chatbot_routes.chatbot_send_message("missing", ChatbotConversationMessageRequest(message="hola"))

    assert exc_info.value.status_code == 404


def test_chatbot_feedback_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chatbot_routes,
        "submit_chatbot_feedback",
        lambda **_: {
            "feedback_id": "feedback-1",
            "conversation_id": "conv-1",
            "turn_id": "turn-1",
            "rating": "helpful",
            "comment": None,
            "created_at": "2026-01-01T00:00:00Z",
            "status_text": "Retroalimentación registrada.",
        },
    )

    response = chatbot_routes.chatbot_feedback(
        ChatbotFeedbackRequest(conversation_id="conv-1", turn_id="turn-1", rating="helpful")
    )

    assert response.feedback_id == "feedback-1"
    assert response.rating == "helpful"


def test_chatbot_feedback_route_converts_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_feedback(**_):
        raise ValueError("rating debe ser valido")

    monkeypatch.setattr(chatbot_routes, "submit_chatbot_feedback", fake_feedback)

    with pytest.raises(chatbot_routes.HTTPException) as exc_info:
        chatbot_routes.chatbot_feedback(
            ChatbotFeedbackRequest(conversation_id="conv-1", turn_id="turn-1", rating="helpful")
        )

    assert exc_info.value.status_code == 400


def test_chatbot_skills_status_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chatbot_routes,
        "get_skill_status",
        lambda settings: {
            "skills_available": True,
            "skills_count": 1,
            "skill_errors_count": 1,
            "skills": [
                {
                    "skill_id": "confiabilidad",
                    "version": "1.0",
                    "status": "active",
                    "source_type": "default",
                    "source_path": "skill.yml",
                    "skill_hash": "hash-1",
                    "errors": [],
                }
            ],
            "validation_errors": [
                {
                    "file_name": "cumplimiento.yml",
                    "skill_id": "cumplimiento",
                    "version": "2.0",
                    "status": "active",
                    "source_type": "configured",
                    "source_path": "bad.yml",
                    "skill_hash": "bad-hash",
                    "errors": ["control bloqueado"],
                }
            ],
        },
    )

    response = chatbot_routes.chatbot_skills_status()

    assert isinstance(response, ChatbotSkillStatusResponse)
    assert response.skills_count == 1
    assert response.validation_errors[0].file_name == "cumplimiento.yml"
