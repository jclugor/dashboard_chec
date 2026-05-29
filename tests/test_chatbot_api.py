from __future__ import annotations

import pytest

from chec_dashboard.api.routes import chatbot as chatbot_routes
from chec_dashboard.api.schemas.chatbot import ChatbotAssessmentRequest, ChatbotContextOptionsRequest


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
            "gemini_configured": False,
            "corpus_available": True,
            "ready": False,
            "documents_count": 2,
            "chunks_count": 5,
            "message": "Gemini no está configurado.",
        },
    )

    response = chatbot_routes.chatbot_status()

    assert response.chunks_count == 5
    assert response.ready is False


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
    assert "Gemini no está configurado" in response.answer
