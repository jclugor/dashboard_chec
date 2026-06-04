from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import textwrap

import httpx
import pandas as pd
import pytest

from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.services.chatbot_service import (
    DatabricksAISearchRetriever,
    DatabricksModelServingLLMClient,
    _databricks_chat_payload,
    _parse_ai_search_response,
    _parse_databricks_model_serving_response,
    assess_chatbot_context,
    build_answer_quality_metadata,
    build_chatbot_context_package,
    build_context_tool_payload,
    build_release_report,
    citation_payload,
    create_chatbot_conversation,
    get_circuit_history_tool,
    get_chatbot_context_options,
    get_chatbot_conversation,
    get_skill_status,
    get_chatbot_status,
    normalize_structured_answer,
    observability_status,
    resolve_prompt_metadata,
    retrieve_chatbot_chunks,
    route_agent_tools,
    score_turn_trace,
    send_chatbot_message,
    submit_chatbot_feedback,
    validate_citations,
    validate_compliance_language,
)
from chec_dashboard.services.conversation_service import (
    ConversationFeedback,
    ConversationMessage,
    ConversationRecord,
    DatabricksSQLConversationStore,
    recent_conversation_messages,
    reset_memory_conversation_store,
)
from chec_dashboard.services.prompt_service import build_prompt
from chec_dashboard.services.skill_service import resolve_skill


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


def _write_skill(skill_dir: Path, name: str, text: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / name).write_text(textwrap.dedent(text).strip() + "\n", encoding="utf-8")


def test_structured_answer_parser_handles_canonical_sections() -> None:
    answer = """
    ## Estado observado
    - SAIDI alto en el circuito CKT-1 [1].
    ## Banderas de evidencia
    - Evidencia disponible de recurrencia.
    ## Requisitos posiblemente aplicables
    - CREG 015 puede ser aplicable [1].
    ## Datos faltantes
    - Fecha exacta de normalización.
    ## Riesgo posible
    - Posible riesgo de continuidad.
    ## Recomendaciones
    - Validar causa raíz.
    ## Limitaciones
    - Sin inspección de campo.
    ## Citas usadas
    - [1] CREG 015.
    ## Preguntas sugeridas
    - ¿Cuál fue la causa repetida?
    """

    structured, validation = normalize_structured_answer(textwrap.dedent(answer))

    assert validation["valid"] is True
    assert validation["missing_sections"] == []
    assert structured["estado_observado"][0].startswith("SAIDI alto")
    assert structured["citas_usadas"][0].startswith("[1]")


def test_structured_answer_parser_fills_partial_and_plain_markdown() -> None:
    partial, partial_validation = normalize_structured_answer(
        "## Estado observado\nTexto con evidencia disponible [1]."
    )
    plain, plain_validation = normalize_structured_answer("Respuesta libre sin secciones.")

    assert partial_validation["valid"] is False
    assert "datos_faltantes" in partial_validation["missing_sections"]
    assert partial["datos_faltantes"][0]
    assert plain_validation["fallback_used"] is True
    assert plain["estado_observado"][0] == "Respuesta libre sin secciones."


def test_citation_validator_resolves_markers_and_flags_uncited_claims() -> None:
    citations = [{"id": "creg-1", "title": "CREG 015"}]
    valid = validate_citations("CREG 015 define SAIDI y SAIFI [1].", citations)
    invalid = validate_citations(
        "CREG 015 define SAIDI y SAIFI. Ver también [2].",
        citations,
    )

    assert valid["valid"] is True
    assert valid["used_citation_numbers"] == [1]
    assert invalid["valid"] is False
    assert invalid["unknown_citation_numbers"] == [2]
    assert invalid["uncited_regulatory_claims"]


def test_compliance_validator_flags_overclaims_and_allows_prudent_language() -> None:
    flagged = validate_compliance_language(
        "El activo no cumple y tiene incumplimiento confirmado con sanción aplicable."
    )
    allowed = validate_compliance_language(
        "Hay posible riesgo, evidencia disponible y una recomendación de verificación."
    )

    assert flagged["valid"] is False
    assert "no cumple" in flagged["flagged_phrases"]
    assert "incumplimiento confirmado" in flagged["flagged_phrases"]
    assert "sanción aplicable" in flagged["flagged_phrases"]
    assert allowed["valid"] is True
    assert "posible riesgo" in allowed["allowed_language_present"]


def test_answer_quality_metadata_combines_sections_and_validators() -> None:
    metadata = build_answer_quality_metadata(
        "## Estado observado\nCREG 015 aplica al indicador SAIDI.",
        citations=[{"id": "creg-1"}],
        briefing_type="compliance",
    )

    assert set(metadata) == {
        "structured_answer",
        "answer_validation",
        "citation_validation",
        "compliance_validation",
    }
    assert metadata["answer_validation"]["valid"] is False
    assert metadata["citation_validation"]["valid"] is False
    assert metadata["compliance_validation"]["valid"] is True


def test_phase9_evaluation_scorers_are_deterministic() -> None:
    trace = {
        "ready": True,
        "latency_ms": 420,
        "citations": [{"id": "creg-1"}, {"id": "saidi-2"}],
        "retrieved_chunk_ids": ["creg-1", "other-1", "saidi-2"],
        "structured_answer": {
            "estado_observado": ["Texto"],
            "banderas_evidencia": ["Texto"],
            "requisitos_posiblemente_aplicables": ["Texto"],
            "datos_faltantes": ["Texto"],
            "riesgo_posible": ["Texto"],
            "recomendaciones": ["Texto"],
            "limitaciones": ["Texto"],
            "citas_usadas": ["Texto"],
            "preguntas_sugeridas": ["Texto"],
        },
        "validation": {
            "citation_validation": {"valid": True},
            "compliance_validation": {"valid": True},
        },
    }

    score = score_turn_trace(trace)
    report = build_release_report([trace], report_only=True)

    assert score["retrieval_precision_at_3"] == 0.6667
    assert score["citation_validity"] == 1.0
    assert score["answer_completeness"] == 1.0
    assert score["compliance_overclaim_rate"] == 0.0
    assert report["report_only"] is True
    assert report["release_status"] == "passed"
    assert report["metrics"]["latency_p95"] == 420.0
    assert report["sme_review_coverage"] == "draft_examples_need_sme_review"


