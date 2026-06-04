from __future__ import annotations

from types import SimpleNamespace

from dash import dcc
import pytest

from chec_dashboard.app import create_app
from chec_dashboard.dash_app import callbacks as root_callbacks
from chec_dashboard.pages import chatbot_page


def _callback_with_output(output_fragment: str):
    app = create_app()
    callback_key = next(key for key in app.callback_map if output_fragment in key)
    callback = app.callback_map[callback_key]["callback"]
    return getattr(callback, "__wrapped__", callback)


def _walk(component):
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if isinstance(children, list):
        for child in children:
            if child is not None:
                yield from _walk(child)
    else:
        yield from _walk(children)


def _all_text(component) -> str:
    return "\n".join(item for item in _walk(component) if isinstance(item, str))


def test_chatbot_tab_navigation(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _callback_with_output("nav-button-chat.style")
    monkeypatch.setattr(root_callbacks, "ctx", SimpleNamespace(triggered_id="nav-button-chat"))

    result = callback(0, 0, 0, 1, {"status": "ready"})

    assert "Asistente técnico" in _all_text(result[0])
    assert result[4]["backgroundColor"] == "#01471998"


def test_chatbot_search_context_callback_preserves_items(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _callback_with_output("chatbot-context-select.options")
    monkeypatch.setattr(
        chatbot_page,
        "fetch_chatbot_context_options",
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

    result = callback(1, "event", "2024-01", "Manizales", ["CKT-1"], "")

    assert result[0] == [{"label": "EQ-1 | CKT-1", "value": "event-1"}]
    assert result[1] == "event-1"
    assert result[2] is False
    assert result[3][0]["context"]["equipo_ope"] == "EQ-1"


def test_chatbot_guided_questions_switch_by_analysis_type() -> None:
    callback = _callback_with_output("chatbot-question-id.options")

    result = callback("maintenance")

    assert result[1] == "maintenance_field_checks"
    assert any("revisión de campo" in option["label"] for option in result[0])


def test_chatbot_select_context_summary_returns_store() -> None:
    callback = _callback_with_output("chatbot-context-summary.children")
    result = callback(
        "event-1",
        [
            {
                "id": "event-1",
                "label": "EQ-1",
                "kind": "event",
                "summary": "Evento con SAIDI alto",
                "context": {"equipo_ope": "EQ-1", "cto_equi_ope": "CKT-1", "SAIDI": 0.5},
            }
        ],
    )

    assert result[1]["equipo_ope"] == "EQ-1"
    assert "Evento con SAIDI alto" in _all_text(result[0])


def test_chatbot_assessment_callback_renders_spanish_message(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _callback_with_output("chatbot-answer.children")
    monkeypatch.setattr(
        chatbot_page,
        "fetch_chatbot_assessment",
        lambda **_: {
            "answer": "Gemini no está configurado todavía.",
            "citations": [],
            "status_text": "Gemini no está configurado.",
            "ready": False,
        },
    )

    result = callback(1, {"equipo_ope": "EQ-1"}, "estado")

    assert isinstance(result[0], dcc.Markdown)
    assert "Gemini no está configurado" in result[0].children
    assert result[2] == "Gemini no está configurado."


def test_chatbot_assessment_callback_stores_conversation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _callback_with_output("chatbot-answer.children")
    monkeypatch.setattr(
        chatbot_page,
        "fetch_chatbot_assessment",
        lambda **_: {
            "answer": "Respuesta guiada.",
            "citations": [],
            "status_text": "ok",
            "ready": True,
            "conversation_id": "conv-1",
            "agent_tool_calls": [{"tool_name": "get_event_context", "status": "executed", "evidence_count": 1}],
            "agent_skipped_tools": [],
            "agent_route_summary": {"route_mode": "tool_augmented_context", "route_reason": "Evento gobernado"},
        },
    )
    monkeypatch.setattr(
        chatbot_page,
        "fetch_chatbot_conversation",
        lambda conversation_id: {
            "conversation_id": conversation_id,
            "messages": [
                {
                    "conversation_id": conversation_id,
                    "turn_id": "turn-1",
                    "role": "assistant",
                    "content": "Respuesta guiada.",
                    "skill_id": "confiabilidad",
                    "skill_version": "1.0",
                    "skill_hash": "hash-1",
                    "trace_id": "trace-1",
                    "agent_tool_calls": [
                        {
                            "tool_name": "get_event_context",
                            "status": "executed",
                            "reason": "Evento gobernado",
                            "evidence_count": 1,
                            "context_id": "event-1",
                        }
                    ],
                    "agent_skipped_tools": [],
                    "agent_route_summary": {
                        "route_mode": "tool_augmented_context",
                        "route_reason": "Evento gobernado",
                    },
                }
            ],
        },
    )

    result = callback(1, {"equipo_ope": "EQ-1"}, "estado")

    assert result[3] == "conv-1"
    assert result[4]["conversation_id"] == "conv-1"
    assert result[6]["turn_id"] == "turn-1"
    assert "Respuesta guiada" in _all_text(result[5])
    assert "get_event_context" in _all_text(result[8])


def test_chatbot_followup_callback_sends_existing_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _callback_with_output("chatbot-followup-input.value")
    calls: dict[str, object] = {}

    def fake_message(**kwargs):
        calls.update(kwargs)
        return {"status_text": "Respuesta de seguimiento generada."}

    monkeypatch.setattr(chatbot_page, "fetch_chatbot_message", fake_message)
    monkeypatch.setattr(
        chatbot_page,
        "fetch_chatbot_conversation",
        lambda conversation_id: {
            "conversation_id": conversation_id,
            "messages": [
                {
                    "conversation_id": conversation_id,
                    "turn_id": "turn-2",
                    "role": "assistant",
                    "content": "Seguimiento.",
                    "agent_tool_calls": [
                        {
                            "tool_name": "search_technical_documents",
                            "status": "executed",
                            "reason": "Documentos tecnicos",
                            "evidence_count": 2,
                            "context_id": "retrieval-1",
                        }
                    ],
                }
            ],
        },
    )

    result = callback(
        1,
        "conv-1",
        {"conversation_id": "conv-1", "messages": []},
        {"equipo_ope": "EQ-1"},
        "  Que sigue?  ",
        "maintenance",
    )

    assert calls["conversation_id"] == "conv-1"
    assert calls["message"] == "Que sigue?"
    assert calls["selected_context"] == {"equipo_ope": "EQ-1"}
    assert result[2] == "Respuesta de seguimiento generada."
    assert result[3] == ""
    assert result[4]["turn_id"] == "turn-2"
    assert "search_technical_documents" in _all_text(result[6])


def test_chatbot_followup_callback_creates_free_form_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _callback_with_output("chatbot-followup-input.value")
    created: dict[str, object] = {}

    def fake_create(**kwargs):
        created.update(kwargs)
        return {"conversation_id": "conv-created"}

    monkeypatch.setattr(chatbot_page, "fetch_chatbot_create_conversation", fake_create)
    monkeypatch.setattr(
        chatbot_page,
        "fetch_chatbot_message",
        lambda **_: {"status_text": "Respuesta de seguimiento generada."},
    )
    monkeypatch.setattr(
        chatbot_page,
        "fetch_chatbot_conversation",
        lambda conversation_id: {"conversation_id": conversation_id, "messages": []},
    )

    result = callback(1, None, {}, {"equipo_ope": "EQ-1"}, "Nueva pregunta", "reliability")

    assert created["mode"] == "free_form"
    assert created["selected_context"] == {"equipo_ope": "EQ-1"}
    assert result[5] == "conv-created"


def test_chatbot_feedback_callback_calls_feedback_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _callback_with_output("chatbot-feedback-status.children")
    calls: dict[str, object] = {}

    def fake_feedback(**kwargs):
        calls.update(kwargs)
        return {"status_text": "Retroalimentación registrada."}

    monkeypatch.setattr(chatbot_page, "ctx", SimpleNamespace(triggered_id="chatbot-feedback-not-helpful"))
    monkeypatch.setattr(chatbot_page, "fetch_chatbot_feedback", fake_feedback)

    result = callback(0, 1, "conv-1", {"turn_id": "turn-1"})

    assert calls == {
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "rating": "not_helpful",
    }
    assert result == "Retroalimentación registrada."
