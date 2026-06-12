from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from dash import dcc

from chec_dashboard.app import create_app
from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.dash_app import api_client
from chec_dashboard.dash_app import callbacks
from chec_dashboard.dash_app.api_client import StartupStatus
from chec_dashboard.dash_app.layout import build_dash_layout
from chec_dashboard.pages import map_page, probability_page, summary_page


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "chec_dashboard"


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


def _find_by_id(component, component_id: str):
    for item in _walk(component):
        if getattr(item, "id", None) == component_id:
            return item
    return None


def _all_text(component) -> str:
    return "\n".join(item for item in _walk(component) if isinstance(item, str))


def test_initial_dash_layout_does_not_call_api(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("initial layout should not load map API options")

    monkeypatch.setattr(map_page, "fetch_map_options", fail_if_called)

    layout = build_dash_layout(base_settings)

    assert _find_by_id(layout, "api-startup-interval") is not None
    assert _find_by_id(layout, "api-heartbeat-interval") is not None
    assert _find_by_id(layout, "api-startup-state") is not None
    assert _find_by_id(layout, "nav-button-map").disabled is True


def test_map_layout_does_not_call_api_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("map layout should load API options lazily")

    monkeypatch.setattr(map_page, "fetch_map_options", fail_if_called)

    layout = map_page.get_layout(base_settings)

    assert _find_by_id(layout, "map-options-load-interval") is not None
    assert _find_by_id(layout, "map-select-date").options == []
    assert _find_by_id(layout, "map-select-municipio").options == []


def test_summary_layout_does_not_call_api_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("summary layout should load API options lazily")

    monkeypatch.setattr(summary_page, "fetch_summary_options", fail_if_called)
    monkeypatch.setattr(summary_page, "fetch_summary_data", fail_if_called)

    layout = summary_page.get_layout(base_settings)

    assert _find_by_id(layout, "summary-initial-load-interval") is not None
    assert _find_by_id(layout, "summary-circuit").options == []
    assert _find_by_id(layout, "summary-event") is None
    assert _find_by_id(layout, "summary-date-window").start_date is None
    assert _find_by_id(layout, "summary-interpretability-store") is not None
    assert _find_by_id(layout, "summary-interpretability-button") is not None
    assert _find_by_id(layout, "summary-interpretability-panel") is not None


def test_summary_interpretability_markers_are_added_to_existing_chart() -> None:
    daily = pd.DataFrame(
        {
            "fecha_dia": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "UITI": [0.2, 5.0],
            "UITI_VANO": [0.1, 0.2],
        }
    )
    figure = summary_page._build_line_figure(daily, "UITI")
    payload = {
        "critical_points": [
            {
                "fecha_dia": "2024-01-02",
                "rank": 1,
                "metrics": {"UITI": 5.0, "UITI_VANO": 0.2},
                "criticality_types": ["uiti_high_outlier"],
                "confidence": "high",
            }
        ]
    }

    marked = summary_page._apply_interpretability_markers(figure, payload, "UITI")

    assert len(marked.data) == 2
    assert marked.data[1].name == "Puntos criticos UITI"


def test_probability_layout_does_not_call_api_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("probability layout should load API options lazily")

    monkeypatch.setattr(probability_page, "fetch_probability_options", fail_if_called)

    layout = probability_page.get_layout()

    assert _find_by_id(layout, "prob-options-load-interval") is not None
    assert _find_by_id(layout, "prob-select-criteria").options == []
    assert _find_by_id(layout, "prob-select-criteria").disabled is True


def test_dashboard_app_copy_is_spanish_and_accented() -> None:
    summary_layout = summary_page.get_layout(base_settings)
    probability_layout_component = probability_page.get_layout()
    map_layout_component = map_page.get_layout(base_settings)

    assert "MÉTRICA" not in _all_text(summary_layout)
    assert "Total UITI" in _all_text(summary_layout)
    assert "Resumen rápido de impacto por circuito" in _all_text(summary_layout)
    assert _find_by_id(summary_layout, "summary-metric-mode") is None
    assert summary_page.DEFAULT_SUMMARY_METRIC_KEY == "UITI"
    assert "Generando gráfica..." in _all_text(probability_layout_component)
    assert "SALIDA" in _all_text(map_layout_component)
    assert _find_by_id(map_layout_component, "map-select-output").options == [{"label": "Base", "value": "BASE"}]


def test_dashboard_source_uses_dm_sans_only() -> None:
    matches = []
    for path in SOURCE_ROOT.rglob("*"):
        if path.suffix not in {".py", ".css"}:
            continue
        if "Poppins" in path.read_text(encoding="utf-8"):
            matches.append(str(path.relative_to(SOURCE_ROOT)))

    assert matches == []


def test_startup_intervals_use_configured_defaults() -> None:
    layout = build_dash_layout(base_settings)
    startup_interval = _find_by_id(layout, "api-startup-interval")
    heartbeat_interval = _find_by_id(layout, "api-heartbeat-interval")

    assert isinstance(startup_interval, dcc.Interval)
    assert startup_interval.interval == base_settings.api_startup_poll_seconds * 1000
    assert startup_interval.disabled is False
    assert heartbeat_interval.interval == base_settings.api_keepalive_seconds * 1000
    assert heartbeat_interval.disabled is True


def test_create_app_sets_viewport_meta_tag() -> None:
    app = create_app()
    meta_tags = app.config.get("meta_tags", [])

    assert any(
        tag.get("name") == "viewport"
        and tag.get("content") == "width=device-width, initial-scale=1"
        for tag in meta_tags
    )


def test_check_api_ready_treats_connection_failure_as_warming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_client,
        "_request_json_no_raise",
        lambda *_, **__: (None, None, "connection failed"),
    )

    status = api_client.check_api_ready()

    assert status.status == "warming"
    assert status.ready is False
    assert "connection failed" in status.message


