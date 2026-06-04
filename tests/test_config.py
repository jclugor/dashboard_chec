from __future__ import annotations

from pathlib import Path

from chec_dashboard.core.config import load_settings


ROOT = Path(__file__).resolve().parents[1]


def _base_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.delenv("CHATBOT_CORPUS_DIR", raising=False)
    monkeypatch.delenv("CHATBOT_CORPUS_VOLUME_DIR", raising=False)
    monkeypatch.delenv("CHATBOT_CORPUS_SUBDIR", raising=False)
    monkeypatch.delenv("CHATBOT_SKILLS_DIR", raising=False)
    monkeypatch.delenv("CHATBOT_SKILLS_VOLUME_DIR", raising=False)
    monkeypatch.delenv("CHATBOT_SKILLS_SUBDIR", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_ENDPOINT_NAME", raising=False)
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    monkeypatch.delenv("SUMMARY_INTERPRETABILITY_ENABLED", raising=False)
    monkeypatch.delenv("SUMMARY_INTERPRETABILITY_MAX_POINTS", raising=False)
    monkeypatch.delenv("SUMMARY_INTERPRETABILITY_HIGH_ROBUST_Z", raising=False)
    monkeypatch.delenv("SUMMARY_INTERPRETABILITY_LOW_ROBUST_Z", raising=False)
    monkeypatch.delenv("SUMMARY_INTERPRETABILITY_DELTA_ROBUST_Z", raising=False)
    monkeypatch.delenv("SUMMARY_INTERPRETABILITY_TOP_CONTRIBUTOR_PCT", raising=False)
    monkeypatch.delenv("SUMMARY_INTERPRETABILITY_SUSTAINED_MIN_DAYS", raising=False)
    monkeypatch.delenv("SUMMARY_INTERPRETABILITY_INCLUDE_AGENT_TEXT_DEFAULT", raising=False)
    monkeypatch.delenv("SUMMARY_INTERPRETABILITY_CACHE_SECONDS", raising=False)
    monkeypatch.delenv("RETRIEVER_BACKEND", raising=False)
    monkeypatch.delenv("AI_SEARCH_ENDPOINT_NAME", raising=False)
    monkeypatch.delenv("AI_SEARCH_INDEX_NAME", raising=False)
    monkeypatch.delenv("AI_SEARCH_TOP_K", raising=False)
    monkeypatch.delenv("AI_SEARCH_QUERY_TYPE", raising=False)
    monkeypatch.delenv("AI_SEARCH_EMBEDDING_ENDPOINT_NAME", raising=False)
    monkeypatch.delenv("AI_SEARCH_ENDPOINT_TYPE", raising=False)
    monkeypatch.delenv("CHATBOT_OBSERVABILITY_ENABLED", raising=False)
    monkeypatch.delenv("CHATBOT_TELEMETRY_SCHEMA", raising=False)
    monkeypatch.delenv("CHATBOT_EVAL_REPORT_ONLY", raising=False)
    monkeypatch.delenv("CHATBOT_EVAL_LLM_JUDGES_ENABLED", raising=False)
    monkeypatch.delenv("CHATBOT_EVAL_ENFORCE", raising=False)
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME", raising=False)
    monkeypatch.delenv("MLFLOW_PROMPT_NAME", raising=False)
    monkeypatch.delenv("MLFLOW_PROMPT_ALIAS", raising=False)


def test_explicit_chatbot_corpus_dir_has_priority(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    explicit_dir = tmp_path / "explicit-corpus"
    volume_dir = tmp_path / "volume-root"
    monkeypatch.setenv("CHATBOT_CORPUS_DIR", str(explicit_dir))
    monkeypatch.setenv("CHATBOT_CORPUS_VOLUME_DIR", str(volume_dir))
    monkeypatch.setenv("CHATBOT_CORPUS_SUBDIR", "chatbot_corpus")

    settings = load_settings()

    assert settings.chatbot_corpus_dir == explicit_dir.resolve()


def test_databricks_volume_resource_has_priority_over_legacy_explicit_dir(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    explicit_dir = tmp_path / "legacy-packaged-corpus"
    volume_dir = tmp_path / "volume-root"
    monkeypatch.setenv("ENVIRONMENT", "databricks_app")
    monkeypatch.setenv("CHATBOT_CORPUS_DIR", str(explicit_dir))
    monkeypatch.setenv("CHATBOT_CORPUS_VOLUME_DIR", str(volume_dir))
    monkeypatch.setenv("CHATBOT_CORPUS_SUBDIR", "chatbot_corpus")

    settings = load_settings()

    assert settings.chatbot_corpus_dir == (volume_dir / "chatbot_corpus").resolve()


def test_databricks_volume_resource_accepts_dbfs_prefix(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "databricks_app")
    monkeypatch.setenv("CHATBOT_CORPUS_VOLUME_DIR", "dbfs:/Volumes/chec_dbx_demo/raw/source_files")
    monkeypatch.setenv("CHATBOT_CORPUS_SUBDIR", "chatbot_corpus")

    settings = load_settings()

    assert settings.chatbot_corpus_dir == Path("/Volumes/chec_dbx_demo/raw/source_files/chatbot_corpus")


def test_databricks_volume_resource_accepts_uc_full_name(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "databricks_app")
    monkeypatch.setenv("CHATBOT_CORPUS_VOLUME_DIR", "chec_dbx_demo.raw.source_files")
    monkeypatch.setenv("CHATBOT_CORPUS_SUBDIR", "chatbot_corpus")

    settings = load_settings()

    assert settings.chatbot_corpus_dir == Path("/Volumes/chec_dbx_demo/raw/source_files/chatbot_corpus")


def test_chatbot_corpus_dir_resolves_from_volume_resource(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    volume_dir = tmp_path / "volume-root"
    monkeypatch.setenv("CHATBOT_CORPUS_VOLUME_DIR", str(volume_dir))
    monkeypatch.setenv("CHATBOT_CORPUS_SUBDIR", "nested/corpus")

    settings = load_settings()

    assert settings.chatbot_corpus_dir == (volume_dir / "nested" / "corpus").resolve()


def test_chatbot_corpus_dir_uses_local_default(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    data_dir = tmp_path / "data"

    settings = load_settings()

    assert settings.chatbot_corpus_dir == (data_dir / "chatbot_corpus").resolve()
    assert settings.chatbot_skills_dir is None


def test_chatbot_skills_dir_resolves_from_explicit_dir(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    skill_dir = tmp_path / "skills" / "active"
    monkeypatch.setenv("CHATBOT_SKILLS_DIR", str(skill_dir))

    settings = load_settings()

    assert settings.chatbot_skills_dir == skill_dir.resolve()


def test_chatbot_skills_volume_resource_accepts_uc_full_name(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "databricks_app")
    monkeypatch.setenv("CHATBOT_SKILLS_VOLUME_DIR", "chec_dbx_demo.agent_config.skills")
    monkeypatch.setenv("CHATBOT_SKILLS_SUBDIR", "active")

    settings = load_settings()

    assert settings.chatbot_skills_dir == Path("/Volumes/chec_dbx_demo/agent_config/skills/active")


def test_llm_provider_defaults_to_mock(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)

    settings = load_settings()

    assert settings.llm_provider == "mock"
    assert settings.llm_endpoint_name is None


def test_llm_provider_env_overrides(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "databricks_model_serving")
    monkeypatch.setenv("LLM_ENDPOINT_NAME", "chec-agent-demo")
    monkeypatch.setenv("LLM_MAX_TOKENS", "900")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.35")

    settings = load_settings()

    assert settings.llm_provider == "databricks_model_serving"
    assert settings.llm_endpoint_name == "chec-agent-demo"
    assert settings.llm_max_tokens == 900
    assert settings.llm_temperature == 0.35


def test_phase5_retriever_env_defaults_and_overrides(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)

    settings = load_settings()

    assert settings.retriever_backend == "local_jsonl"
    assert settings.ai_search_endpoint_name == "chec-agent-search"
    assert settings.ai_search_index_name == "chec_dbx_demo.gold.technical_doc_chunks_current_index"
    assert settings.ai_search_top_k == 8
    assert settings.ai_search_query_type == "hybrid"
    assert settings.ai_search_embedding_endpoint_name == "databricks-qwen3-embedding-0-6b"
    assert settings.ai_search_endpoint_type == "STANDARD"

    monkeypatch.setenv("RETRIEVER_BACKEND", "databricks_ai_search")
    monkeypatch.setenv("AI_SEARCH_ENDPOINT_NAME", "custom-search")
    monkeypatch.setenv("AI_SEARCH_INDEX_NAME", "cat.gold.idx")
    monkeypatch.setenv("AI_SEARCH_TOP_K", "11")
    monkeypatch.setenv("AI_SEARCH_QUERY_TYPE", "ann")
    monkeypatch.setenv("AI_SEARCH_EMBEDDING_ENDPOINT_NAME", "databricks-gte-large-en")
    monkeypatch.setenv("AI_SEARCH_ENDPOINT_TYPE", "storage_optimized")

    settings = load_settings()

    assert settings.retriever_backend == "databricks_ai_search"
    assert settings.ai_search_endpoint_name == "custom-search"
    assert settings.ai_search_index_name == "cat.gold.idx"
    assert settings.ai_search_top_k == 11
    assert settings.ai_search_query_type == "ann"
    assert settings.ai_search_embedding_endpoint_name == "databricks-gte-large-en"
    assert settings.ai_search_endpoint_type == "STORAGE_OPTIMIZED"


def test_summary_interpretability_env_defaults_and_overrides(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)

    settings = load_settings()

    assert settings.summary_interpretability_enabled is True
    assert settings.summary_interpretability_max_points == 5
    assert settings.summary_interpretability_high_robust_z == 3.0
    assert settings.summary_interpretability_low_robust_z == -2.5
    assert settings.summary_interpretability_delta_robust_z == 3.0
    assert settings.summary_interpretability_top_contributor_pct == 0.10
    assert settings.summary_interpretability_sustained_min_days == 3
    assert settings.summary_interpretability_include_agent_text_default is True
    assert settings.summary_interpretability_cache_seconds == 300

    monkeypatch.setenv("SUMMARY_INTERPRETABILITY_ENABLED", "false")
    monkeypatch.setenv("SUMMARY_INTERPRETABILITY_MAX_POINTS", "8")
    monkeypatch.setenv("SUMMARY_INTERPRETABILITY_HIGH_ROBUST_Z", "2.7")
    monkeypatch.setenv("SUMMARY_INTERPRETABILITY_LOW_ROBUST_Z", "-2.1")
    monkeypatch.setenv("SUMMARY_INTERPRETABILITY_DELTA_ROBUST_Z", "2.4")
    monkeypatch.setenv("SUMMARY_INTERPRETABILITY_TOP_CONTRIBUTOR_PCT", "0.2")
    monkeypatch.setenv("SUMMARY_INTERPRETABILITY_SUSTAINED_MIN_DAYS", "4")
    monkeypatch.setenv("SUMMARY_INTERPRETABILITY_INCLUDE_AGENT_TEXT_DEFAULT", "false")
    monkeypatch.setenv("SUMMARY_INTERPRETABILITY_CACHE_SECONDS", "60")

    settings = load_settings()

    assert settings.summary_interpretability_enabled is False
    assert settings.summary_interpretability_max_points == 8
    assert settings.summary_interpretability_high_robust_z == 2.7
    assert settings.summary_interpretability_low_robust_z == -2.1
    assert settings.summary_interpretability_delta_robust_z == 2.4
    assert settings.summary_interpretability_top_contributor_pct == 0.2
    assert settings.summary_interpretability_sustained_min_days == 4
    assert settings.summary_interpretability_include_agent_text_default is False
    assert settings.summary_interpretability_cache_seconds == 60


def test_phase9_observability_env_defaults_and_overrides(monkeypatch, tmp_path: Path) -> None:
    _base_env(monkeypatch, tmp_path)

    settings = load_settings()

    assert settings.chatbot_observability_enabled is False
    assert settings.chatbot_telemetry_schema == "agent_observability"
    assert settings.chatbot_eval_report_only is True
    assert settings.chatbot_eval_llm_judges_enabled is False
    assert settings.chatbot_eval_enforce is False
    assert settings.mlflow_tracking_uri == "databricks"
    assert settings.mlflow_experiment_name == "/Shared/chec_dash_parity/agent_observability"
    assert settings.mlflow_prompt_name == "chec_chatbot_answer_prompt"
    assert settings.mlflow_prompt_alias == "production"

    monkeypatch.setenv("CHATBOT_OBSERVABILITY_ENABLED", "true")
    monkeypatch.setenv("CHATBOT_TELEMETRY_SCHEMA", "agent_obs_test")
    monkeypatch.setenv("CHATBOT_EVAL_REPORT_ONLY", "false")
    monkeypatch.setenv("CHATBOT_EVAL_LLM_JUDGES_ENABLED", "true")
    monkeypatch.setenv("CHATBOT_EVAL_ENFORCE", "true")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "file:///tmp/mlruns")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "/Shared/custom/agent")
    monkeypatch.setenv("MLFLOW_PROMPT_NAME", "custom_prompt")
    monkeypatch.setenv("MLFLOW_PROMPT_ALIAS", "staging")

    settings = load_settings()

    assert settings.chatbot_observability_enabled is True
    assert settings.chatbot_telemetry_schema == "agent_obs_test"
    assert settings.chatbot_eval_report_only is False
    assert settings.chatbot_eval_llm_judges_enabled is True
    assert settings.chatbot_eval_enforce is True
    assert settings.mlflow_tracking_uri == "file:///tmp/mlruns"
    assert settings.mlflow_experiment_name == "/Shared/custom/agent"
    assert settings.mlflow_prompt_name == "custom_prompt"
    assert settings.mlflow_prompt_alias == "staging"


def test_phase0_decision_record_locks_demo_defaults() -> None:
    text = (ROOT / "docs" / "databricks_agentic_rag_phase0_decisions.md").read_text(encoding="utf-8")

    assert "Databricks Apps app authorization" in text
    assert "read-only" in text
    assert "bounded agentic RAG" in text
    assert "possible-risk" in text
    assert "LLM_PROVIDER=mock" in text
