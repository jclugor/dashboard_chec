#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from chec_dashboard.core.config import load_settings  # noqa: E402
from chec_dashboard.services.databricks_sql import DatabricksSQLWarehouseClient, sql_literal, sql_table_name  # noqa: E402
from chec_dashboard.services.observability_service import prompt_hash  # noqa: E402
from chec_dashboard.services.prompt_service import ANSWER_PROMPT_TEMPLATE  # noqa: E402


DEFAULT_TELEMETRY_SCHEMA = "agent_observability"
DEFAULT_MLFLOW_EXPERIMENT_NAME = "/Shared/chec_dash_parity/agent_observability"
DEFAULT_MLFLOW_PROMPT_NAME = "chec_chatbot_answer_prompt"
DEFAULT_MLFLOW_PROMPT_ALIAS = "production"


EVAL_EXAMPLES = [
    ("uiti_impact_01", "reliability", "CREG 015 impacto UITI", "UITI impact explanation", "needs_sme_review"),
    ("uiti_impact_02", "reliability", "explica UITI del circuito", "UITI impact explanation", "needs_sme_review"),
    ("uiti_impact_03", "reliability", "por que UITI vano sube", "UITI impact explanation", "needs_sme_review"),
    ("uiti_impact_04", "reliability", "calidad del servicio por municipio", "UITI impact explanation", "needs_sme_review"),
    ("uiti_impact_05", "reliability", "comparar UITI y usuarios afectados", "UITI impact explanation", "needs_sme_review"),
    ("creg_01", "compliance", "CREG 015 requisitos aplicables", "CREG/quality-service", "needs_sme_review"),
    ("creg_02", "compliance", "RETIE y red de media tensión", "CREG/quality-service", "needs_sme_review"),
    ("creg_03", "compliance", "cumplimiento técnico posible", "CREG/quality-service", "needs_sme_review"),
    ("creg_04", "compliance", "norma para interrupciones menores", "CREG/quality-service", "needs_sme_review"),
    ("creg_05", "compliance", "banderas regulatorias", "CREG/quality-service", "needs_sme_review"),
    ("maintenance_01", "maintenance", "qué revisar en campo", "Maintenance prioritization", "needs_sme_review"),
    ("maintenance_02", "maintenance", "priorizar activo seleccionado", "Maintenance prioritization", "needs_sme_review"),
    ("maintenance_03", "maintenance", "causa raíz probable", "Maintenance prioritization", "needs_sme_review"),
    ("maintenance_04", "maintenance", "acciones preventivas", "Maintenance prioritization", "needs_sme_review"),
    ("maintenance_05", "maintenance", "revisiones de cuadrilla", "Maintenance prioritization", "needs_sme_review"),
    ("missing_01", "compliance", "qué falta para decidir", "Missing evidence", "needs_sme_review"),
    ("missing_02", "maintenance", "datos faltantes del activo", "Missing evidence", "needs_sme_review"),
    ("missing_03", "reliability", "sin documentos recuperados", "Missing evidence", "needs_sme_review"),
    ("missing_04", "compliance", "no hay contexto suficiente", "Missing evidence", "needs_sme_review"),
    ("missing_05", "maintenance", "faltan mediciones de campo", "Missing evidence", "needs_sme_review"),
    ("ambiguous_01", "reliability", "qué pasó", "Ambiguous question", "needs_sme_review"),
    ("ambiguous_02", "maintenance", "revísalo", "Ambiguous question", "needs_sme_review"),
    ("ambiguous_03", "compliance", "está bien", "Ambiguous question", "needs_sme_review"),
    ("ambiguous_04", "reliability", "qué significa esto", "Ambiguous question", "needs_sme_review"),
    ("ambiguous_05", "maintenance", "qué sigue", "Ambiguous question", "needs_sme_review"),
    ("memory_01", "reliability", "historial del circuito CKT-1", "Memory follow-up", "needs_sme_review"),
    ("memory_02", "maintenance", "qué revisar en el activo seleccionado", "Memory follow-up", "needs_sme_review"),
    ("memory_03", "compliance", "con lo anterior qué requisitos aplican", "Memory follow-up", "needs_sme_review"),
    ("memory_04", "reliability", "resume la conversación", "Memory follow-up", "needs_sme_review"),
    ("memory_05", "maintenance", "mantén el mismo contexto", "Memory follow-up", "needs_sme_review"),
]


