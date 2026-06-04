from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _to_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_path(value: str) -> Path:
    if value.startswith("dbfs:/"):
        value = value.removeprefix("dbfs:")
    if not value.startswith("/") and value.count(".") == 2:
        catalog, schema, volume = value.split(".")
        value = f"/Volumes/{catalog}/{schema}/{volume}"
    return Path(value)


@dataclass(frozen=True)
class Settings:
    project_root: Path
    data_dir: Path
    output_dir: Path
    data_backend: str
    api_transport: str
    host: str
    port: int
    debug: bool
    api_host: str
    api_port: int
    api_reload: bool
    api_base_url: str
    environment: str
    model_backend: str
    databricks_host: str | None
    databricks_token: str | None
    databricks_model_endpoint: str | None
    databricks_sql_warehouse_id: str | None
    databricks_sql_http_path: str | None
    databricks_catalog_name: str
    databricks_gold_schema: str
    databricks_silver_schema: str
    azure_ml_endpoint: str | None
    azure_ml_key: str | None
    cache_enabled: bool
    log_level: str
    request_timeout_seconds: int
    inference_http_retries: int
    inference_retry_backoff_ms: int
    llm_provider: str
    llm_endpoint_name: str | None
    llm_max_tokens: int
    llm_temperature: float
    chatbot_enabled: bool
    gemini_api_key: str | None
    gemini_model: str
    chatbot_corpus_dir: Path
    chatbot_skills_dir: Path | None
    chatbot_conversation_backend: str
    chatbot_conversation_schema: str
    chatbot_context_tools_schema: str
    chatbot_memory_max_turns: int
    retriever_backend: str
    ai_search_endpoint_name: str
    ai_search_index_name: str | None
    ai_search_top_k: int
    ai_search_query_type: str
    ai_search_embedding_endpoint_name: str
    ai_search_endpoint_type: str
    chatbot_retrieval_top_k: int
    chatbot_max_context_chars: int
    max_summary_points: int
    max_map_html_chars: int
    api_startup_poll_seconds: int
    api_keepalive_seconds: int
    api_startup_max_attempts: int



