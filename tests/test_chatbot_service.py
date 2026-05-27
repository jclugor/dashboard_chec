from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.services.chatbot_service import (
    assess_chatbot_context,
    get_chatbot_context_options,
    get_chatbot_status,
    retrieve_chatbot_chunks,
)


def _settings(tmp_path: Path, data_dir: Path, corpus_dir: Path, **overrides):
    output_dir = tmp_path / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    return replace(
        base_settings,
        data_dir=data_dir,
        output_dir=output_dir,
        cache_enabled=False,
        data_backend="pickle",
        chatbot_corpus_dir=corpus_dir,
        chatbot_retrieval_top_k=3,
        chatbot_max_context_chars=3000,
        **overrides,
    )


def _write_map_files(data_dir: Path) -> None:
    trafos = pd.DataFrame(
        {
            "FECHA": ["2024-01-05"],
            "MUN": ["Manizales"],
            "LATITUD": [5.07],
            "LONGITUD": [-75.51],
            "FPARENT": ["CKT-1"],
            "CODE": ["TR-1"],
            "KVA": [25],
        }
    )
    empty_asset = pd.DataFrame(
        {
            "FECHA": ["2024-01-05"],
            "MUN": ["Manizales"],
            "LATITUD": [5.08],
            "LONGITUD": [-75.52],
            "FPARENT": ["CKT-1"],
            "CODE": ["SW-1"],
        }
    )
    redmt = pd.DataFrame(
        {
            "FECHA": ["2024-01-05"],
            "MUN": ["Manizales"],
            "LATITUD": [5.070],
            "LONGITUD": [-75.510],
            "LATITUD2": [5.071],
            "LONGITUD2": [-75.511],
            "FPARENT": ["CKT-1"],
            "CODE": ["L-1"],
        }
    )
    events = pd.DataFrame(
        {
            "inicio": ["2024-01-05 10:00:00"],
            "fin": ["2024-01-05 12:00:00"],
            "MUN": ["Manizales"],
            "LATITUD": [5.073],
            "LONGITUD": [-75.513],
            "equipo_ope": ["EQ-1"],
            "tipo_equi_ope": ["SW"],
            "cto_equi_ope": ["CKT-1"],
            "tipo_elemento": ["LINEA"],
            "duracion_h": [2.0],
            "causa": ["VIENTO"],
            "cnt_usus": [10],
            "SAIDI": [0.5],
            "SAIFI": [0.3],
        }
    )
    trafos.to_pickle(data_dir / "TRAFOS.pkl")
    empty_asset.to_pickle(data_dir / "SWITCHES.pkl")
    empty_asset.to_pickle(data_dir / "APOYOS.pkl")
    redmt.to_pickle(data_dir / "REDMT.pkl")
    events.to_pickle(data_dir / "SuperEventos_Criticidad_AguasAbajo_CODEs.pkl")


def _write_corpus(corpus_dir: Path) -> None:
    corpus_dir.mkdir(parents=True, exist_ok=True)
    chunks = [
        {
            "chunk_id": "retie-1",
            "document_id": "retie",
            "document_title": "RETIE",
            "source_path": "retie.pdf",
            "page": 10,
            "tags": ["retie", "viento", "red"],
            "text": "Las redes deben considerar esfuerzos por viento, condiciones ambientales y continuidad del servicio.",
        },
        {
            "chunk_id": "otros-1",
            "document_id": "otros",
            "document_title": "Otro documento",
            "source_path": "otro.pdf",
            "page": 2,
            "tags": ["aislador"],
            "text": "Requisitos para aisladores en condiciones normales.",
        },
    ]
    (corpus_dir / "chunks.jsonl").write_text(
        "\n".join(__import__("json").dumps(chunk, ensure_ascii=False) for chunk in chunks) + "\n",
        encoding="utf-8",
    )
    (corpus_dir / "documents_manifest.json").write_text(
        '{"documents":[{"document_id":"retie"},{"document_id":"otros"}]}',
        encoding="utf-8",
    )
    (corpus_dir / "variables_manifest.json").write_text('{"variables":[]}', encoding="utf-8")