def test_chatbot_status_uses_mock_provider_without_credentials(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True, gemini_api_key=None)

    status = get_chatbot_status(settings)

    assert status["enabled"] is True
    assert status["llm_provider"] == "mock"
    assert status["llm_configured"] is True
    assert status["corpus_available"] is True
    assert status["gemini_configured"] is False
    assert status["ready"] is True
    assert status["skills_available"] is True
    assert status["skills_count"] == 6
    assert status["skill_errors_count"] == 0
    assert status["chunks_path_exists"] is True
    assert "chunks.jsonl" in status["corpus_dir_entries"]
    assert "listo" in status["message"]
    assert status["observability_enabled"] is False
    assert status["mlflow_prompt_name"] == "chec_chatbot_answer_prompt"
    assert status["mlflow_prompt_alias"] == "production"
    assert status["mlflow_prompt_source"] == "local"
    assert status["chatbot_telemetry_schema"] == "agent_observability"
    assert status["chatbot_eval_report_only"] is True


def test_observability_status_and_prompt_metadata_noop_locally(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir)

    metadata = resolve_prompt_metadata(settings, "Hola {{question_text}}")
    status = observability_status(settings)

    assert metadata.prompt_source == "local"
    assert metadata.prompt_version == "local"
    assert metadata.prompt_hash
    assert status["observability_enabled"] is False
    assert status["observability_configured"] is False
    assert status["mlflow_prompt_name"] == "chec_chatbot_answer_prompt"
    assert status["mlflow_prompt_source"] == "local"


def test_chatbot_status_reports_unconfigured_selected_gemini_provider(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        chatbot_enabled=True,
        gemini_api_key=None,
        llm_provider="gemini",
    )

    status = get_chatbot_status(settings)

    assert status["llm_provider"] == "gemini"
    assert status["llm_configured"] is False
    assert status["gemini_configured"] is False
    assert status["ready"] is False
    assert "gemini" in status["message"]


def test_chatbot_status_reports_databricks_model_serving_readiness(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        chatbot_enabled=True,
        llm_provider="databricks_model_serving",
        llm_endpoint_name="databricks-qwen3-next-80b-a3b-instruct",
        llm_max_tokens=900,
        llm_temperature=0.15,
    )

    status = get_chatbot_status(settings)

    assert status["ready"] is True
    assert status["llm_provider"] == "databricks_model_serving"
    assert status["llm_configured"] is True
    assert status["llm_endpoint_configured"] is True
    assert status["model_endpoint_name"] == "databricks-qwen3-next-80b-a3b-instruct"
    assert status["llm_max_tokens"] == 900
    assert status["llm_temperature"] == 0.15


