from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from chec_dashboard.api.main import create_api_app
from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.services.inference_service import (
    InferenceBackendRequestError,
    InferenceTimeoutError,
)


@pytest.fixture()
def client() -> TestClient:
    app = create_api_app()
    with TestClient(app) as test_client:
        yield test_client


class _FakeInferenceService:
    def __init__(self, exc: Exception | None = None):
        self._exc = exc

    def predict(self, features, context, *, request_id):
        if self._exc:
            raise self._exc
        return type(
            "Result",
            (),
            {
                "request_id": request_id,
                "backend": "mock",
                "prediction": 0.6,
                "label": "high_risk",
                "model_version": "mock-v1",
                "raw_response": {"features": features, "context": context},
            },
        )



def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert "environment" in payload
    assert "model_backend" in payload
    assert "cache_enabled" in payload



def test_ready_endpoint_contract(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code in {200, 503}

    payload = response.json()
    assert "ready" in payload
    assert "checks" in payload
    assert "data" in payload["checks"]
    assert "backend" in payload["checks"]



def test_inference_mock_backend(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    mock_settings = replace(base_settings, model_backend="mock")
    monkeypatch.setattr("chec_dashboard.api.routes.inference.settings", mock_settings)

    response = client.post(
        "/inference",
        json={"features": {"x": 10, "y": 30}, "context": {"request_id": "abc"}},
        headers={"X-Request-ID": "test-request-id"},
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["backend"] == "mock"
    assert isinstance(payload["prediction"], float)
    assert payload["model_version"] == "mock-v1"
    assert payload["request_id"] == "test-request-id"
    assert response.headers["X-Request-ID"] == "test-request-id"



def test_inference_validation_error(client: TestClient) -> None:
    response = client.post("/inference", json={})
    assert response.status_code == 422



def test_inference_timeout_mapping(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.inference.get_inference_service",
        lambda *_: _FakeInferenceService(exc=InferenceTimeoutError("timeout")),
    )

    response = client.post("/inference", json={"features": {"x": 1}, "context": {}})
    assert response.status_code == 504
    assert response.json()["error_type"] == "inference_timeout"



def test_inference_backend_error_mapping(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.inference.get_inference_service",
        lambda *_: _FakeInferenceService(exc=InferenceBackendRequestError("backend down")),
    )

    response = client.post("/inference", json={"features": {"x": 1}, "context": {}})
    assert response.status_code == 502
    assert response.json()["error_type"] == "inference_backend_error"



def test_post_data_summary_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.data.get_summary_payload",
        lambda **_: {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "circuit_label": "CIR-1",
            "metric_mode": "BOTH",
            "saidi_total": 10.0,
            "saifi_total": 20.0,
            "event_count": 4,
            "daily_data": [{"fecha_dia": "2024-01-01", "SAIDI": 1.0, "SAIFI": 2.0}],
            "status_text": "ok",
        },
    )

    response = client.post(
        "/data",
        json={
            "mode": "summary",
            "summary": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "circuito": "CIR-1",
                "metric_mode": "BOTH",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "summary"
    assert payload["summary"]["event_count"] == 4
    assert sorted(payload["summary"].keys()) == sorted(
        [
            "start_date",
            "end_date",
            "circuit_label",
            "metric_mode",
            "saidi_total",
            "saifi_total",
            "event_count",
            "daily_data",
            "status_text",
        ]
    )


def test_post_data_summary_interpretability_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.data.get_summary_interpretability_payload",
        lambda **_: {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "circuit_label": "CIR-1",
            "metric_mode": "BOTH",
            "generated_at": "2026-06-04T00:00:00Z",
            "critical_points": [
                {
                    "fecha_dia": "2024-01-03",
                    "rank": 1,
                    "criticality_score": 1.2,
                    "criticality_types": ["saidi_high_outlier"],
                    "metrics": {"SAIDI": 9.5, "SAIFI": 0.05},
                    "reasons": [
                        {
                            "reason_type": "saidi_high_outlier",
                            "metric": "SAIDI",
                            "score": 1.0,
                            "value": 9.5,
                            "baseline": 0.2,
                            "threshold": 3.0,
                            "detail": "SAIDI alto.",
                        }
                    ],
                    "daily_aggregates": {"event_count": 3},
                    "top_causes": [],
                    "top_event_families": [],
                    "top_equipment": [],
                    "top_circuits": [],
                    "top_events": [],
                    "external_signals": {},
                    "data_quality_flags": [],
                    "confidence": "medium",
                }
            ],
            "critical_periods": [],
            "insight_text": "Texto deterministico.",
            "corpus_citations": [],
            "status_text": "ok",
        },
    )

    response = client.post(
        "/data",
        json={
            "mode": "summary_interpretability",
            "summary_interpretability": {
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "circuito": "CIR-1",
                "metric_mode": "BOTH",
                "max_points": 5,
                "include_agent_text": False,
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "summary_interpretability"
    assert payload["summary_interpretability"]["critical_points"][0]["fecha_dia"] == "2024-01-03"
    assert payload["summary_interpretability"]["insight_text"] == "Texto deterministico."



def test_post_data_map_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_get_map_payload(**kwargs):
        captured.update(kwargs)
        return {"map_html": "<html></html>", "current_day": 2, "status_text": "ok"}

    monkeypatch.setattr(
        "chec_dashboard.api.routes.data.get_map_payload",
        fake_get_map_payload,
    )

    response = client.post(
        "/data",
        json={
            "mode": "map",
            "map": {
                "selected_period": "2024-01",
                "selected_municipio": "Manizales",
                "selected_circuit": "Todos",
                "selected_circuits": ["CKT-1", "CKT-2"],
                "selected_output": "BASE",
                "day": 2,
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "map"
    assert payload["map"]["current_day"] == 2
    assert captured["selected_circuits"] == ["CKT-1", "CKT-2"]



def test_post_data_map_metadata_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.data.get_map_filter_metadata",
        lambda **_: {
            "action": "circuits",
            "dates": [],
            "municipios": [],
            "default_date": "2024-01",
            "default_municipio": "Manizales",
            "circuits": ["Todos", "CKT-1"],
            "default_circuit": "Todos",
            "outputs": ["BASE"],
            "default_output": "BASE",
        },
    )

    response = client.post(
        "/data",
        json={
            "mode": "map_metadata",
            "map_metadata": {
                "action": "circuits",
                "selected_period": "2024-01",
                "selected_municipio": "Manizales",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "map_metadata"
    assert payload["map_metadata"]["circuits"] == ["Todos", "CKT-1"]
    assert payload["map_metadata"]["default_output"] == "BASE"


def test_post_data_probability_route(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.data.get_probability_payload",
        lambda **_: {
            "probability_text": "P(x|y)",
            "status_text": "ok",
            "graph_name": "probability_graph_1.png",
            "graph_data_uri": "data:image/png;base64,ZmFrZQ==",
        },
    )

    response = client.post(
        "/data",
        json={
            "mode": "probability",
            "probability": {
                "criteria": "Eventos Tramo",
                "target_column": "duracion_h",
                "filters": [["", "", "", ""]],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "probability"
    assert payload["probability"]["graph_name"] == "probability_graph_1.png"
    assert payload["probability"]["graph_data_uri"].startswith("data:image/png;base64,")



def test_post_data_probability_metadata_columns_route(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.data.get_probability_columns_metadata",
        lambda **_: {
            "action": "columns",
            "criteria_options": [],
            "columns": ["a", "b"],
            "filter_kind": None,
            "value_options": [],
            "is_empty": False,
            "message": None,
        },
    )

    response = client.post(
        "/data",
        json={
            "mode": "probability_metadata",
            "probability_metadata": {
                "action": "columns",
                "criteria": "Eventos Tramo",
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "probability_metadata"
    assert payload["probability_metadata"]["columns"] == ["a", "b"]



def test_post_data_probability_metadata_filter_options_route(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.data.get_probability_filter_options_metadata",
        lambda **_: {
            "action": "filter_options",
            "criteria_options": [],
            "columns": [],
            "filter_kind": "seleccion",
            "value_options": ["x", "y"],
            "is_empty": False,
            "message": None,
        },
    )

    response = client.post(
        "/data",
        json={
            "mode": "probability_metadata",
            "probability_metadata": {
                "action": "filter_options",
                "criteria": "Eventos Tramo",
                "selected_column": "causa",
                "previous_filters": [["", "", "", ""]],
            },
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "probability_metadata"
    assert payload["probability_metadata"]["filter_kind"] == "seleccion"