def test_chatbot_status_reports_unconfigured_key(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True, gemini_api_key=None)

    status = get_chatbot_status(settings)

    assert status["enabled"] is True
    assert status["corpus_available"] is True
    assert status["gemini_configured"] is False
    assert status["ready"] is False
    assert status["chunks_path_exists"] is True
    assert "chunks.jsonl" in status["corpus_dir_entries"]
    assert "Gemini no está configurado" in status["message"]


def test_chatbot_status_reports_missing_corpus(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "missing-corpus"
    data_dir.mkdir()
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True, gemini_api_key=None)

    status = get_chatbot_status(settings)

    assert status["enabled"] is True
    assert status["corpus_available"] is False
    assert status["ready"] is False
    assert status["chunks_path_exists"] is False
    assert "corpus técnico no está disponible" in status["message"]


def test_chatbot_status_loads_corpus_through_databricks_files_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    corpus_dir = Path("/Volumes/chec_dbx_demo/raw/source_files/chatbot_corpus")
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True, gemini_api_key="fake-key")

    def fake_read(path: Path) -> str | None:
        if path.name == "chunks.jsonl":
            return (
                '{"chunk_id":"retie-1","document_title":"RETIE",'
                '"text":"Requisito técnico para redes y condiciones ambientales."}\n'
            )
        if path.name == "documents_manifest.json":
            return '{"documents":[{"document_id":"retie"}]}'
        if path.name == "variables_manifest.json":
            return '{"variables":[]}'
        return None

    monkeypatch.setattr("chec_dashboard.services.chatbot_service._read_databricks_file_text", fake_read)
    monkeypatch.setattr("chec_dashboard.services.chatbot_service._databricks_file_exists", lambda path: True)
    monkeypatch.setattr(
        "chec_dashboard.services.chatbot_service._list_databricks_directory",
        lambda path: (["chunks.jsonl", "documents_manifest.json", "variables_manifest.json"], None),
    )

    status = get_chatbot_status(settings)

    assert status["corpus_available"] is True
    assert status["chunks_count"] == 1
    assert status["documents_count"] == 1
    assert status["files_api_available"] is True
    assert status["chunks_path_exists"] is True


def test_retrieval_ranks_relevant_chunks(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True)

    chunks = retrieve_chatbot_chunks(
        settings,
        selected_context={"causa": "VIENTO", "tipo_elemento": "red"},
        question="condiciones de viento",
    )

    assert chunks
    assert chunks[0]["chunk_id"] == "retie-1"


def test_assessment_without_gemini_key_returns_graceful_message(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True, gemini_api_key=None)

    payload = assess_chatbot_context(
        settings,
        selected_context={"causa": "VIENTO", "cto_equi_ope": "CKT-1"},
        question="explica el indicador",
    )

    assert payload["ready"] is False
    assert "Gemini no está configurado" in payload["answer"]
    assert payload["citations"]


def test_context_options_from_local_map_files(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_map_files(data_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir)

    payload = get_chatbot_context_options(
        settings,
        context_kind="event",
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuits=["CKT-1"],
        search="viento",
        limit=10,
    )

    assert payload["items"]
    assert payload["items"][0]["kind"] == "event"
    assert payload["items"][0]["context"]["cto_equi_ope"] == "CKT-1"


def test_gemini_wrapper_can_be_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        chatbot_enabled=True,
        gemini_api_key="fake-key",
    )

    monkeypatch.setattr(
        "chec_dashboard.services.chatbot_service._generate_gemini_answer",
        lambda settings, prompt: "Respuesta técnica en español [1].",
    )

    payload = assess_chatbot_context(
        settings,
        selected_context={"causa": "VIENTO", "cto_equi_ope": "CKT-1"},
        question=None,
    )

    assert payload["ready"] is True
    assert payload["answer"] == "Respuesta técnica en español [1]."
