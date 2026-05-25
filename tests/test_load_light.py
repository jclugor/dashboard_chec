from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
import pytest

from chec_dashboard.api.main import create_api_app


@pytest.fixture()
def client() -> TestClient:
    app = create_api_app()
    return TestClient(app)



def test_concurrent_summary_requests(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
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

    body = {
        "mode": "summary",
        "summary": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "circuito": "CIR-1",
            "metric_mode": "BOTH",
        },
    }

    def _call_summary() -> int:
        response = client.post("/data", json=body)
        return response.status_code

    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(lambda _: _call_summary(), range(24)))

    assert all(status == 200 for status in statuses)



def test_concurrent_map_requests(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "chec_dashboard.api.routes.data.get_map_payload",
        lambda **_: {"map_html": "<html></html>", "current_day": 1, "status_text": "ok"},
    )

    body = {
        "mode": "map",
        "map": {
            "selected_period": "2024-01",
            "selected_municipio": "Manizales",
            "day": 1,
        },
    }

    def _call_map() -> int:
        response = client.post("/data", json=body)
        return response.status_code

    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(lambda _: _call_map(), range(24)))

    assert all(status == 200 for status in statuses)
