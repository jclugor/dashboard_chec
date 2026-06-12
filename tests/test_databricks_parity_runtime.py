from __future__ import annotations

from dataclasses import replace

from fastapi import Response

from chec_dashboard.app import create_app
from chec_dashboard.api.routes import health as health_routes
from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.dash_app import api_client
from chec_dashboard.services.databricks_sql import sql_literal


def test_sql_literal_escapes_quotes_and_backslashes_for_json_payloads() -> None:
    literal = sql_literal('{"text": "usa \\"comillas\\" y O\'Brien"}')

    assert literal.startswith("'")
    assert literal.endswith("'")
    assert "\\\\\"" in literal
    assert "O''Brien" in literal


def test_fetch_summary_data_inproc_uses_local_provider(
    monkeypatch,
) -> None:
    monkeypatch.setattr(api_client, "_use_inproc_transport", lambda: True)
    monkeypatch.setattr(
        api_client,
        "get_summary_payload",
        lambda **_: {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "circuit_label": "CIR-1",
            "metric_key": "UITI",
            "metric_totals": {"UITI": 1.0, "UITI_VANO": 2.0, "EVENT_COUNT": 3.0, "USERS": 0.0, "DURATION_RAW": 0.0},
            "event_count": 3,
            "daily_data": [],
            "status_text": "ok",
        },
    )

    payload = api_client.fetch_summary_data("2024-01-01", "2024-01-31", "CIR-1", "UITI")

    assert payload["event_count"] == 3
    assert payload["status_text"] == "ok"


def test_fetch_summary_event_options_inproc_forwards_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(api_client, "_use_inproc_transport", lambda: True)

    def fake_summary_event_options(**kwargs):
        captured.update(kwargs)
        return {
            "events": [{"event_id": "evt-1", "label": "evt-1"}],
            "default_event_id": None,
            "status_text": "ok",
        }

    monkeypatch.setattr(api_client, "get_summary_event_options", fake_summary_event_options)

    payload = api_client.fetch_summary_event_options("2024-01-01", "2024-01-31", "CIR-1", limit=15)

    assert payload["events"][0]["event_id"] == "evt-1"
    assert captured["start_date_raw"] == "2024-01-01"
    assert captured["circuito"] == "CIR-1"
    assert captured["limit"] == 15