def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    default_data_dir = (project_root / ".." / "data").resolve()
    default_output_dir = Path("/tmp/outputs")
    data_dir = Path(os.getenv("DATA_DIR", str(default_data_dir))).resolve()
    output_dir = Path(os.getenv("OUTPUT_DIR", str(default_output_dir))).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    default_chatbot_corpus_dir = (data_dir / "chatbot_corpus").resolve()
    explicit_chatbot_corpus_dir = _env_value("CHATBOT_CORPUS_DIR")
    chatbot_corpus_volume_dir = _env_value("CHATBOT_CORPUS_VOLUME_DIR")
    chatbot_corpus_subdir = (_env_value("CHATBOT_CORPUS_SUBDIR") or "chatbot_corpus").strip("/")
    explicit_chatbot_skills_dir = _env_value("CHATBOT_SKILLS_DIR")
    chatbot_skills_volume_dir = _env_value("CHATBOT_SKILLS_VOLUME_DIR")
    chatbot_skills_subdir = (_env_value("CHATBOT_SKILLS_SUBDIR") or "active").strip("/")
    prefer_volume_corpus = os.getenv("ENVIRONMENT", "").strip().lower() == "databricks_app"
    if chatbot_corpus_volume_dir and (prefer_volume_corpus or not explicit_chatbot_corpus_dir):
        volume_root = _env_path(chatbot_corpus_volume_dir)
        chatbot_corpus_dir = (volume_root / chatbot_corpus_subdir if chatbot_corpus_subdir else volume_root).resolve()
    elif explicit_chatbot_corpus_dir:
        chatbot_corpus_dir = Path(explicit_chatbot_corpus_dir).resolve()
    else:
        chatbot_corpus_dir = default_chatbot_corpus_dir
    if chatbot_skills_volume_dir and (prefer_volume_corpus or not explicit_chatbot_skills_dir):
        skills_volume_root = _env_path(chatbot_skills_volume_dir)
        chatbot_skills_dir = (skills_volume_root / chatbot_skills_subdir if chatbot_skills_subdir else skills_volume_root).resolve()
    elif explicit_chatbot_skills_dir:
        chatbot_skills_dir = Path(explicit_chatbot_skills_dir).resolve()
    else:
        chatbot_skills_dir = None

    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = _to_int(os.getenv("API_PORT"), 8000)

    return Settings(
        project_root=project_root,
        data_dir=data_dir,
        output_dir=output_dir,
        data_backend=os.getenv("DATA_BACKEND", "pickle").strip().lower(),
        api_transport=os.getenv("API_TRANSPORT", "http").strip().lower(),
        host=os.getenv("HOST", "0.0.0.0"),
        port=_to_int(os.getenv("PORT"), 8050),
        debug=_to_bool(os.getenv("DEBUG"), False),
        api_host=api_host,
        api_port=api_port,
        api_reload=_to_bool(os.getenv("API_RELOAD"), False),
        api_base_url=os.getenv("API_BASE_URL", f"http://127.0.0.1:{api_port}"),
        environment=os.getenv("ENVIRONMENT", "local"),
        model_backend=os.getenv("MODEL_BACKEND", "mock").strip().lower(),
        databricks_host=os.getenv("DATABRICKS_HOST"),
        databricks_token=os.getenv("DATABRICKS_TOKEN"),
        databricks_model_endpoint=os.getenv("DATABRICKS_MODEL_ENDPOINT"),
        databricks_sql_warehouse_id=os.getenv("DATABRICKS_SQL_WAREHOUSE_ID"),
        databricks_sql_http_path=os.getenv("DATABRICKS_SQL_HTTP_PATH"),
        databricks_catalog_name=os.getenv("DATABRICKS_CATALOG_NAME", "chec_dbx_demo"),
        databricks_gold_schema=os.getenv("DATABRICKS_GOLD_SCHEMA", "gold"),
        databricks_silver_schema=os.getenv("DATABRICKS_SILVER_SCHEMA", "silver"),
        azure_ml_endpoint=os.getenv("AZURE_ML_ENDPOINT"),
        azure_ml_key=os.getenv("AZURE_ML_KEY"),
        cache_enabled=_to_bool(os.getenv("CACHE_ENABLED"), True),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        request_timeout_seconds=_to_int(os.getenv("REQUEST_TIMEOUT_SECONDS"), 30),
        inference_http_retries=max(_to_int(os.getenv("INFERENCE_HTTP_RETRIES"), 1), 0),
        inference_retry_backoff_ms=max(_to_int(os.getenv("INFERENCE_RETRY_BACKOFF_MS"), 250), 0),
        llm_provider=os.getenv("LLM_PROVIDER", "mock").strip().lower(),
        llm_endpoint_name=_env_value("LLM_ENDPOINT_NAME"),
        llm_max_tokens=max(_to_int(os.getenv("LLM_MAX_TOKENS"), 1200), 1),
        llm_temperature=max(0.0, min(_to_float(os.getenv("LLM_TEMPERATURE"), 0.2), 2.0)),
        chatbot_enabled=_to_bool(os.getenv("CHATBOT_ENABLED"), False),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        chatbot_corpus_dir=chatbot_corpus_dir,
        chatbot_skills_dir=chatbot_skills_dir,
        chatbot_conversation_backend=os.getenv("CHATBOT_CONVERSATION_BACKEND", "memory").strip().lower(),
        chatbot_conversation_schema=os.getenv("CHATBOT_CONVERSATION_SCHEMA", "agent").strip() or "agent",
        chatbot_context_tools_schema=os.getenv("CHATBOT_CONTEXT_TOOLS_SCHEMA", "agent_tools").strip() or "agent_tools",
        chatbot_memory_max_turns=max(_to_int(os.getenv("CHATBOT_MEMORY_MAX_TURNS"), 8), 1),
        retriever_backend=os.getenv("RETRIEVER_BACKEND", "local_jsonl").strip().lower(),
        ai_search_endpoint_name=os.getenv("AI_SEARCH_ENDPOINT_NAME", "chec-agent-search").strip() or "chec-agent-search",
        ai_search_index_name=(
            _env_value("AI_SEARCH_INDEX_NAME")
            or f"{os.getenv('DATABRICKS_CATALOG_NAME', 'chec_dbx_demo')}.gold.technical_doc_chunks_current_index"
        ),
        ai_search_top_k=max(_to_int(os.getenv("AI_SEARCH_TOP_K"), 8), 1),
        ai_search_query_type=os.getenv("AI_SEARCH_QUERY_TYPE", "hybrid").strip().lower() or "hybrid",
        ai_search_embedding_endpoint_name=(
            os.getenv("AI_SEARCH_EMBEDDING_ENDPOINT_NAME", "databricks-qwen3-embedding-0-6b").strip()
            or "databricks-qwen3-embedding-0-6b"
        ),
        ai_search_endpoint_type=os.getenv("AI_SEARCH_ENDPOINT_TYPE", "STANDARD").strip().upper() or "STANDARD",
        chatbot_retrieval_top_k=max(_to_int(os.getenv("CHATBOT_RETRIEVAL_TOP_K"), 5), 1),
        chatbot_max_context_chars=max(_to_int(os.getenv("CHATBOT_MAX_CONTEXT_CHARS"), 12000), 1000),
        max_summary_points=max(_to_int(os.getenv("MAX_SUMMARY_POINTS"), 5000), 100),
        max_map_html_chars=max(_to_int(os.getenv("MAX_MAP_HTML_CHARS"), 8000000), 100000),
        api_startup_poll_seconds=max(_to_int(os.getenv("API_STARTUP_POLL_SECONDS"), 3), 1),
        api_keepalive_seconds=max(_to_int(os.getenv("API_KEEPALIVE_SECONDS"), 60), 10),
        api_startup_max_attempts=max(_to_int(os.getenv("API_STARTUP_MAX_ATTEMPTS"), 0), 0),
    )


settings = load_settings()
