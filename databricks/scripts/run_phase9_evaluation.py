#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from chec_dashboard.core.config import load_settings  # noqa: E402
from chec_dashboard.services.databricks_sql import DatabricksSQLWarehouseClient, sql_literal, sql_table_name  # noqa: E402
from chec_dashboard.services.evaluation_service import build_release_report  # noqa: E402


def _settings_with_app_defaults():
    env_map = {
        "APP_WAREHOUSE_ID": "DATABRICKS_SQL_WAREHOUSE_ID",
        "APP_CATALOG_NAME": "DATABRICKS_CATALOG_NAME",
        "APP_CHATBOT_TELEMETRY_SCHEMA": "CHATBOT_TELEMETRY_SCHEMA",
        "APP_CHATBOT_EVAL_REPORT_ONLY": "CHATBOT_EVAL_REPORT_ONLY",
        "APP_CHATBOT_EVAL_ENFORCE": "CHATBOT_EVAL_ENFORCE",
    }
    for source, target in env_map.items():
        if os.getenv(source) and not os.getenv(target):
            os.environ[target] = os.environ[source]
    return load_settings()


def main() -> int:
    settings = _settings_with_app_defaults()
    client = DatabricksSQLWarehouseClient(settings)
    traces = _load_recent_traces(client, settings)
    report = build_release_report(traces, report_only=settings.chatbot_eval_report_only)
    _write_report(client, settings, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if settings.chatbot_eval_enforce and not report["controls_passed"]:
        return 1
    return 0


def _load_recent_traces(client: DatabricksSQLWarehouseClient, settings) -> list[dict]:
    table_name = sql_table_name(settings.databricks_catalog_name, settings.chatbot_telemetry_schema, "agent_turn_traces")
    frame = client.fetch_dataframe(
        f"""
SELECT telemetry_json
FROM {table_name}
ORDER BY created_at DESC
LIMIT 100
""".strip()
    )
    traces = []
    for _, row in frame.iterrows():
        value = row.get("telemetry_json")
        if not value:
            continue
        try:
            traces.append(json.loads(str(value)))
        except json.JSONDecodeError:
            continue
    return traces


def _write_report(client: DatabricksSQLWarehouseClient, settings, report: dict) -> None:
    report_id = f"release-report-{uuid.uuid4().hex}"
    evaluation_id = f"evaluation-{uuid.uuid4().hex}"
    metrics_json = json.dumps(report["metrics"], ensure_ascii=False, sort_keys=True)
    report_json = json.dumps(report, ensure_ascii=False, sort_keys=True)
    eval_table = sql_table_name(settings.databricks_catalog_name, settings.chatbot_telemetry_schema, "agent_evaluation_results")
    release_table = sql_table_name(settings.databricks_catalog_name, settings.chatbot_telemetry_schema, "agent_release_reports")
    client.fetch_dataframe(
        f"""
INSERT INTO {eval_table} (
  evaluation_id, created_at, source, trace_count, metrics_json, report_json
) VALUES (
  {sql_literal(evaluation_id)},
  current_timestamp(),
  'agent_turn_traces',
  {sql_literal(int(report.get("trace_count") or 0))},
  {sql_literal(metrics_json)},
  {sql_literal(report_json)}
)
""".strip()
    )
    client.fetch_dataframe(
        f"""
INSERT INTO {release_table} (
  report_id, created_at, release_status, report_only, metrics_json, report_json
) VALUES (
  {sql_literal(report_id)},
  current_timestamp(),
  {sql_literal(report.get("release_status"))},
  {sql_literal(bool(report.get("report_only")))},
  {sql_literal(metrics_json)},
  {sql_literal(report_json)}
)
""".strip()
    )


if __name__ == "__main__":
    raise SystemExit(main())
