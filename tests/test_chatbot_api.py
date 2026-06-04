from __future__ import annotations

import pytest

from chec_dashboard.api.routes import chatbot as chatbot_routes
from chec_dashboard.api.schemas.chatbot import (
    ChatbotAssessmentRequest,
    ChatbotAssessmentResponse,
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
    )

    assert response.conversation_id == "conv-existing"
    assert response.trace_id == "trace-1"
    assert response.skill_hash == "hash-1"


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
