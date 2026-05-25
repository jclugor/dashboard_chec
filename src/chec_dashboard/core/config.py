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
        max_summary_points=max(_to_int(os.getenv("MAX_SUMMARY_POINTS"), 5000), 100),
        max_map_html_chars=max(_to_int(os.getenv("MAX_MAP_HTML_CHARS"), 8000000), 100000),
        api_startup_poll_seconds=max(_to_int(os.getenv("API_STARTUP_POLL_SECONDS"), 3), 1),
        api_keepalive_seconds=max(_to_int(os.getenv("API_KEEPALIVE_SECONDS"), 60), 10),
        api_startup_max_attempts=max(_to_int(os.getenv("API_STARTUP_MAX_ATTEMPTS"), 0), 0),
    )


settings = load_settings()