def test_chatbot_status_reports_unconfigured_databricks_model_serving(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        chatbot_enabled=True,
        llm_provider="databricks_model_serving",
        llm_endpoint_name=None,
        databricks_model_endpoint=None,
    )

    status = get_chatbot_status(settings)

    assert status["ready"] is False
    assert status["llm_configured"] is False
    assert status["llm_endpoint_configured"] is False
    assert "LLM_ENDPOINT_NAME" in status["message"]


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

    monkeypatch.setattr("chec_dashboard.services.retrieval_service.read_databricks_file_text", fake_read)
    monkeypatch.setattr("chec_dashboard.services.retrieval_service.databricks_file_exists", lambda path: True)
    monkeypatch.setattr(
        "chec_dashboard.services.retrieval_service.list_databricks_directory",
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


def test_ai_search_response_parser_returns_citation_ready_chunks() -> None:
    response = {
        "manifest": {
            "columns": [
                {"name": "chunk_id"},
                {"name": "document_title"},
                {"name": "document_type"},
                {"name": "source_path"},
                {"name": "source_uri"},
                {"name": "page"},
                {"name": "section_title"},
                {"name": "section_number"},
                {"name": "authority_level"},
                {"name": "text"},
            ]
        },
        "result": {
            "data_array": [
                [
                    "creg-015-1",
                    "CREG 015",
                    "pdf",
                    "resolucion_creg_0015_2018.pdf",
                    "/Volumes/chec_dbx_demo/raw/source_files/chatbot_documents/resolucion_creg_0015_2018.pdf",
                    4,
                    "SAIDI y SAIFI",
                    "2.1",
                    "normative_or_technical_document",
                    "CREG 015 define indicadores SAIDI y SAIFI para calidad del servicio.",
                ]
            ]
        },
    }

    chunks = _parse_ai_search_response(response)
    citations = citation_payload(chunks)

    assert chunks[0]["chunk_id"] == "creg-015-1"
    assert chunks[0]["score"] == 1.0
    assert citations[0]["id"] == "creg-015-1"
    assert citations[0]["title"] == "CREG 015"
    assert citations[0]["source_uri"].endswith("resolucion_creg_0015_2018.pdf")
    assert citations[0]["section_title"] == "SAIDI y SAIFI"
    assert citations[0]["section_number"] == "2.1"
    assert citations[0]["document_type"] == "pdf"
    assert citations[0]["authority_level"] == "normative_or_technical_document"


def test_ai_search_retriever_builds_bounded_hybrid_query(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "missing-corpus"
    data_dir.mkdir()
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        retriever_backend="databricks_ai_search",
        ai_search_index_name="chec_dbx_demo.gold.technical_doc_chunks_current_index",
        ai_search_top_k=2,
        ai_search_query_type="hybrid",
    )
    calls: list[dict[str, object]] = []

    class FakeVectorSearchIndexes:
        def query_index(self, **kwargs):
            calls.append(kwargs)
            return {
                "manifest": {
                    "columns": [
                        {"name": "chunk_id"},
                        {"name": "document_title"},
                        {"name": "source_path"},
                        {"name": "page"},
                        {"name": "text"},
                    ]
                },
                "result": {
                    "data_array": [
                        ["saidi-1", "RETIE", "retie.pdf", 10, "SAIDI SAIFI CREG 015 continuidad del servicio."],
                        [
                            "saifi-2",
                            "CREG 015",
                            "resolucion_creg_0015_2018.pdf",
                            22,
                            "SAIFI y duracion de interrupciones para circuitos.",
                        ],
                    ]
                },
            }

    class FakeWorkspaceClient:
        vector_search_indexes = FakeVectorSearchIndexes()

    retriever = DatabricksAISearchRetriever(settings, workspace_client_factory=FakeWorkspaceClient)

    chunks = retriever.retrieve(
        selected_context={"structured_context_tool": {"summary": {"text": "Circuito CKT-1 con SAIDI alto."}}},
        question="CREG 015 SAIDI",
    )

    assert calls[0]["index_name"] == "chec_dbx_demo.gold.technical_doc_chunks_current_index"
    assert calls[0]["query_type"] == "hybrid"
    assert calls[0]["num_results"] == 2
    assert "text" in calls[0]["columns"]
    assert "CREG 015 SAIDI" in calls[0]["query_text"]
    assert len(chunks) == 2
    assert chunks[0]["snippet"] == "SAIDI SAIFI CREG 015 continuidad del servicio."
    assert chunks[1]["snippet"].startswith("SAIFI")


def test_databricks_model_serving_payload_is_bounded(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        llm_provider="databricks_model_serving",
        llm_endpoint_name="databricks-qwen3-next-80b-a3b-instruct",
        llm_max_tokens=321,
        llm_temperature=0.4,
    )

    payload = _databricks_chat_payload(settings, "Prompt técnico con citas [1].")

    assert payload["max_tokens"] == 321
    assert payload["temperature"] == 0.4
    assert payload["messages"][0]["role"] == "system"
    assert "español" in payload["messages"][0]["content"]
    assert payload["messages"][1] == {"role": "user", "content": "Prompt técnico con citas [1]."}


def test_databricks_model_serving_response_parser_reads_text_and_usage() -> None:
    result = _parse_databricks_model_serving_response(
        {
            "choices": [{"message": {"content": "Respuesta técnica con citas [1]."}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }
    )

    assert result.text == "Respuesta técnica con citas [1]."
    assert result.usage["total_tokens"] == 120


def test_databricks_model_serving_client_sends_trace_headers_and_parses_response(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        llm_provider="databricks_model_serving",
        llm_endpoint_name="databricks-qwen3-next-80b-a3b-instruct",
        databricks_host="https://adb-test.azuredatabricks.net",
        databricks_token="local-token",
        request_timeout_seconds=12,
        inference_http_retries=0,
    )
    calls: list[dict[str, object]] = []

    def fake_post_json(**kwargs):
        calls.append(kwargs)
        return {
            "choices": [{"message": {"content": "Análisis gobernado desde Databricks."}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 6, "total_tokens": 14},
        }

    client = DatabricksModelServingLLMClient(settings, post_json=fake_post_json)
    result = client.generate("Genera análisis.", trace_id="trace-123")

    assert result.text == "Análisis gobernado desde Databricks."
    assert calls[0]["url"] == (
        "https://adb-test.azuredatabricks.net/serving-endpoints/"
        "databricks-qwen3-next-80b-a3b-instruct/invocations"
    )
    assert calls[0]["headers"]["Authorization"] == "Bearer local-token"
    assert calls[0]["headers"]["X-Request-ID"] == "trace-123"
    assert calls[0]["payload"]["messages"][1]["content"] == "Genera análisis."
    assert calls[0]["timeout"] == 12


def test_databricks_model_serving_timeout_is_spanish_error(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        llm_provider="databricks_model_serving",
        llm_endpoint_name="databricks-qwen3-next-80b-a3b-instruct",
        databricks_host="https://adb-test.azuredatabricks.net",
        databricks_token="local-token",
        request_timeout_seconds=1,
        inference_http_retries=0,
    )

    def fake_post_json(**kwargs):
        raise httpx.TimeoutException("timed out")

    client = DatabricksModelServingLLMClient(settings, post_json=fake_post_json)

    with pytest.raises(RuntimeError, match="tiempo límite"):
        client.generate("Genera análisis.", trace_id="trace-timeout")


def test_chatbot_status_reports_ai_search_ready_without_jsonl(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "missing-corpus"
    data_dir.mkdir()
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        chatbot_enabled=True,
        retriever_backend="databricks_ai_search",
        ai_search_index_name="chec_dbx_demo.gold.technical_doc_chunks_current_index",
    )

    status = get_chatbot_status(settings)

    assert status["ready"] is True
    assert status["corpus_available"] is True
    assert status["chunks_path_exists"] is False
    assert status["retriever_backend"] == "databricks_ai_search"
    assert status["ai_search_configured"] is True
    assert status["ai_search_index_name"] == "chec_dbx_demo.gold.technical_doc_chunks_current_index"
    assert status["ai_search_query_type"] == "hybrid"
    assert status["ai_search_top_k"] == 8


def test_missing_ai_search_config_returns_traceable_early_answer(tmp_path: Path) -> None:
    reset_memory_conversation_store()
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "missing-corpus"
    data_dir.mkdir()
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        chatbot_enabled=True,
        retriever_backend="databricks_ai_search",
        ai_search_index_name=None,
    )

    result = assess_chatbot_context(
        settings,
        selected_context={"CODE": "TR-1", "causa": "VIENTO"},
        question="CREG 015",
        briefing_type="reliability",
    )
    detail = get_chatbot_conversation(settings, result["conversation_id"])

    assert result["ready"] is False
    assert "AI_SEARCH_INDEX_NAME" in result["status_text"]
    assert result["skill_id"]
    assert result["skill_version"]
    assert result["skill_hash"]
    assert result["structured_answer"]["estado_observado"]
    assert result["answer_validation"]["valid"] in {True, False}
    assert result["citation_validation"]["valid"] in {True, False}
    assert result["compliance_validation"]["valid"] in {True, False}
    assert detail["messages"][-1]["skill_id"] == result["skill_id"]
    assert detail["messages"][-1]["structured_answer"] == result["structured_answer"]


def test_databricks_model_serving_failure_preserves_citations_and_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_memory_conversation_store()
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        chatbot_enabled=True,
        llm_provider="databricks_model_serving",
        llm_endpoint_name="databricks-qwen3-next-80b-a3b-instruct",
    )

    def fake_generate(settings, prompt, *, trace_id=None):
        raise RuntimeError("Databricks Model Serving no respondió antes del tiempo límite.")

    monkeypatch.setattr(
        "chec_dashboard.services.llm_service._generate_databricks_model_serving_answer",
        fake_generate,
    )

    result = assess_chatbot_context(
        settings,
        selected_context={"CODE": "TR-1", "causa": "VIENTO"},
        question="condiciones de viento",
        briefing_type="reliability",
    )
    detail = get_chatbot_conversation(settings, result["conversation_id"])

    assert result["ready"] is False
    assert result["citations"]
    assert result["llm_provider"] == "databricks_model_serving"
    assert result["model_endpoint_name"] == "databricks-qwen3-next-80b-a3b-instruct"
    assert result["trace_id"]
    assert "No fue posible generar el análisis" in result["answer"]
    assert result["structured_answer"]["estado_observado"]
    assert result["citation_validation"]["available_citation_numbers"]
    assert detail["messages"][-1]["trace_id"] == result["trace_id"]
    assert detail["messages"][-1]["llm_provider"] == "databricks_model_serving"
    assert detail["messages"][-1]["model_endpoint_name"] == result["model_endpoint_name"]
    assert detail["messages"][-1]["citation_validation"] == result["citation_validation"]


def test_default_repo_skills_load_and_validate(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    settings = _settings(tmp_path, data_dir, corpus_dir)

    status = get_skill_status(settings)
    skill = resolve_skill("compliance", settings)

    assert status["skills_available"] is True
    assert status["skills_count"] == 6
    assert status["skill_errors_count"] == 0
    assert ".yml" in status["supported_file_types"]
    assert ".yaml" in status["supported_file_types"]
    assert ".md" in status["supported_file_types"]
    assert status["lifecycle_directories"]["active"]["exists"] is True
    assert skill.skill_id == "cumplimiento"
    assert skill.skill_version == "1.0"
    assert skill.skill_hash
    assert skill.skill.source_type == "default"


def test_configured_skill_overrides_default_and_shapes_prompt(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    skill_dir = tmp_path / "skills"
    data_dir.mkdir()
    _write_skill(
        skill_dir,
        "mantenimiento.yml",
        """
        skill_id: mantenimiento
        version: "2.0"
        status: active
        role: Asistente de mantenimiento personalizado.
        language: es
        tone: Directo.
        allowed_tools:
          - get_dashboard_context
          - search_technical_documents
        instructions:
          - Prioriza cuadrillas de campo por criticidad personalizada.
        output:
          sections:
            - Seccion personalizada
            - Evidencia de campo
            - Datos por confirmar
            - Accion sugerida
        constraints:
          must_cite_regulatory_claims: true
          cannot_make_legal_conclusions: true
          forbidden_phrases:
            - cierre definitivo
        missing_evidence_behavior: Pedir medicion de campo.
        retrieval:
          backend: local_jsonl
          top_k: 2
          boost_tags:
            - mantenimiento
        """,
    )
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_skills_dir=skill_dir)

    skill = resolve_skill("maintenance", settings)
    prompt = build_prompt(
        context_package={"nombre_analisis": "Mantenimiento", "selected_context": {"CODE": "TR-1"}},
        question="prioridad",
        briefing_type="maintenance",
        chunks=[],
        skill_resolution=skill,
    )

    assert skill.skill_version == "2.0"
    assert skill.skill.source_type == "configured"
    assert "Seccion personalizada" in prompt
    assert "Prioriza cuadrillas de campo" in prompt
    assert "cierre definitivo" in prompt


def test_configured_markdown_skill_uses_front_matter_and_body_instructions(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    skill_dir = tmp_path / "skills"
    data_dir.mkdir()
    _write_skill(
        skill_dir,
        "mantenimiento.md",
        """
        ---
        skill_id: mantenimiento
        version: "2.1"
        status: active
        role: Asistente de mantenimiento en Markdown.
        language: es
        tone: Operativo.
        allowed_tools:
          - get_dashboard_context
          - search_technical_documents
        instructions:
          - Mantener foco en continuidad del servicio.
        output:
          sections:
            - Diagnostico
            - Revision en campo
        constraints:
          must_cite_regulatory_claims: true
          cannot_make_legal_conclusions: true
          forbidden_phrases: []
        missing_evidence_behavior: Pedir medicion de campo.
        retrieval:
          backend: local_jsonl
          top_k: 2
        ---

        ## Guia operativa

        Prioriza activos con recurrencia y registra datos faltantes antes de recomendar acciones.
        """,
    )
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_skills_dir=skill_dir)

    skill = resolve_skill("maintenance", settings)
    prompt = build_prompt(
        context_package={"nombre_analisis": "Mantenimiento", "selected_context": {"CODE": "TR-1"}},
        question="prioridad",
        briefing_type="maintenance",
        chunks=[],
        skill_resolution=skill,
    )

    assert skill.skill_version == "2.1"
    assert skill.skill.source_type == "configured"
    assert "Mantener foco en continuidad del servicio" in prompt
    assert "Prioriza activos con recurrencia" in prompt


def test_markdown_skill_without_front_matter_falls_back_and_reports_error(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    skill_dir = tmp_path / "skills"
    data_dir.mkdir()
    _write_skill(
        skill_dir,
        "cumplimiento.md",
        """
        # Cumplimiento

        Instrucciones sin front matter.
        """,
    )
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_skills_dir=skill_dir)

    status = get_skill_status(settings)
    skill = resolve_skill("compliance", settings)

    assert status["skill_errors_count"] == 1
    assert "front matter" in " ".join(status["validation_errors"][0]["errors"])
    assert skill.skill_version == "1.0"
    assert skill.skill.source_type == "default"


def test_duplicate_configured_skill_files_fall_back_and_report_error(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    skill_dir = tmp_path / "skills"
    data_dir.mkdir()
    skill_text = """
        skill_id: confiabilidad
        version: "2.0"
        status: active
        role: Skill duplicado.
        language: es
        tone: Tecnico.
        allowed_tools:
          - get_dashboard_context
        instructions:
          - No debe activarse por duplicado.
        output:
          sections:
            - Estado observado
        constraints:
          must_cite_regulatory_claims: true
          cannot_make_legal_conclusions: true
          forbidden_phrases: []
        retrieval:
          backend: local_jsonl
    """
    _write_skill(skill_dir, "confiabilidad.yml", skill_text)
    _write_skill(skill_dir, "confiabilidad.yaml", skill_text)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_skills_dir=skill_dir)

    status = get_skill_status(settings)
    skill = resolve_skill("reliability", settings)

    assert status["skill_errors_count"] == 1
    assert "Multiples archivos configurados" in " ".join(status["validation_errors"][0]["errors"])
    assert skill.skill_version == "1.0"
    assert skill.skill.source_type == "default"


def test_blocked_markdown_skill_body_falls_back_and_reports_error(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    skill_dir = tmp_path / "skills"
    data_dir.mkdir()
    _write_skill(
        skill_dir,
        "cumplimiento.md",
        """
        ---
        skill_id: cumplimiento
        version: "2.0"
        status: active
        role: Asistente de cumplimiento.
        language: es
        tone: Prudente.
        allowed_tools:
          - get_dashboard_context
        instructions:
          - Validar controles.
        output:
          sections:
            - Estado observado
        constraints:
          must_cite_regulatory_claims: true
          cannot_make_legal_conclusions: true
          forbidden_phrases: []
        retrieval:
          backend: local_jsonl
        ---

        select * from secret_table
        """,
    )
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_skills_dir=skill_dir)

    status = get_skill_status(settings)
    skill = resolve_skill("compliance", settings)

    assert status["skill_errors_count"] == 1
    assert "texto bloqueado" in " ".join(status["validation_errors"][0]["errors"])
    assert skill.skill_version == "1.0"
    assert skill.skill.source_type == "default"


def test_invalid_configured_skill_falls_back_and_reports_error(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    skill_dir = tmp_path / "skills"
    data_dir.mkdir()
    _write_skill(
        skill_dir,
        "cumplimiento.yml",
        """
        skill_id: cumplimiento
        version: "2.0"
        status: active
        sql: select * from secret_table
        instructions:
          - No debe aceptarse.
        """,
    )
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_skills_dir=skill_dir)

    status = get_skill_status(settings)
    skill = resolve_skill("compliance", settings)

    assert status["skill_errors_count"] == 1
    assert status["validation_errors"][0]["source_type"] == "configured"
    assert "control bloqueado" in " ".join(status["validation_errors"][0]["errors"])
    assert skill.skill_version == "1.0"
    assert skill.skill.source_type == "default"


def test_retrieval_uses_skill_top_k_and_boost_tags(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    skill_dir = tmp_path / "skills"
    data_dir.mkdir()
    corpus_dir.mkdir()
    chunks = [
        {
            "chunk_id": "red-1",
            "document_title": "Red",
            "tags": ["red"],
            "text": "Condiciones ambientales y continuidad del servicio.",
        },
        {
            "chunk_id": "aislador-1",
            "document_title": "Aislador",
            "tags": ["aislador"],
            "text": "Condiciones normales de aisladores.",
        },
    ]
    (corpus_dir / "chunks.jsonl").write_text(
        "\n".join(__import__("json").dumps(chunk, ensure_ascii=False) for chunk in chunks) + "\n",
        encoding="utf-8",
    )
    (corpus_dir / "documents_manifest.json").write_text('{"documents":[]}', encoding="utf-8")
    (corpus_dir / "variables_manifest.json").write_text('{"variables":[]}', encoding="utf-8")
    _write_skill(
        skill_dir,
        "confiabilidad.yml",
        """
        skill_id: confiabilidad
        version: "2.0"
        status: active
        role: Skill de prueba.
        language: es
        tone: Tecnico.
        allowed_tools:
          - get_dashboard_context
          - search_technical_documents
        instructions:
          - Probar refuerzo por etiqueta.
        output:
          sections:
            - Estado observado
        constraints:
          must_cite_regulatory_claims: true
          cannot_make_legal_conclusions: true
          forbidden_phrases: []
        missing_evidence_behavior: Reportar faltantes.
        retrieval:
          backend: local_jsonl
          top_k: 1
          boost_tags:
            - aislador
        """,
    )
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_skills_dir=skill_dir)
    skill = resolve_skill("reliability", settings)

    chunks = retrieve_chatbot_chunks(
        settings,
        selected_context={"causa": "condiciones"},
        question="condiciones",
        skill_resolution=skill,
    )

    assert len(chunks) == 1
    assert chunks[0]["chunk_id"] == "aislador-1"


def test_assessment_with_mock_provider_returns_deterministic_answer(tmp_path: Path) -> None:
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

    assert payload["ready"] is True
    assert "análisis mock" in payload["answer"]
    assert payload["citations"]
    assert payload["conversation_id"].startswith("conv-")
    assert payload["turn_id"].startswith("turn-")
    assert payload["skill_id"] == "confiabilidad"
    assert payload["skill_version"] == "1.0"
    assert payload["skill_hash"]
    assert payload["trace_id"].startswith("trace-")
    assert payload["prompt_name"] == "chec_chatbot_answer_prompt"
    assert payload["prompt_alias"] == "production"
    assert payload["prompt_version"] == "local"
    assert payload["prompt_hash"]
    assert payload["observability_status"] == "disabled"
    assert payload["latency_ms"] is not None
    assert payload["structured_answer"]["estado_observado"]
    assert "requisitos_posiblemente_aplicables" in payload["answer_validation"]["missing_sections"]


def test_assessment_reuses_conversation_id(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True)

    payload = assess_chatbot_context(
        settings,
        selected_context={"causa": "VIENTO", "cto_equi_ope": "CKT-1"},
        question=None,
        conversation_id="conv-existing",
    )

    assert payload["conversation_id"] == "conv-existing"
    assert payload["turn_id"].startswith("turn-")


def test_missing_context_assessment_persists_skill_metadata(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True)

    payload = assess_chatbot_context(
        settings,
        selected_context={},
        question="estado",
        briefing_type="compliance",
    )
    detail = get_chatbot_conversation(settings, payload["conversation_id"])

    assert payload["ready"] is False
    assert payload["skill_id"] == "cumplimiento"
    assert detail is not None
    assert detail["skill_id"] == payload["skill_id"]
    assert detail["skill_version"] == payload["skill_version"]
    assert detail["skill_hash"] == payload["skill_hash"]
    assert detail["messages"][-1]["skill_id"] == payload["skill_id"]
    assert detail["messages"][-1]["prompt_name"] == payload["prompt_name"]
    assert detail["messages"][-1]["prompt_hash"] == payload["prompt_hash"]
    assert detail["messages"][-1]["latency_ms"] == payload["latency_ms"]
    assert payload["structured_answer"]["estado_observado"]
    assert detail["messages"][-1]["structured_answer"] == payload["structured_answer"]


def test_followup_message_reuses_context_and_recent_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_memory_conversation_store()
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True, gemini_api_key=None)

    first = assess_chatbot_context(
        settings,
        selected_context={"causa": "VIENTO", "cto_equi_ope": "CKT-1"},
        question="explica el indicador",
    )
    captured_history: dict[str, list[dict[str, object]]] = {}

    def fake_build_prompt(**kwargs):
        captured_history["messages"] = kwargs.get("conversation_history") or []
        return "prompt con historial"

    monkeypatch.setattr("chec_dashboard.services.agent_orchestrator.build_prompt", fake_build_prompt)

    followup = send_chatbot_message(
        settings,
        conversation_id=first["conversation_id"],
        message="Que debo revisar en campo?",
    )
    detail = get_chatbot_conversation(settings, first["conversation_id"])

    assert followup is not None
    assert followup["ready"] is True
    assert followup["conversation_id"] == first["conversation_id"]
    assert captured_history["messages"][0]["role"] == "user"
    assert captured_history["messages"][1]["role"] == "assistant"
    assert "explica el indicador" in captured_history["messages"][0]["content"]
    assert detail is not None
    assert detail["context_snapshot"]["selected_context"]["cto_equi_ope"] == "CKT-1"
    assert len(detail["messages"]) == 4
    assert detail["messages"][-1]["llm_provider"] == "mock"
    assert detail["messages"][-1]["model_endpoint_name"] == "mock"
    assert followup["structured_answer"]["estado_observado"]
    assert detail["messages"][-1]["structured_answer"] == followup["structured_answer"]


def test_followup_without_saved_context_persists_clear_response(tmp_path: Path) -> None:
    reset_memory_conversation_store()
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True)
    conversation = create_chatbot_conversation(settings, selected_context={}, mode="free_form")

    payload = send_chatbot_message(
        settings,
        conversation_id=conversation["conversation_id"],
        message="Que sigue?",
    )
    detail = get_chatbot_conversation(settings, conversation["conversation_id"])

    assert payload is not None
    assert payload["ready"] is False
    assert payload["skill_id"] == "confiabilidad"
    assert payload["llm_provider"] == "mock"
    assert detail is not None
    assert detail["messages"][-1]["skill_hash"] == payload["skill_hash"]
    assert "No hay contexto guardado" in detail["messages"][-1]["content"]
    assert payload["structured_answer"]["estado_observado"]
    assert detail["messages"][-1]["answer_validation"] == payload["answer_validation"]


def test_conversation_feedback_validates_rating_and_returns_traceable_payload(tmp_path: Path) -> None:
    reset_memory_conversation_store()
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True)
    assessment = assess_chatbot_context(
        settings,
        selected_context={"causa": "VIENTO", "cto_equi_ope": "CKT-1"},
        question="estado",
    )

    feedback = submit_chatbot_feedback(
        settings,
        conversation_id=assessment["conversation_id"],
        turn_id=assessment["turn_id"],
        rating="helpful",
    )

    assert feedback["feedback_id"].startswith("feedback-")
    assert feedback["conversation_id"] == assessment["conversation_id"]
    assert feedback["turn_id"] == assessment["turn_id"]
    assert feedback["rating"] == "helpful"
    assert feedback["trace_id"] == assessment["trace_id"]
    assert feedback["prompt_name"] == assessment["prompt_name"]
    assert feedback["prompt_version"] == assessment["prompt_version"]
    assert feedback["skill_hash"] == assessment["skill_hash"]
    with pytest.raises(ValueError, match="rating"):
        submit_chatbot_feedback(
            settings,
            conversation_id=assessment["conversation_id"],
            turn_id=assessment["turn_id"],
            rating="bad",
        )


