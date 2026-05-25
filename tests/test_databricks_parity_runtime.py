from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from chec_dashboard.app import create_app
from chec_dashboard.api.main import create_api_app
from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.dash_app import api_client


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
            "metric_mode": "BOTH",
            "saidi_total": 1.0,
            "saifi_total": 2.0,
            "event_count": 3,
            "daily_data": [],
            "status_text": "ok",
        },
    )

    payload = api_client.fetch_summary_data("2024-01-01", "2024-01-31", "CIR-1", "BOTH")

    assert payload["event_count"] == 3
    assert payload["status_text"] == "ok"


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


def test_fastapi_ready_uses_databricks_readiness_when_backend_selected(monkeypatch) -> None:
    mock_settings = replace(base_settings, data_backend="databricks_sql")
    monkeypatch.setattr("chec_dashboard.api.routes.health.settings", mock_settings)
    monkeypatch.setattr(
        "chec_dashboard.api.routes.health.databricks_data_readiness_check",
        lambda *_: (True, "Databricks data backend ready"),
    )

    client = TestClient(create_api_app())
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["data"]["message"] == "Databricks data backend ready"