def test_check_api_ready_treats_azure_503_without_payload_as_warming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_client,
        "_request_json_no_raise",
        lambda *_, **__: (503, {}, None),
    )

    status = api_client.check_api_ready()

    assert status.status == "warming"


def test_check_api_ready_reports_missing_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_client,
        "_request_json_no_raise",
        lambda *_, **__: (
            503,
            {
                "ready": False,
                "checks": {
                    "data": {
                        "ok": False,
                        "message": "Missing required data files: TRAFOS.pkl",
                    }
                },
            },
            None,
        ),
    )

    status = api_client.check_api_ready()

    assert status.status == "data_unavailable"
    assert "TRAFOS.pkl" in status.message


def test_check_api_ready_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_client,
        "_request_json_no_raise",
        lambda *_, **__: (200, {"ready": True}, None),
    )

    status = api_client.check_api_ready()

    assert status.ready is True


def test_warm_api_metadata_treats_transient_status_as_warming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_client,
        "_request_json_no_raise",
        lambda *_, **__: (502, {}, None),
    )

    status = api_client.warm_api_metadata()

    assert status.status == "warming"


def test_startup_status_skips_warmup_when_api_is_still_starting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        callbacks,
        "check_api_ready",
        lambda: StartupStatus("warming", "starting"),
    )
    monkeypatch.setattr(
        callbacks,
        "warm_api_metadata",
        lambda: pytest.fail("warmup should not run before readiness succeeds"),
    )

    status = callbacks._startup_status(base_settings)

    assert status.status == "warming"


def test_startup_status_warms_metadata_after_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        callbacks,
        "check_api_ready",
        lambda: StartupStatus("ready", "ready"),
    )
    monkeypatch.setattr(
        callbacks,
        "warm_api_metadata",
        lambda: StartupStatus("ready", "warm"),
    )

    status = callbacks._startup_status(base_settings)

    assert status.ready is True


def test_fetch_map_render_retries_transient_503(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    class _Response:
        def __init__(self, status_code: int, payload: dict[str, object]):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError("raise_for_status should not be called for transient status")

    class _Client:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def request(self, *_, **__):
            calls["count"] += 1
            if calls["count"] == 1:
                return _Response(503, {})
            return _Response(200, {"map": {"map_html": "<html></html>", "current_day": 1, "status_text": "ok"}})

    monkeypatch.setattr(api_client.httpx, "Client", _Client)
    monkeypatch.setattr(api_client.time, "sleep", lambda *_: None)

    payload = api_client.fetch_map_render("2024-01", "Manizales", 1)

    assert calls["count"] == 2
    assert payload["map_html"] == "<html></html>"
