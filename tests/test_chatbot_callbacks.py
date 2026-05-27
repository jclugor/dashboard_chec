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
