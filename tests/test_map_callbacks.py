from __future__ import annotations

from types import SimpleNamespace

import pytest
from dash import no_update

from chec_dashboard.app import create_app
from chec_dashboard.pages import map_page


MAP_CALLBACK_KEY = (
    "..map-folium-frame.srcDoc...map-date-slider.value...map-status-text.children..."
    "map-session-state.data...map-confirm-button.disabled...map-date-slider.disabled..."
    "map-decrease-btn.disabled...map-increase-btn.disabled...map-panel-overlay.style.."
)


def _get_map_callback():
    app = create_app()
    callback = app.callback_map[MAP_CALLBACK_KEY]["callback"]
    return getattr(callback, "__wrapped__", callback)


def _get_circuit_callback():
    app = create_app()
    callback_key = next(
        key
        for key in app.callback_map
        if "map-select-circuit.options" in key
        and "map-select-all-circuits.disabled" in key
    )
    callback = app.callback_map[callback_key]["callback"]
    return getattr(callback, "__wrapped__", callback)


def _circuit_options(*values: str) -> list[dict[str, str]]:
    return [{"label": value, "value": value} for value in values]


def _session_state(**overrides):
    state = map_page._initial_map_session_state()
    state.update(overrides)
    return state


def test_map_ok_with_missing_filters_returns_visible_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _get_map_callback()
    monkeypatch.setattr(map_page, "ctx", SimpleNamespace(triggered_id="map-confirm-button"))

    result = callback(
        1,
        0,
        0,
        1,
        None,
        None,
        [],
        [],
        "BASE",
        1,
        31,
        _session_state(),
    )

    assert result[0] is no_update
    assert "Selecciona una fecha y un municipio" in result[2]
    assert result[4] is False
    assert result[5] is True
    assert result[6] is True
    assert result[7] is True
    assert result[8]["display"] == "none"


def test_map_ok_retries_transient_failure_then_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _get_map_callback()
    monkeypatch.setattr(map_page, "ctx", SimpleNamespace(triggered_id="map-confirm-button"))
    monkeypatch.setattr(map_page.time, "sleep", lambda *_: None)

    calls = {"count": 0}

    def fake_fetch_map_render(
        *,
        selected_period: str,
        selected_municipio: str,
        selected_circuits: list[str] | None,
        selected_output: str | None,
        day: int,
    ):
        _ = selected_period
        _ = selected_municipio
        assert selected_circuits is None
        _ = selected_output
        _ = day
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("API request failed: Transient API status 503")
        return {
            "map_html": "<html>ok-map</html>",
            "current_day": 1,
        }

    monkeypatch.setattr(map_page, "fetch_map_render", fake_fetch_map_render)

    result = callback(
        1,
        0,
        0,
        1,
        "2024-01",
        "Manizales",
        ["CKT-1", "CKT-2"],
        _circuit_options("CKT-1", "CKT-2"),
        "BASE",
        1,
        31,
        _session_state(),
    )

    assert calls["count"] == 2
    assert result[0] == "<html>ok-map</html>"
    assert "reintento (2/3)" in result[2]
    assert result[5] is False
    assert result[6] is False
    assert result[7] is False
    assert result[8]["display"] == "none"