def test_recent_conversation_messages_uses_deterministic_bounded_memory(tmp_path: Path) -> None:
    reset_memory_conversation_store()
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        chatbot_enabled=True,
        chatbot_memory_max_turns=1,
    )
    first = assess_chatbot_context(
        settings,
        selected_context={"causa": "VIENTO", "cto_equi_ope": "CKT-1"},
        question="primer tema",
    )
    send_chatbot_message(settings, conversation_id=first["conversation_id"], message="segundo tema")
    send_chatbot_message(settings, conversation_id=first["conversation_id"], message="tercer tema")

    history_a = recent_conversation_messages(settings, first["conversation_id"])
    history_b = recent_conversation_messages(settings, first["conversation_id"])

    assert len(history_a) == 3
    assert history_a[0]["turn_id"] == history_b[0]["turn_id"]
    assert history_a[0]["content"].startswith("Memoria compacta deterministica")
    assert "primer tema" in history_a[0]["content"]
    assert history_a[-2]["content"] == "tercer tema"


def test_databricks_conversation_store_targets_agent_schema(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        databricks_catalog_name="chec_dbx_demo",
        chatbot_conversation_schema="agent",
    )

    class FakeClient:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def fetch_dataframe(self, statement: str):
            self.statements.append(statement)
            return pd.DataFrame()

    client = FakeClient()
    store = DatabricksSQLConversationStore(settings, client=client)  # type: ignore[arg-type]
    store.upsert_conversation(ConversationRecord(conversation_id="conv-1", llm_provider="mock"))
    store.append_messages(
        [
            ConversationMessage(
                conversation_id="conv-1",
                turn_id="turn-1",
                role="assistant",
                content="respuesta",
                llm_provider="mock",
                model_endpoint_name="mock",
            )
        ]
    )
    store.add_feedback(ConversationFeedback("feedback-1", "conv-1", "turn-1", "helpful"))

    assert store.conversations_table == "`chec_dbx_demo`.`agent`.`agent_conversations`"
    assert store.messages_table == "`chec_dbx_demo`.`agent`.`agent_messages`"
    assert store.feedback_table == "`chec_dbx_demo`.`agent`.`agent_feedback`"
    statements = "\n".join(client.statements)
    assert "`chec_dbx_demo`.`agent`.`agent_conversations`" in statements
    assert "`chec_dbx_demo`.`agent`.`agent_messages`" in statements
    assert "`chec_dbx_demo`.`agent`.`agent_feedback`" in statements
    assert "llm_provider" in statements
    assert "model_endpoint_name" in statements
    assert "agent_tool_calls_json" in statements
    assert "agent_skipped_tools_json" in statements
    assert "agent_route_summary_json" in statements
    assert "structured_answer_json" in statements
    assert "answer_validation_json" in statements
    assert "citation_validation_json" in statements
    assert "compliance_validation_json" in statements
    assert "prompt_name" in statements
    assert "prompt_version" in statements
    assert "prompt_hash" in statements
    assert "mlflow_trace_id" in statements
    assert "mlflow_run_id" in statements
    assert "latency_ms" in statements