def _settings_with_app_defaults():
    os.environ.setdefault("CHATBOT_TELEMETRY_SCHEMA", DEFAULT_TELEMETRY_SCHEMA)
    os.environ.setdefault("MLFLOW_EXPERIMENT_NAME", DEFAULT_MLFLOW_EXPERIMENT_NAME)
    os.environ.setdefault("MLFLOW_PROMPT_NAME", DEFAULT_MLFLOW_PROMPT_NAME)
    os.environ.setdefault("MLFLOW_PROMPT_ALIAS", DEFAULT_MLFLOW_PROMPT_ALIAS)
    env_map = {
        "APP_WAREHOUSE_ID": "DATABRICKS_SQL_WAREHOUSE_ID",
        "APP_CATALOG_NAME": "DATABRICKS_CATALOG_NAME",
        "APP_CHATBOT_TELEMETRY_SCHEMA": "CHATBOT_TELEMETRY_SCHEMA",
        "APP_MLFLOW_TRACKING_URI": "MLFLOW_TRACKING_URI",
        "APP_MLFLOW_EXPERIMENT_NAME": "MLFLOW_EXPERIMENT_NAME",
        "APP_MLFLOW_PROMPT_NAME": "MLFLOW_PROMPT_NAME",
        "APP_MLFLOW_PROMPT_ALIAS": "MLFLOW_PROMPT_ALIAS",
    }
    for source, target in env_map.items():
        if os.getenv(source) and not os.getenv(target):
            os.environ[target] = os.environ[source]
    return load_settings()


def main() -> int:
    settings = _settings_with_app_defaults()
    client = DatabricksSQLWarehouseClient(settings)
    catalog = settings.databricks_catalog_name
    schema = settings.chatbot_telemetry_schema

    client.fetch_dataframe(f"CREATE SCHEMA IF NOT EXISTS {sql_table_name(catalog, schema)}")
    _create_tables(client, catalog, schema)
    _seed_eval_examples(client, catalog, schema)
    _register_mlflow_assets(settings)
    print(
        "Phase 9 observability is ready: "
        f"{catalog}.{schema}, {settings.mlflow_experiment_name}, "
        f"{settings.mlflow_prompt_name}@{settings.mlflow_prompt_alias}, "
        f"report_only={settings.chatbot_eval_report_only}"
    )
    return 0


def _create_tables(client: DatabricksSQLWarehouseClient, catalog: str, schema: str) -> None:
    client.fetch_dataframe(
        f"""
CREATE TABLE IF NOT EXISTS {sql_table_name(catalog, schema, "agent_turn_traces")} (
  trace_id STRING,
  conversation_id STRING,
  turn_id STRING,
  created_at TIMESTAMP,
  mode STRING,
  briefing_type STRING,
  ready BOOLEAN,
  status_text STRING,
  skill_id STRING,
  skill_hash STRING,
  context_snapshot_hash STRING,
  prompt_name STRING,
  prompt_alias STRING,
  prompt_version STRING,
  prompt_hash STRING,
  llm_provider STRING,
  llm_tier STRING,
  model_endpoint_name STRING,
  retriever_backend STRING,
  ai_search_index_name STRING,
  latency_ms BIGINT,
  citation_count BIGINT,
  retrieved_chunk_ids_json STRING,
  tool_calls_json STRING,
  validation_json STRING,
  telemetry_json STRING
) USING DELTA
""".strip()
    )
    try:
        client.fetch_dataframe(
            f"ALTER TABLE {sql_table_name(catalog, schema, 'agent_turn_traces')} ADD COLUMNS (llm_tier STRING)"
        )
    except Exception:
        pass
    client.fetch_dataframe(
        f"""
CREATE TABLE IF NOT EXISTS {sql_table_name(catalog, schema, "agent_feedback_events")} (
  feedback_id STRING,
  conversation_id STRING,
  turn_id STRING,
  rating STRING,
  comment STRING,
  created_at TIMESTAMP,
  feedback_json STRING
) USING DELTA
""".strip()
    )
    client.fetch_dataframe(
        f"""
CREATE TABLE IF NOT EXISTS {sql_table_name(catalog, schema, "agent_evaluation_examples")} (
  example_id STRING,
  briefing_type STRING,
  question STRING,
  category STRING,
  review_status STRING,
  created_at TIMESTAMP
) USING DELTA
""".strip()
    )
    client.fetch_dataframe(
        f"""
CREATE TABLE IF NOT EXISTS {sql_table_name(catalog, schema, "agent_evaluation_results")} (
  evaluation_id STRING,
  created_at TIMESTAMP,
  source STRING,
  trace_count BIGINT,
  metrics_json STRING,
  report_json STRING
) USING DELTA
""".strip()
    )
    client.fetch_dataframe(
        f"""
CREATE TABLE IF NOT EXISTS {sql_table_name(catalog, schema, "agent_release_reports")} (
  report_id STRING,
  created_at TIMESTAMP,
  release_status STRING,
  report_only BOOLEAN,
  metrics_json STRING,
  report_json STRING
) USING DELTA
""".strip()
    )


