#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from chec_dashboard.core.config import load_settings  # noqa: E402
from chec_dashboard.services.databricks_sql import DatabricksSQLWarehouseClient, sql_table_name  # noqa: E402


MESSAGE_TRACE_COLUMNS = {
    "agent_tool_calls_json": "STRING",
    "agent_skipped_tools_json": "STRING",
    "agent_route_summary_json": "STRING",
    "structured_answer_json": "STRING",
    "answer_validation_json": "STRING",
    "citation_validation_json": "STRING",
    "compliance_validation_json": "STRING",
    "prompt_name": "STRING",
    "prompt_alias": "STRING",
    "prompt_version": "STRING",
    "prompt_hash": "STRING",
    "mlflow_trace_id": "STRING",
    "mlflow_run_id": "STRING",
    "latency_ms": "BIGINT",
}


def _settings_with_app_defaults():
    if os.getenv("APP_WAREHOUSE_ID") and not os.getenv("DATABRICKS_SQL_WAREHOUSE_ID"):
        os.environ["DATABRICKS_SQL_WAREHOUSE_ID"] = os.environ["APP_WAREHOUSE_ID"]
    if os.getenv("APP_CATALOG_NAME") and not os.getenv("DATABRICKS_CATALOG_NAME"):
        os.environ["DATABRICKS_CATALOG_NAME"] = os.environ["APP_CATALOG_NAME"]
    if os.getenv("APP_CHATBOT_CONVERSATION_SCHEMA") and not os.getenv("CHATBOT_CONVERSATION_SCHEMA"):
        os.environ["CHATBOT_CONVERSATION_SCHEMA"] = os.environ["APP_CHATBOT_CONVERSATION_SCHEMA"]
    return load_settings()


def main() -> int:
    settings = _settings_with_app_defaults()
    client = DatabricksSQLWarehouseClient(settings)
    catalog = settings.databricks_catalog_name
    schema = settings.chatbot_conversation_schema

    client.fetch_dataframe(f"CREATE SCHEMA IF NOT EXISTS {sql_table_name(catalog, schema)}")
    client.fetch_dataframe(
        f"""
CREATE TABLE IF NOT EXISTS {sql_table_name(catalog, schema, "agent_conversations")} (
  conversation_id STRING,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  mode STRING,
  briefing_type STRING,
  title STRING,
  context_snapshot_json STRING,
  skill_id STRING,
  skill_version STRING,
  skill_hash STRING,
  llm_provider STRING,
  model_endpoint_name STRING
) USING DELTA
""".strip()
    )
    client.fetch_dataframe(
        f"""
CREATE TABLE IF NOT EXISTS {sql_table_name(catalog, schema, "agent_messages")} (
  conversation_id STRING,
  turn_id STRING,
  role STRING,
  content STRING,
  created_at TIMESTAMP,
  briefing_type STRING,
  question_id STRING,
  skill_id STRING,
  skill_version STRING,
  skill_hash STRING,
  trace_id STRING,
  llm_provider STRING,
  model_endpoint_name STRING,
  citations_json STRING,
  retrieved_chunk_ids_json STRING,
  status_text STRING,
  ready BOOLEAN,
  agent_tool_calls_json STRING,
  agent_skipped_tools_json STRING,
  agent_route_summary_json STRING,
  structured_answer_json STRING,
  answer_validation_json STRING,
  citation_validation_json STRING,
  compliance_validation_json STRING,
  prompt_name STRING,
  prompt_alias STRING,
  prompt_version STRING,
  prompt_hash STRING,
  mlflow_trace_id STRING,
  mlflow_run_id STRING,
  latency_ms BIGINT
) USING DELTA
""".strip()
    )
    messages_table = sql_table_name(catalog, schema, "agent_messages")
    existing_columns = _table_columns(client, messages_table)
    missing_columns = {
        column_name: column_type
        for column_name, column_type in MESSAGE_TRACE_COLUMNS.items()
        if column_name.lower() not in existing_columns
    }
    if missing_columns:
        column_sql = ", ".join(f"{column_name} {column_type}" for column_name, column_type in missing_columns.items())
        client.fetch_dataframe(f"ALTER TABLE {messages_table} ADD COLUMNS ({column_sql})")
    client.fetch_dataframe(
        f"""
CREATE TABLE IF NOT EXISTS {sql_table_name(catalog, schema, "agent_feedback")} (
  feedback_id STRING,
  conversation_id STRING,
  turn_id STRING,
  rating STRING,
  comment STRING,
  created_at TIMESTAMP
) USING DELTA
""".strip()
    )
    print(f"Phase 3 conversation tables are ready in {catalog}.{schema}")
    return 0


def _table_columns(client: DatabricksSQLWarehouseClient, table_name: str) -> set[str]:
    frame = client.fetch_dataframe(f"DESCRIBE TABLE {table_name}")
    if frame.empty:
        return set()
    column_field = "col_name" if "col_name" in frame.columns else frame.columns[0]
    return {
        str(value).strip().lower()
        for value in frame[column_field].tolist()
        if str(value).strip() and not str(value).startswith("#")
    }


if __name__ == "__main__":
    raise SystemExit(main())
