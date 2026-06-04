#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from chec_dashboard.core.config import load_settings  # noqa: E402
from chec_dashboard.services.databricks_sql import DatabricksSQLWarehouseClient, sql_literal, sql_table_name  # noqa: E402


DEFAULT_SOURCE_VOLUME_NAME = "source_files"
DEFAULT_AI_SEARCH_ENDPOINT_NAME = "chec-agent-search"
DEFAULT_AI_SEARCH_INDEX_NAME = "technical_doc_chunks_current_index"
DEFAULT_AI_SEARCH_EMBEDDING_ENDPOINT_NAME = "databricks-qwen3-embedding-0-6b"
DEFAULT_AI_SEARCH_ENDPOINT_TYPE = "STANDARD"
DEFAULT_AI_SEARCH_QUERY_TYPE = "hybrid"
DELTA_SYNC_MODE = "TRIGGERED"
SILVER_TABLE_DISPLAY_NAME = "silver.technical_doc_chunks"
GOLD_TABLE_DISPLAY_NAME = "gold.technical_doc_chunks_current"
DEFAULT_INDEX_READY_TIMEOUT_SECONDS = 1800

TECHNICAL_DOC_COLUMNS = [
    "chunk_id",
    "document_id",
    "document_title",
    "document_type",
    "source_path",
    "source_uri",
    "page",
    "section_title",
    "section_number",
    "effective_date",
    "version",
    "jurisdiction",
    "topic_tags",
    "analysis_tags",
    "authority_level",
    "text",
    "text_hash",
    "created_at",
]


def _settings_with_app_defaults():
    if os.getenv("APP_WAREHOUSE_ID") and not os.getenv("DATABRICKS_SQL_WAREHOUSE_ID"):
        os.environ["DATABRICKS_SQL_WAREHOUSE_ID"] = os.environ["APP_WAREHOUSE_ID"]
    if os.getenv("APP_CATALOG_NAME") and not os.getenv("DATABRICKS_CATALOG_NAME"):
        os.environ["DATABRICKS_CATALOG_NAME"] = os.environ["APP_CATALOG_NAME"]
    if os.getenv("APP_AI_SEARCH_INDEX_FULL_NAME") and not os.getenv("AI_SEARCH_INDEX_NAME"):
        os.environ["AI_SEARCH_INDEX_NAME"] = os.environ["APP_AI_SEARCH_INDEX_FULL_NAME"]
    if os.getenv("APP_AI_SEARCH_ENDPOINT_NAME") and not os.getenv("AI_SEARCH_ENDPOINT_NAME"):
        os.environ["AI_SEARCH_ENDPOINT_NAME"] = os.environ["APP_AI_SEARCH_ENDPOINT_NAME"]
    if os.getenv("APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME") and not os.getenv("AI_SEARCH_EMBEDDING_ENDPOINT_NAME"):
        os.environ["AI_SEARCH_EMBEDDING_ENDPOINT_NAME"] = os.environ["APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME"]
    if os.getenv("APP_AI_SEARCH_ENDPOINT_TYPE") and not os.getenv("AI_SEARCH_ENDPOINT_TYPE"):
        os.environ["AI_SEARCH_ENDPOINT_TYPE"] = os.environ["APP_AI_SEARCH_ENDPOINT_TYPE"]
    if os.getenv("APP_AI_SEARCH_QUERY_TYPE") and not os.getenv("AI_SEARCH_QUERY_TYPE"):
        os.environ["AI_SEARCH_QUERY_TYPE"] = os.environ["APP_AI_SEARCH_QUERY_TYPE"]
    return load_settings()


def _source_volume_name() -> str:
    return os.getenv("APP_SOURCE_VOLUME_NAME") or os.getenv("SOURCE_VOLUME_NAME") or DEFAULT_SOURCE_VOLUME_NAME


def _ai_search_index_name(catalog: str) -> str:
    return (
        os.getenv("APP_AI_SEARCH_INDEX_FULL_NAME")
        or os.getenv("AI_SEARCH_INDEX_NAME")
        or f"{catalog}.gold.{DEFAULT_AI_SEARCH_INDEX_NAME}"
    )