def _seed_eval_examples(client: DatabricksSQLWarehouseClient, catalog: str, schema: str) -> None:
    table_name = sql_table_name(catalog, schema, "agent_evaluation_examples")
    values = ",\n".join(
        f"({sql_literal(example_id)}, {sql_literal(briefing)}, {sql_literal(question)}, "
        f"{sql_literal(category)}, {sql_literal(review_status)}, current_timestamp())"
        for example_id, briefing, question, category, review_status in EVAL_EXAMPLES
    )
    client.fetch_dataframe(
        f"""
MERGE INTO {table_name} target
USING (
  SELECT * FROM VALUES
  {values}
  AS source(example_id, briefing_type, question, category, review_status, created_at)
) source
ON target.example_id = source.example_id
WHEN NOT MATCHED THEN INSERT (
  example_id, briefing_type, question, category, review_status, created_at
) VALUES (
  source.example_id, source.briefing_type, source.question, source.category,
  source.review_status, source.created_at
)
""".strip()
    )


def _register_mlflow_assets(settings) -> None:
    try:
        import mlflow

        _ensure_mlflow_experiment_parent(settings.mlflow_experiment_name)
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment_name)
        prompt = mlflow.genai.register_prompt(
            name=settings.mlflow_prompt_name,
            template=ANSWER_PROMPT_TEMPLATE,
            commit_message="Phase 9 governed CHEC chatbot answer prompt",
            tags={
                "project": "chec_dash_parity",
                "phase": "9",
                "prompt_hash": prompt_hash(ANSWER_PROMPT_TEMPLATE),
                "language": "es",
            },
        )
        _set_prompt_alias(settings, prompt)
    except Exception as exc:
        print(f"WARNING: MLflow assets were not registered: {exc}", file=sys.stderr)


def _ensure_mlflow_experiment_parent(experiment_name: str) -> None:
    parent_path = _workspace_parent_path(experiment_name)
    if not parent_path:
        return
    try:
        from databricks.sdk import WorkspaceClient

        WorkspaceClient().workspace.mkdirs(path=parent_path)
    except Exception as exc:
        print(f"WARNING: MLflow experiment parent directory was not created: {exc}", file=sys.stderr)


def _workspace_parent_path(experiment_name: str) -> str | None:
    compact = (experiment_name or "").strip()
    if not compact.startswith("/"):
        return None
    parent = compact.rsplit("/", 1)[0]
    if not parent or parent == compact:
        return None
    return parent


def _set_prompt_alias(settings, prompt) -> None:
    try:
        import mlflow

        client = mlflow.tracking.MlflowClient()
        if hasattr(client, "set_prompt_alias"):
            client.set_prompt_alias(settings.mlflow_prompt_name, settings.mlflow_prompt_alias, prompt.version)
    except Exception as exc:
        print(f"WARNING: MLflow prompt alias was not set: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
