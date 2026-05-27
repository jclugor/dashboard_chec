from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from chec_dashboard.api.main import create_api_app


@pytest.fixture()
def client() -> TestClient:
    with TestClient(create_api_app()) as test_client:
        yield test_client


def test_chatbot_status_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.chatbot.get_chatbot_status",
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

    response = client.get("/chatbot/status")

    assert response.status_code == 200
    assert response.json()["chunks_count"] == 5
    assert response.json()["ready"] is False


def test_chatbot_context_options_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.chatbot.get_chatbot_context_options",
        lambda **_: {
            "items": [
                {
                    "id": "event-1",
                    "label": "EQ-1 | CKT-1",
                    "kind": "event",
                    "summary": "Evento de prueba",
                    "context": {"equipo_ope": "EQ-1"},
                }
            ],
            "status_text": "Se encontraron 1 eventos.",
        },
    )

    response = client.post(
        "/chatbot/context-options",
        json={
            "context_kind": "event",
            "selected_period": "2024-01",
            "selected_municipio": "Manizales",
            "selected_circuits": ["CKT-1"],
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "event-1"


def test_chatbot_assess_route_unconfigured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.chatbot.assess_chatbot_context",
        lambda **_: {
            "answer": "Gemini no está configurado todavía.",
            "citations": [],
            "status_text": "Gemini no está configurado.",
            "ready": False,
        },
    )

    response = client.post(
        "/chatbot/assess",
        json={"selected_context": {"equipo_ope": "EQ-1"}, "question": "estado"},
    )

    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert "Gemini no está configurado" in response.json()["answer"]