def test_phase7_router_selects_documents_structured_tools_and_direct_mode() -> None:
    selected_context = {"kind": "event", "cto_equi_ope": "CKT-1", "causa": "VIENTO"}
    context_package = build_chatbot_context_package(
        selected_context=selected_context,
        briefing_type="reliability",
        question_id="reliability_saidi_saifi",
    )

    candidates = route_agent_tools(
        selected_context=selected_context,
        context_package=context_package,
        question="CREG 015 SAIDI SAIFI",
        briefing_type="reliability",
        question_id="reliability_saidi_saifi",
    )
    direct_candidates = route_agent_tools(
        selected_context=selected_context,
        context_package=context_package,
        question="gracias",
        briefing_type="reliability",
        question_id=None,
    )

    tool_names = {candidate.tool_name for candidate in candidates}
    assert "search_regulatory_documents" in tool_names
    assert "get_reliability_summary" in tool_names
    assert "get_event_context" in tool_names
    assert direct_candidates == []


def test_phase7_guided_assessment_returns_and_persists_tool_trace(tmp_path: Path) -> None:
    reset_memory_conversation_store()
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir, chatbot_enabled=True)

    payload = assess_chatbot_context(
        settings,
        selected_context={"kind": "event", "causa": "VIENTO", "cto_equi_ope": "CKT-1"},
        question="CREG 015 SAIDI SAIFI",
        briefing_type="reliability",
    )
    detail = get_chatbot_conversation(settings, payload["conversation_id"])

    assert payload["ready"] is True
    assert payload["agent_tool_calls"]
    assert payload["agent_route_summary"]["read_only"] is True
    assert "search_regulatory_documents" in payload["agent_route_summary"]["executed_tools"]
    assert payload["citations"]
    assert detail is not None
    assistant_turn = detail["messages"][-1]
    assert assistant_turn["agent_tool_calls"] == payload["agent_tool_calls"]
    assert assistant_turn["agent_route_summary"]["executed_tools"] == payload["agent_route_summary"]["executed_tools"]
    assert assistant_turn["structured_answer"] == payload["structured_answer"]
    assert assistant_turn["citation_validation"] == payload["citation_validation"]


