from dataclasses import replace

import httpx
import pandas as pd
import pytest

from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.services.databricks_data_service import _build_map_where_clause
from chec_dashboard.services.data_service import (
    get_map_filter_metadata,
    get_map_payload,
    get_probability_filter_options_metadata,
    get_probability_payload,
    get_summary_payload,
)
from chec_dashboard.services.inference_service import (
    InferenceBackendRequestError,
    InferenceConfigurationError,
    InferenceResponseFormatError,
    InferenceService,
    InferenceTimeoutError,
    UnsupportedModelBackendError,
)
from chec_dashboard.services.summary_service import SUMMARY_FILE



def _test_settings(tmp_path, data_dir):
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    return replace(
        base_settings,
        data_dir=data_dir,
        output_dir=output_dir,
        cache_enabled=False,
        model_backend="mock",
        request_timeout_seconds=1,
        inference_http_retries=0,
        inference_retry_backoff_ms=0,
    )



def _write_probability_files(data_dir) -> None:
    frame_interruptor = pd.DataFrame(
        {
            "causa": ["viento", "rayo", "viento"],
            "duracion_h": [1.2, 0.5, 2.0],
            "inicio": ["2024-01-01", "2024-01-02", "2024-01-03"],
        }
    )
    frame_tramo = pd.DataFrame(
        {
            "causa": ["caida_arbol", "viento"],
            "duracion_h": [3.2, 1.0],
            "inicio": ["2024-01-01", "2024-01-04"],
        }
    )
    frame_transformador = pd.DataFrame(
        {
            "causa": ["sobrecarga"],
            "duracion_h": [4.5],
            "inicio": ["2024-01-05"],
        }
    )

    frame_interruptor.to_pickle(data_dir / "Eventos_interruptor.pkl")
    frame_tramo.to_pickle(data_dir / "Eventos_tramo_linea.pkl")
    frame_transformador.to_pickle(data_dir / "Eventos_transformador.pkl")



def _write_map_files(data_dir) -> None:
    trafos = pd.DataFrame(
        {
            "FECHA": ["2024-01-05", "2024-01-10", "2024-02-01"],
            "MUN": ["Manizales", "Manizales", "Neira"],
            "LATITUD": [5.07, 5.08, 5.10],
            "LONGITUD": [-75.51, -75.52, -75.50],
            "FPARENT": ["CKT-1", "CKT-2", "CKT-9"],
            "PHASES": ["ABC", "ABC", "AB"],
            "OWNER1": ["CHEC", "CHEC", "CHEC"],
            "IMPEDANCE": [1.0, 1.1, 0.9],
            "MARCA": ["A", "B", "C"],
            "DATE_FAB": ["2020-01-01", "2020-02-01", "2020-03-01"],
            "TIPO_SUB": ["POSTE", "POSTE", "POSTE"],
            "KVA": [25, 50, 75],
            "KV1": [13.2, 13.2, 13.2],
        }
    )
    switches = pd.DataFrame(
        {
            "FECHA": ["2024-01-05", "2024-01-07"],
            "MUN": ["Manizales", "Manizales"],
            "LATITUD": [5.075, 5.085],
            "LONGITUD": [-75.515, -75.525],
            "FPARENT": ["CKT-1", "CKT-2"],
            "PHASES": ["ABC", "ABC"],
            "ASSEMBLY": ["ASM-1", "ASM-2"],
            "KV": [13.2, 13.2],
            "STATE": ["CERRADO", "ABIERTO"],
        }
    )
    redmt = pd.DataFrame(
        {
            "FECHA": ["2024-01-05", "2024-01-07"],
            "MUN": ["Manizales", "Manizales"],
            "LATITUD": [5.070, 5.080],
            "LONGITUD": [-75.510, -75.520],
            "LATITUD2": [5.071, 5.081],
            "LONGITUD2": [-75.511, -75.521],
            "FPARENT": ["CKT-1", "CKT-2"],
            "MATERIALCONDUCTOR": ["AL", "AL"],
            "TIPOCONDUCTOR": ["X", "Y"],
            "LENGTH": [10, 12],
            "CALIBRECONDUCTOR": ["1/0", "2/0"],
            "GUARDACONDUCTOR": ["N", "N"],
            "NEUTROCONDUCTOR": ["S", "S"],
            "CALIBRENEUTRO": ["1/0", "2/0"],
            "CAPACITY": [100, 110],
            "RESISTANCE": [1.1, 1.2],
            "ACOMETIDACONDUCTOR": ["NO", "NO"],
        }
    )
    apoyos = pd.DataFrame(
        {
            "FECHA": ["2024-01-05", "2024-01-10"],
            "MUN": ["Manizales", "Manizales"],
            "LATITUD": [5.072, 5.082],
            "LONGITUD": [-75.512, -75.522],
            "TOWNER": ["CHEC", "CHEC"],
            "TIPO": ["POSTE", "POSTE"],
            "CLASE": ["A", "B"],
            "MATERIAL": ["CONCRETO", "MADERA"],
            "LONG_APOYO": [12, 11],
            "TIERRA_PIE": ["SI", "NO"],
            "VIENTOS": [0, 1],
        }
    )
    super_eventos = pd.DataFrame(
        {
            "inicio": ["2024-01-05 10:00:00", "2024-01-10 13:00:00", "2024-02-01 09:00:00"],
            "fin": ["2024-01-05 12:00:00", "2024-01-10 14:30:00", "2024-02-01 10:00:00"],
            "MUN": ["Manizales", "Manizales", "Neira"],
            "LATITUD": [5.073, 5.083, 5.101],
            "LONGITUD": [-75.513, -75.523, -75.501],
            "equipo_ope": ["EQ-1", "EQ-2", "EQ-9"],
            "tipo_equi_ope": ["SW", "SW", "SW"],
            "cto_equi_ope": ["CKT-1", "CKT-2", "CKT-9"],
            "tipo_elemento": ["LINEA", "LINEA", "LINEA"],
            "duracion_h": [2.0, 1.5, 1.0],
            "causa": ["VIENTO", "RAYO", "VIENTO"],
            "cnt_usus": [10, 12, 3],
            "SAIDI": [0.5, 0.4, 0.1],
        }
    )

    trafos.to_pickle(data_dir / "TRAFOS.pkl")
    switches.to_pickle(data_dir / "SWITCHES.pkl")
    redmt.to_pickle(data_dir / "REDMT.pkl")
    apoyos.to_pickle(data_dir / "APOYOS.pkl")
    super_eventos.to_pickle(data_dir / "SuperEventos_Criticidad_AguasAbajo_CODEs.pkl")