def test_map_ok_repeated_transient_failure_keeps_previous_map(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _get_map_callback()
    monkeypatch.setattr(map_page, "ctx", SimpleNamespace(triggered_id="map-confirm-button"))
    monkeypatch.setattr(map_page.time, "sleep", lambda *_: None)

    def always_transient_failure(
        *,
        selected_period: str,
        selected_municipio: str,
        selected_circuits: list[str] | None,
        selected_output: str | None,
        day: int,
    ):
        _ = selected_period
        _ = selected_municipio
        assert selected_circuits is None
        _ = selected_output
        _ = day
        raise RuntimeError("API request failed: Transient API status 503")

    monkeypatch.setattr(map_page, "fetch_map_render", always_transient_failure)

    result = callback(
        2,
        0,
        0,
        1,
        "2024-01",
        "Manizales",
        ["CKT-1", "CKT-2"],
        _circuit_options("CKT-1", "CKT-2"),
        "BASE",
        1,
        31,
        _session_state(
            has_successful_render=True,
            current_day=5,
            selected_date="2023-12",
            selected_municipio="Villamaria",
            selected_circuits=["CKT-1", "CKT-2"],
            last_successful_render={
                "selected_date": "2023-12",
                "selected_municipio": "Villamaria",
                "selected_circuits": ["CKT-1", "CKT-2"],
                "current_day": 5,
            },
        ),
    )

    assert result[0] is no_update
    assert "No se pudo renderizar el mapa tras 3 intentos" in result[2]
    assert result[3]["has_successful_render"] is True
    assert result[5] is False
    assert result[6] is False
    assert result[7] is False
    assert result[8]["display"] == "none"


def test_map_confirm_click_not_globally_suppressed_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _get_map_callback()
    monkeypatch.setattr(map_page, "ctx", SimpleNamespace(triggered_id="map-confirm-button"))

    calls = {"count": 0}

    def fake_fetch_map_render(
        *,
        selected_period: str,
        selected_municipio: str,
        selected_circuits: list[str] | None,
        selected_output: str | None,
        day: int,
    ):
        calls["count"] += 1
        circuit_label = "Todos" if selected_circuits is None else ",".join(selected_circuits)
        return {
            "map_html": (
                f"<html>{selected_period}-{selected_municipio}-{circuit_label}-{selected_output}-d{day}</html>"
            ),
            "current_day": day,
        }

    monkeypatch.setattr(map_page, "fetch_map_render", fake_fetch_map_render)

    first = callback(
        1,
        0,
        0,
        1,
        "2024-01",
        "Manizales",
        ["CKT-1", "CKT-2"],
        _circuit_options("CKT-1", "CKT-2"),
        "BASE",
        1,
        31,
        _session_state(),
    )
    second = callback(
        1,
        0,
        0,
        1,
        "2024-02",
        "Neira",
        ["Circuito 7"],
        _circuit_options("Circuito 7", "Circuito 8"),
        "BASE",
        1,
        31,
        first[3],
    )

    assert calls["count"] == 2
    assert first[0] == "<html>2024-01-Manizales-Todos-BASE-d1</html>"
    assert second[0] == "<html>2024-02-Neira-Circuito 7-BASE-d1</html>"


def test_map_slider_boundary_click_shows_visible_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _get_map_callback()
    monkeypatch.setattr(map_page, "ctx", SimpleNamespace(triggered_id="map-increase-btn"))

    result = callback(
        0,
        0,
        1,
        31,
        "2024-01",
        "Manizales",
        ["CKT-1", "CKT-2"],
        _circuit_options("CKT-1", "CKT-2"),
        "BASE",
        1,
        31,
        _session_state(
            has_successful_render=True,
            current_day=31,
            selected_date="2024-01",
            selected_municipio="Manizales",
            selected_circuits=["CKT-1", "CKT-2"],
            last_successful_render={
                "selected_date": "2024-01",
                "selected_municipio": "Manizales",
                "selected_circuits": ["CKT-1", "CKT-2"],
                "current_day": 31,
            },
        ),
    )

    assert result[0] is no_update
    assert "Ya estás en el límite del rango" in result[2]
    assert result[1] == 31


def test_map_circuit_options_selects_all_real_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _get_circuit_callback()
    monkeypatch.setattr(map_page, "ctx", SimpleNamespace(triggered_id="map-select-date"))
    monkeypatch.setattr(
        map_page,
        "fetch_map_circuit_options",
        lambda **_: {
            "circuits": ["Todos", "CKT-1", "CKT-2"],
            "outputs": ["BASE"],
            "default_output": "BASE",
        },
    )

    result = callback(
        "2024-01",
        "Manizales",
        0,
        0,
        [],
        _session_state(),
    )

    assert result[0] == _circuit_options("CKT-1", "CKT-2")
    assert result[1] == ["CKT-1", "CKT-2"]
    assert result[4] is False
    assert result[5] is False
    assert "todos los circuitos seleccionados" in result[6]
    assert result[7]["selected_circuits"] == ["CKT-1", "CKT-2"]


def test_map_circuit_buttons_select_all_and_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    callback = _get_circuit_callback()
    options = _circuit_options("CKT-1", "CKT-2")

    monkeypatch.setattr(map_page, "ctx", SimpleNamespace(triggered_id="map-clear-circuits"))
    cleared = callback(
        "2024-01",
        "Manizales",
        0,
        1,
        options,
        _session_state(selected_circuits=["CKT-1", "CKT-2"]),
    )

    assert cleared[1] == []
    assert "Selección limpia" in cleared[6]
    assert cleared[7]["selected_circuits"] == []

    monkeypatch.setattr(map_page, "ctx", SimpleNamespace(triggered_id="map-select-all-circuits"))
    selected = callback(
        "2024-01",
        "Manizales",
        1,
        1,
        options,
        cleared[7],
    )

    assert selected[1] == ["CKT-1", "CKT-2"]
    assert "Todos los circuitos" in selected[6]
    assert selected[7]["selected_circuits"] == ["CKT-1", "CKT-2"]