def test_phase7_router_blocks_skill_disallowed_tools(tmp_path: Path) -> None:
    reset_memory_conversation_store()
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    skill_dir = tmp_path / "skills"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    _write_skill(
        skill_dir,
        "cumplimiento.yml",
        """
        skill_id: cumplimiento
        version: "7.0"
        status: active
        role: Asistente restringido.
        language: es
        tone: Seco.
        allowed_tools:
          - get_dashboard_context
        instructions:
          - Usa solo herramientas permitidas.
        output:
          sections:
            - Respuesta
        constraints:
          must_cite_regulatory_claims: true
          cannot_make_legal_conclusions: true
          forbidden_phrases:
            - dato inventado
        missing_evidence_behavior: Declarar datos faltantes.
        retrieval:
          backend: local_jsonl
          top_k: 2
        """,
    )
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        chatbot_enabled=True,
        chatbot_skills_dir=skill_dir,
    )

    payload = assess_chatbot_context(
        settings,
        selected_context={"kind": "event", "causa": "VIENTO", "cto_equi_ope": "CKT-1"},
        question="CREG 015 requisitos",
        briefing_type="compliance",
    )

    blocked = {
        item["tool_name"]
        for item in payload["agent_skipped_tools"]
        if item.get("skip_reason") == "blocked_by_skill_policy"
    }
    assert "search_regulatory_documents" in blocked
    assert "get_event_context" in blocked
    assert "search_regulatory_documents" not in payload["agent_route_summary"]["executed_tools"]


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