def test_data_service_summary_payload(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    frame = pd.DataFrame(
        {
            "inicio": ["2024-01-01", "2024-01-01", "2024-01-02"],
            "cto_equi_ope": ["CIR-1", "CIR-1", "CIR-2"],
            "SAIDI": [1.0, 2.0, 0.5],
            "SAIFI": [0.2, 0.3, 0.1],
        }
    )
    frame.to_pickle(data_dir / SUMMARY_FILE)

    settings = _test_settings(tmp_path, data_dir)
    payload = get_summary_payload(
        settings=settings,
        start_date_raw="2024-01-01",
        end_date_raw="2024-01-02",
        circuito="CIR-1",
        metric_mode="BOTH",
    )

    assert payload["circuit_label"] == "CIR-1"
    assert payload["event_count"] == 2
    assert payload["saidi_total"] == pytest.approx(3.0)
    assert payload["saifi_total"] == pytest.approx(0.5)
    assert len(payload["daily_data"]) == 2



def test_probability_filter_options_metadata(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_probability_files(data_dir)

    settings = _test_settings(tmp_path, data_dir)
    payload = get_probability_filter_options_metadata(
        settings=settings,
        criteria="Eventos Interruptor",
        selected_column="causa",
        previous_filters=[],
    )

    assert payload["action"] == "filter_options"
    assert payload["filter_kind"] == "seleccion"
    assert payload["value_options"]



def test_map_metadata_returns_merged_circuits(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_map_files(data_dir)

    settings = _test_settings(tmp_path, data_dir)
    payload = get_map_filter_metadata(
        settings=settings,
        action="circuits",
        selected_period="2024-01",
        selected_municipio="Manizales",
    )

    assert payload["action"] == "circuits"
    assert payload["circuits"][0] == "Todos"
    assert payload["circuits"][1:] == ["CKT-1", "CKT-2"]
    assert payload["default_output"] == "BASE"


def test_map_payload_filters_selected_circuit_and_hides_apoyos(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_map_files(data_dir)

    settings = _test_settings(tmp_path, data_dir)
    observed: dict[str, int] = {}

    def fake_render(filtered, day: int) -> str:
        observed["trafos"] = len(filtered.trafos)
        observed["switches"] = len(filtered.switches)
        observed["redmt"] = len(filtered.redmt)
        observed["apoyos"] = len(filtered.apoyos)
        observed["events"] = len(filtered.events_by_day[day - 1])
        return "<html>map</html>"

    monkeypatch.setattr("chec_dashboard.services.data_service.render_base_map", fake_render)

    payload = get_map_payload(
        settings=settings,
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuit="CKT-1",
        selected_output="BASE",
        day=5,
    )

    assert payload["map_html"] == "<html>map</html>"
    assert "circuito CKT-1" in payload["status_text"]
    assert "salida BASE" in payload["status_text"]
    assert observed == {
        "trafos": 1,
        "switches": 1,
        "redmt": 1,
        "apoyos": 0,
        "events": 1,
    }


def test_map_payload_filters_selected_circuit_list_and_empty_selection(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_map_files(data_dir)

    settings = _test_settings(tmp_path, data_dir)
    observed: dict[str, dict[str, int]] = {}

    def fake_render(filtered, day: int) -> str:
        observed[f"day-{day}"] = {
            "trafos": len(filtered.trafos),
            "switches": len(filtered.switches),
            "redmt": len(filtered.redmt),
            "apoyos": len(filtered.apoyos),
            "events": len(filtered.events_by_day[day - 1]),
        }
        return "<html>map</html>"

    monkeypatch.setattr("chec_dashboard.services.data_service.render_base_map", fake_render)

    partial = get_map_payload(
        settings=settings,
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuit=None,
        selected_circuits=["CKT-1", "CKT-2"],
        selected_output="BASE",
        day=5,
    )
    empty = get_map_payload(
        settings=settings,
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuit="CKT-1",
        selected_circuits=[],
        selected_output="BASE",
        day=10,
    )

    assert "2 circuitos seleccionados" in partial["status_text"]
    assert "sin circuitos seleccionados" in empty["status_text"]
    assert observed["day-5"] == {
        "trafos": 2,
        "switches": 2,
        "redmt": 2,
        "apoyos": 0,
        "events": 1,
    }
    assert observed["day-10"] == {
        "trafos": 0,
        "switches": 0,
        "redmt": 0,
        "apoyos": 0,
        "events": 0,
    }


def test_databricks_map_where_clause_supports_multi_and_empty_circuits() -> None:
    multi = _build_map_where_clause(
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuits=["CKT-1", "CKT-2"],
    )
    empty = _build_map_where_clause(
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuits=[],
    )
    all_circuits = _build_map_where_clause(
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuits=None,
    )

    assert "circuito IN ('CKT-1', 'CKT-2')" in multi
    assert "1 = 0" in empty
    assert "circuito" not in all_circuits


def test_probability_payload_includes_data_uri(tmp_path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_probability_files(data_dir)

    settings = _test_settings(tmp_path, data_dir)
    payload = get_probability_payload(
        settings=settings,
        criteria="Eventos Interruptor",
        target_column="duracion_h",
        filters=[["", "", "", ""]],
    )

    assert payload["graph_name"] is not None
    assert payload["graph_data_uri"].startswith("data:image/png;base64,")



def test_inference_service_mock_backend_is_deterministic(tmp_path) -> None:
    settings = _test_settings(tmp_path, tmp_path)
    service = InferenceService(settings)

    first = service.predict(features={"a": 10, "b": 30}, request_id="req-1")
    second = service.predict(features={"a": 10, "b": 30}, request_id="req-1")

    assert first.backend == "mock"
    assert first.prediction == pytest.approx(second.prediction)
    assert first.label == second.label



def test_inference_service_unsupported_backend(tmp_path) -> None:
    settings = replace(_test_settings(tmp_path, tmp_path), model_backend="unknown")
    service = InferenceService(settings)

    with pytest.raises(UnsupportedModelBackendError):
        service.predict(features={"a": 1}, request_id="req-1")



def test_inference_service_azure_configuration_error(tmp_path) -> None:
    settings = replace(
        _test_settings(tmp_path, tmp_path),
        model_backend="azure_ml",
        azure_ml_endpoint=None,
        azure_ml_key=None,
    )
    service = InferenceService(settings)

    with pytest.raises(InferenceConfigurationError):
        service.predict(features={"a": 1}, request_id="req-1")



def test_inference_service_timeout_error(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = replace(
        _test_settings(tmp_path, tmp_path),
        model_backend="azure_ml",
        azure_ml_endpoint="https://example.test/score",
        azure_ml_key="token",
        inference_http_retries=0,
    )
    service = InferenceService(settings)

    class _TimeoutClient:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *_, **__):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("chec_dashboard.services.inference_service.httpx.Client", _TimeoutClient)

    with pytest.raises(InferenceTimeoutError):
        service.predict(features={"a": 1}, request_id="req-1")



def test_inference_service_backend_error(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = replace(
        _test_settings(tmp_path, tmp_path),
        model_backend="azure_ml",
        azure_ml_endpoint="https://example.test/score",
        azure_ml_key="token",
        inference_http_retries=0,
    )
    service = InferenceService(settings)

    class _RequestErrorClient:
        def __init__(self, *_, **__):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *_, **__):
            raise httpx.RequestError("network down")

    monkeypatch.setattr("chec_dashboard.services.inference_service.httpx.Client", _RequestErrorClient)

    with pytest.raises(InferenceBackendRequestError):
        service.predict(features={"a": 1}, request_id="req-1")



def test_inference_service_malformed_backend_response(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = replace(
        _test_settings(tmp_path, tmp_path),
        model_backend="azure_ml",
        azure_ml_endpoint="https://example.test/score",
        azure_ml_key="token",
    )
    service = InferenceService(settings)

    monkeypatch.setattr(
        service,
        "_post_json",
        lambda **_: {"not_prediction": "x"},
    )

    with pytest.raises(InferenceResponseFormatError):
        service.predict(features={"a": 1}, request_id="req-1")