def _run_cli(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["databricks", *args]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{message}")
    return result


def _cli_json(args: list[str]) -> dict[str, Any] | list[Any] | None:
    result = _run_cli([*args, "-o", "json"], check=False)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None


def _create_silver_table_sql(*, catalog: str, silver_schema: str, source_volume_name: str) -> str:
    table_ref = sql_table_name(catalog, silver_schema, "technical_doc_chunks")
    corpus_path = f"/Volumes/{catalog}/raw/{source_volume_name}/chatbot_corpus/chunks.jsonl"
    documents_path = f"/Volumes/{catalog}/raw/{source_volume_name}/chatbot_documents"
    return f"""
CREATE OR REPLACE TABLE {table_ref}
TBLPROPERTIES (delta.enableChangeDataFeed = true)
AS
SELECT
  CAST(chunk_id AS STRING) AS chunk_id,
  CAST(document_id AS STRING) AS document_id,
  CAST(document_title AS STRING) AS document_title,
  COALESCE(CAST(source_type AS STRING), 'technical_document') AS document_type,
  CAST(source_path AS STRING) AS source_path,
  CASE
    WHEN CAST(source_path AS STRING) LIKE '/Volumes/%' THEN CAST(source_path AS STRING)
    WHEN CAST(source_path AS STRING) LIKE 'dbfs:/%' THEN regexp_replace(CAST(source_path AS STRING), '^dbfs:', '')
    WHEN CAST(source_path AS STRING) LIKE '%arbol_decision_recomendaciones/%'
      THEN concat({sql_literal(documents_path)}, '/', regexp_extract(CAST(source_path AS STRING), 'arbol_decision_recomendaciones/(.*)$', 1))
    ELSE concat({sql_literal(documents_path)}, '/', regexp_extract(CAST(source_path AS STRING), '[^/]+$', 0))
  END AS source_uri,
  CAST(page AS INT) AS page,
  CAST(NULL AS STRING) AS section_title,
  CAST(NULL AS STRING) AS section_number,
  CAST(NULL AS DATE) AS effective_date,
  CAST(NULL AS STRING) AS version,
  CAST('CO' AS STRING) AS jurisdiction,
  CAST(tags AS ARRAY<STRING>) AS topic_tags,
  CAST(array() AS ARRAY<STRING>) AS analysis_tags,
  CASE
    WHEN lower(COALESCE(CAST(source_type AS STRING), '')) = 'pdf' THEN 'normative_or_technical_document'
    WHEN lower(COALESCE(CAST(source_type AS STRING), '')) = 'xlsx' THEN 'metadata_workbook'
    ELSE 'technical_document'
  END AS authority_level,
  CAST(text AS STRING) AS text,
  sha2(CAST(text AS STRING), 256) AS text_hash,
  current_timestamp() AS created_at
FROM read_files({sql_literal(corpus_path)}, format => 'json')
WHERE text IS NOT NULL
  AND length(trim(CAST(text AS STRING))) > 0
  AND chunk_id IS NOT NULL
"""


def _create_gold_table_sql(*, catalog: str, silver_schema: str, gold_schema: str) -> str:
    source_ref = sql_table_name(catalog, silver_schema, "technical_doc_chunks")
    target_ref = sql_table_name(catalog, gold_schema, "technical_doc_chunks_current")
    columns_csv = ", ".join(TECHNICAL_DOC_COLUMNS)
    return f"""
CREATE OR REPLACE TABLE {target_ref}
TBLPROPERTIES (delta.enableChangeDataFeed = true)
AS
WITH ranked AS (
  SELECT
    {columns_csv},
    row_number() OVER (PARTITION BY chunk_id ORDER BY created_at DESC, text_hash DESC) AS row_number
  FROM {source_ref}
)
SELECT {columns_csv}
FROM ranked
WHERE row_number = 1
"""


def _ensure_endpoint(endpoint_name: str, endpoint_type: str) -> None:
    existing = _cli_json(["vector-search-endpoints", "get-endpoint", endpoint_name])
    if existing:
        return
    _run_cli(["vector-search-endpoints", "create-endpoint", endpoint_name, endpoint_type])


def _ensure_index(
    *,
    endpoint_name: str,
    index_name: str,
    source_table_name: str,
    embedding_endpoint_name: str,
    query_type: str,
) -> None:
    existing = _cli_json(["vector-search-indexes", "get-index", index_name])
    if existing:
        return
    index_subtype = "HYBRID" if query_type.lower() == "hybrid" else "VECTOR"
    body = {
        "name": index_name,
        "endpoint_name": endpoint_name,
        "primary_key": "chunk_id",
        "index_type": "DELTA_SYNC",
        "index_subtype": index_subtype,
        "delta_sync_index_spec": {
            "source_table": source_table_name,
            "pipeline_type": DELTA_SYNC_MODE,
            "embedding_source_columns": [
                {
                    "name": "text",
                    "embedding_model_endpoint_name": embedding_endpoint_name,
                }
            ],
            "columns_to_sync": TECHNICAL_DOC_COLUMNS,
        }
    }
    _run_cli(
        [
            "vector-search-indexes",
            "create-index",
            "--json",
            json.dumps(body),
        ]
    )


def _sync_index(index_name: str) -> None:
    result = _run_cli(["vector-search-indexes", "sync-index", index_name], check=False)
    if result.returncode == 0:
        return
    message = (result.stderr or result.stdout or "").strip()
    if "Pipeline is in state RUNNING" in message:
        print(f"AI Search index {index_name} sync is already running.", flush=True)
        return
    raise RuntimeError(f"Command failed: databricks vector-search-indexes sync-index {index_name}\n{message}")


def _wait_for_index_ready(index_name: str) -> dict[str, Any]:
    timeout_seconds = int(os.getenv("APP_AI_SEARCH_INDEX_READY_TIMEOUT_SECONDS", DEFAULT_INDEX_READY_TIMEOUT_SECONDS))
    deadline = time.time() + max(timeout_seconds, 1)
    status_payload: dict[str, Any] = {}
    while time.time() < deadline:
        index_payload = _cli_json(["vector-search-indexes", "get-index", index_name]) or {}
        status_payload = index_payload.get("status") or {}
        if status_payload.get("ready") is True:
            return index_payload if isinstance(index_payload, dict) else {}
        message = status_payload.get("message") or "waiting for AI Search index readiness"
        print(f"Waiting for AI Search index {index_name}: {message}", flush=True)
        time.sleep(20)
    raise TimeoutError(f"AI Search index {index_name} was not ready within {timeout_seconds} seconds: {status_payload}")


def main() -> int:
    settings = _settings_with_app_defaults()
    catalog = settings.databricks_catalog_name
    silver_schema = settings.databricks_silver_schema
    gold_schema = settings.databricks_gold_schema
    source_volume_name = _source_volume_name()
    endpoint_name = os.getenv("APP_AI_SEARCH_ENDPOINT_NAME") or settings.ai_search_endpoint_name or DEFAULT_AI_SEARCH_ENDPOINT_NAME
    endpoint_type = (os.getenv("APP_AI_SEARCH_ENDPOINT_TYPE") or settings.ai_search_endpoint_type or DEFAULT_AI_SEARCH_ENDPOINT_TYPE).upper()
    index_name = _ai_search_index_name(catalog)
    embedding_endpoint_name = (
        os.getenv("APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME")
        or settings.ai_search_embedding_endpoint_name
        or DEFAULT_AI_SEARCH_EMBEDDING_ENDPOINT_NAME
    )
    query_type = os.getenv("APP_AI_SEARCH_QUERY_TYPE") or settings.ai_search_query_type or DEFAULT_AI_SEARCH_QUERY_TYPE

    client = DatabricksSQLWarehouseClient(settings)
    client.fetch_dataframe(f"CREATE SCHEMA IF NOT EXISTS {sql_table_name(catalog, silver_schema)}")
    client.fetch_dataframe(f"CREATE SCHEMA IF NOT EXISTS {sql_table_name(catalog, gold_schema)}")
    client.fetch_dataframe(
        _create_silver_table_sql(
            catalog=catalog,
            silver_schema=silver_schema,
            source_volume_name=source_volume_name,
        )
    )
    client.fetch_dataframe(_create_gold_table_sql(catalog=catalog, silver_schema=silver_schema, gold_schema=gold_schema))

    source_table_name = f"{catalog}.{gold_schema}.technical_doc_chunks_current"
    _ensure_endpoint(endpoint_name, endpoint_type)
    _ensure_index(
        endpoint_name=endpoint_name,
        index_name=index_name,
        source_table_name=source_table_name,
        embedding_endpoint_name=embedding_endpoint_name,
        query_type=query_type,
    )
    _wait_for_index_ready(index_name)
    _sync_index(index_name)
    index_status = _cli_json(["vector-search-indexes", "get-index", index_name]) or {}
    print(
        "Phase 5 AI Search corpus is ready: "
        f"{catalog}.{silver_schema}.technical_doc_chunks, {source_table_name}, "
        f"{endpoint_name}, {index_name}, {DELTA_SYNC_MODE}, "
        f"{embedding_endpoint_name}, {query_type}. Status: {json.dumps(index_status.get('status', {}), sort_keys=True)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