def test_view_context_options_include_filtered_analysis_context(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_map_files(data_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir)

    payload = get_chatbot_context_options(
        settings,
        context_kind="view",
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuits=["CKT-1"],
        search=None,
        limit=10,
    )

    item = payload["items"][0]
    context = item["context"]
    assert item["kind"] == "view"
    assert context["tool_name"] == "get_dashboard_context"
    assert context["source_view"].endswith("gold_agent_view_context")
    assert context["context_id"].startswith("view-")
    assert context["context_hash"]
    assert context["traceability"]["read_only"] is True
    assert context["kpi_summary"]["event_count"] == 1
    assert context["kpi_summary"]["saidi_total"] == 0.5
    assert context["top_circuits"][0]["label"] == "CKT-1"
    assert context["top_causes"][0]["label"] == "VIENTO"


def test_context_tool_payload_is_bounded_json_safe_and_deterministic() -> None:
    records = [{"idx": index, "when": pd.Timestamp("2024-01-01")} for index in range(75)]

    payload_a = build_context_tool_payload(
        kind="view",
        tool_name="get_dashboard_context",
        source_function="local.agent_tools.get_dashboard_context",
        source_view="local.gold.gold_agent_view_context",
        parameters={"period": "2024-01", "municipio": "Manizales"},
        summary={"text": "Resumen"},
        records=records,
        metrics={"kpi_summary": {"event_count": 1}},
        traceability={"read_only": True},
    )
    payload_b = build_context_tool_payload(
        kind="view",
        tool_name="get_dashboard_context",
        source_function="local.agent_tools.get_dashboard_context",
        source_view="local.gold.gold_agent_view_context",
        parameters={"period": "2024-01", "municipio": "Manizales"},
        summary={"text": "Resumen"},
        records=records,
        metrics={"kpi_summary": {"event_count": 1}},
        traceability={"read_only": True},
    )

    assert len(payload_a["records"]) == 50
    assert payload_a["records"][0]["when"] == "2024-01-01T00:00:00"
    assert payload_a["context_hash"] == payload_b["context_hash"]
    assert payload_a["context_id"] == payload_b["context_id"]
    assert payload_a["traceability"]["read_only"] is True


def test_local_event_and_asset_context_options_share_tool_schema(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_map_files(data_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir)

    event_payload = get_chatbot_context_options(
        settings,
        context_kind="event",
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuits=["CKT-1"],
        search="viento",
        limit=10,
    )
    asset_payload = get_chatbot_context_options(
        settings,
        context_kind="asset",
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuits=["CKT-1"],
        search="TR-1",
        limit=10,
    )

    event_context = event_payload["items"][0]["context"]
    asset_context = asset_payload["items"][0]["context"]
    assert event_context["tool_name"] == "get_event_context"
    assert event_context["source_view"].endswith("gold_agent_event_context")
    assert event_context["cto_equi_ope"] == "CKT-1"
    assert event_context["records"][0]["causa"] == "VIENTO"
    assert asset_context["tool_name"] == "get_asset_context"
    assert asset_context["source_view"].endswith("gold_agent_asset_context")
    assert asset_context["CODE"] == "TR-1"
    assert asset_context["traceability"]["read_only"] is True


def test_databricks_context_options_use_governed_tools_and_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    settings = replace(
        _settings(
            tmp_path,
            data_dir,
            corpus_dir,
        ),
        data_backend="databricks_sql",
        databricks_sql_warehouse_id="warehouse",
        databricks_catalog_name="chec_dbx_demo",
        databricks_gold_schema="gold",
        chatbot_context_tools_schema="agent_tools",
    )

    class FakeClient:
        statements: list[str] = []

        def __init__(self, settings):
            self.settings = settings

        def fetch_scalar(self, statement: str, default=None):
            self.statements.append(statement)
            return json.dumps(
                {
                    "kind": "view",
                    "tool_name": "get_dashboard_context",
                    "source_function": "chec_dbx_demo.agent_tools.get_dashboard_context",
                    "source_view": "chec_dbx_demo.gold.gold_agent_view_context",
                    "parameters": {"period": "2024-01", "municipio": "Manizales", "circuits": "CKT-1"},
                    "context_hash": "hash-1",
                    "context_id": "view-hash-1",
                    "summary": {"text": "Vista gobernada"},
                    "records": [],
                    "metrics": {"kpi_summary": {"event_count": 1}},
                    "traceability": {"read_only": True},
                    "selected_period": "2024-01",
                    "selected_municipio": "Manizales",
                    "scope_label": "CKT-1",
                    "kpi_summary": {"event_count": 1, "saidi_total": 0.5, "saifi_total": 0.3},
                }
            )

        def fetch_dataframe(self, statement: str):
            self.statements.append(statement)
            return pd.DataFrame(
                [
                    {
                        "event_id": "event-1",
                        "kind": "event",
                        "map_period": "2024-01",
                        "municipio": "Manizales",
                        "circuito": "CKT-1",
                        "cto_equi_ope": "CKT-1",
                        "equipo_ope": "EQ-1",
                        "causa": "VIENTO",
                        "SAIDI": 0.5,
                        "SAIFI": 0.3,
                    }
                ]
            )

    monkeypatch.setattr(
        "chec_dashboard.services.agent_context_service.DatabricksSQLWarehouseClient",
        FakeClient,
    )

    view_payload = get_chatbot_context_options(
        settings,
        context_kind="view",
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuits=["CKT-1"],
        limit=10,
    )
    event_payload = get_chatbot_context_options(
        settings,
        context_kind="event",
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuits=["CKT-1"],
        limit=10,
    )

    statements = "\n".join(FakeClient.statements)
    assert "`chec_dbx_demo`.`agent_tools`.`get_dashboard_context`" in statements
    assert "`chec_dbx_demo`.`gold`.`gold_agent_event_context`" in statements
    assert "gold_map_event_days" not in statements
    assert "gold_saidi_saifi_daily" not in statements
    assert view_payload["items"][0]["context"]["tool_name"] == "get_dashboard_context"
    assert event_payload["items"][0]["context"]["source_function"] == "`chec_dbx_demo`.`agent_tools`.`get_event_context`"


def test_context_package_preserves_compliance_guardrails() -> None:
    package = build_chatbot_context_package(
        selected_context={"kind": "asset", "family": "Transformador", "CODE": "TR-1", "KVA": 25},
        briefing_type="compliance",
        question_id="compliance_risk_flags",
    )

    assert package["tipo_analisis"] == "compliance"
    assert package["selected_context"]["family"] == "Transformador"
    assert "aprobado/reprobado" in package["response_guardrails"]["compliance"]


def test_context_package_includes_structured_tool_output(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_map_files(data_dir)
    settings = _settings(tmp_path, data_dir, corpus_dir)
    payload = get_chatbot_context_options(
        settings,
        context_kind="view",
        selected_period="2024-01",
        selected_municipio="Manizales",
        selected_circuits=["CKT-1"],
    )

    package = build_chatbot_context_package(
        selected_context=payload["items"][0]["context"],
        briefing_type="reliability",
        question_id="reliability_saidi_saifi",
    )

    tool = package["structured_context_tool"]
    assert package["selected_context"]["tool_name"] == "get_dashboard_context"
    assert tool["source_view"].endswith("gold_agent_view_context")
    assert tool["context_hash"] == payload["items"][0]["context"]["context_hash"]
    assert tool["traceability"]["read_only"] is True


def test_local_circuit_history_tool_uses_phase4_schema(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    settings = _settings(tmp_path, data_dir, corpus_dir)

    payload = get_circuit_history_tool(
        settings,
        circuit="CKT-1",
        start_date="2024-01-01",
        end_date="2024-01-31",
    )

    assert payload["tool_name"] == "get_circuit_history"
    assert payload["source_view"].endswith("gold_agent_circuit_history")
    assert payload["parameters"]["circuit"] == "CKT-1"
    assert payload["traceability"]["read_only"] is True


@pytest.mark.parametrize(
    ("briefing_type", "question_id", "expected_text"),
    [
        ("reliability", "reliability_saidi_saifi", "confiabilidad"),
        ("compliance", "compliance_risk_flags", "Banderas de evidencia"),
        ("maintenance", "maintenance_field_checks", "mantenimiento"),
    ],
)
def test_assessment_prompt_uses_guided_analysis_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    briefing_type: str,
    question_id: str,
    expected_text: str,
) -> None:
    data_dir = tmp_path / "data"
    corpus_dir = tmp_path / "corpus"
    data_dir.mkdir()
    _write_corpus(corpus_dir)
    settings = _settings(
        tmp_path,
        data_dir,
        corpus_dir,
        chatbot_enabled=True,
        llm_provider="gemini",
        gemini_api_key="fake-key",
    )
    captured_prompt = {}

    def fake_generate(settings, prompt):
        captured_prompt["text"] = prompt
        return "Respuesta técnica en español [1]."

    monkeypatch.setattr(
        "chec_dashboard.services.llm_service._generate_gemini_answer",
        fake_generate,
    )

    payload = assess_chatbot_context(
        settings,
        selected_context={"kind": "event", "causa": "VIENTO", "cto_equi_ope": "CKT-1"},
        question=None,
        briefing_type=briefing_type,
        question_id=question_id,
    )

    assert payload["ready"] is True
    assert payload["briefing_type"] == briefing_type
    assert expected_text in captured_prompt["text"]


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
        llm_provider="gemini",
        gemini_api_key="fake-key",
    )

    monkeypatch.setattr(
        "chec_dashboard.services.llm_service._generate_gemini_answer",
        lambda settings, prompt: "Respuesta técnica en español [1].",
    )

    payload = assess_chatbot_context(
        settings,
        selected_context={"causa": "VIENTO", "cto_equi_ope": "CKT-1"},
        question=None,
    )

    assert payload["ready"] is True
    assert payload["answer"] == "Respuesta técnica en español [1]."