def test_fetch_summary_interpretability_inproc_uses_local_provider(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(api_client, "_use_inproc_transport", lambda: True)
    monkeypatch.setattr(
        api_client,
        "get_summary_interpretability_payload",
        lambda **kwargs: captured.update(kwargs) or {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "circuit_label": "CIR-1",
            "metric_key": "UITI",
            "generated_at": "2026-06-04T00:00:00Z",
            "critical_points": [],
            "critical_periods": [],
            "insight_text": "ok",
            "corpus_citations": [],
            "status_text": "ok",
        },
    )

    payload = api_client.fetch_summary_interpretability(
        "2024-01-01",
        "2024-01-31",
        "CIR-1",
        "UITI",
        include_agent_text=False,
        selected_event_id="evt-1",
    )

    assert payload["insight_text"] == "ok"
    assert captured["selected_event_id"] == "evt-1"


def test_check_api_ready_inproc_uses_dashboard_metadata(monkeypatch) -> None:
    monkeypatch.setattr(api_client, "_use_inproc_transport", lambda: True)
    monkeypatch.setattr(
        api_client,
        "get_dashboard_metadata",
        lambda *_: {"summary": {}, "map": {}, "probability": {}},
    )

    status = api_client.check_api_ready()

    assert status.ready is True
    assert status.status == "ready"


def test_dash_server_exposes_local_data_contract(monkeypatch) -> None:
    app_settings = replace(base_settings, api_transport="inproc")
    monkeypatch.setattr("chec_dashboard.app.settings", app_settings)
    monkeypatch.setattr(
        "chec_dashboard.dash_app.callbacks.get_map_metadata",
        lambda *_: {
            "action": None,
            "dates": [],
            "municipios": [],
            "default_date": None,
            "default_municipio": None,
            "circuits": [],
            "default_circuit": None,
            "outputs": [],
            "default_output": None,
        },
    )
    monkeypatch.setattr(
        "chec_dashboard.dash_app.callbacks.get_summary_metadata",
        lambda *_: {
            "circuits": ["CIR-1"],
            "default_circuit": "CIR-1",
            "min_date": "2024-01-01",
            "max_date": "2024-01-31",
            "default_start": "2024-01-01",
            "default_end": "2024-01-31",
        },
    )
    monkeypatch.setattr(
        "chec_dashboard.dash_app.callbacks.get_probability_metadata",
        lambda *_: {
            "action": "criteria",
            "criteria_options": [{"label": "Eventos Interruptor", "value": "Eventos Interruptor"}],
            "columns": [],
            "filter_kind": None,
            "value_options": [],
            "is_empty": False,
            "message": None,
        },
    )

    app = create_app()
    client = app.server.test_client()
    response = client.get("/data?section=summary")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["summary"]["default_circuit"] == "CIR-1"


def test_dash_server_exposes_summary_interpretability_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}
    app_settings = replace(base_settings, api_transport="inproc")
    monkeypatch.setattr("chec_dashboard.app.settings", app_settings)

    def fake_summary_interpretability_payload(**kwargs):
        captured.update(kwargs)
        return {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "circuit_label": "CIR-1",
            "metric_key": kwargs["metric_key"],
            "generated_at": "2026-06-04T00:00:00Z",
            "critical_points": [],
            "critical_periods": [],
            "insight_text": "ok",
            "corpus_citations": [],
            "status_text": "ok",
        }

    monkeypatch.setattr(
        "chec_dashboard.dash_app.callbacks.get_summary_interpretability_payload",
        fake_summary_interpretability_payload,
    )

    app = create_app()
    client = app.server.test_client()
    response = client.post(
        "/data",
        json={
            "mode": "summary_interpretability",
            "summary_interpretability": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "circuito": "CIR-1",
                "metric_key": "UITI",
                "max_points": 5,
                "include_agent_text": True,
                "selected_date": "2024-01-03",
                "selected_event_id": "evt-1",
            },
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["mode"] == "summary_interpretability"
    assert payload["summary_interpretability"]["metric_key"] == "UITI"
    assert captured["metric_key"] == "UITI"
    assert captured["include_agent_text"] is True
    assert captured["selected_date"] == "2024-01-03"
    assert captured["selected_event_id"] == "evt-1"


def test_dash_server_exposes_summary_event_options_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}
    app_settings = replace(base_settings, api_transport="inproc")
    monkeypatch.setattr("chec_dashboard.app.settings", app_settings)

    def fake_summary_event_options(**kwargs):
        captured.update(kwargs)
        return {
            "events": [{"event_id": "evt-1", "label": "evt-1"}],
            "default_event_id": None,
            "status_text": "ok",
        }

    monkeypatch.setattr(
        "chec_dashboard.dash_app.callbacks.get_summary_event_options",
        fake_summary_event_options,
    )

    app = create_app()
    client = app.server.test_client()
    response = client.post(
        "/data",
        json={
            "mode": "summary_event_options",
            "summary_event_options": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "circuito": "CIR-1",
                "limit": 15,
            },
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["mode"] == "summary_event_options"
    assert payload["summary_event_options"]["events"][0]["event_id"] == "evt-1"
    assert captured["circuito"] == "CIR-1"
    assert captured["limit"] == 15


def test_fastapi_ready_uses_databricks_readiness_when_backend_selected(monkeypatch) -> None:
    mock_settings = replace(base_settings, data_backend="databricks_sql")
    monkeypatch.setattr(health_routes, "settings", mock_settings)
    monkeypatch.setattr(
        health_routes,
        "databricks_data_readiness_check",
        lambda *_: (True, "Databricks data backend ready"),
    )

    response = Response()
    payload = health_routes.readiness(response)

    assert response.status_code == 200
    assert payload.checks["data"].message == "Databricks data backend ready"
