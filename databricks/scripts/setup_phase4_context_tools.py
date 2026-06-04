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


AGENT_CONTEXT_VIEWS = (
    "gold_agent_view_context",
    "gold_agent_event_context",
    "gold_agent_asset_context",
    "gold_agent_circuit_history",
    "gold_timeseries_event_details",
    "gold_timeseries_daily_attribution",
    "gold_timeseries_environment_daily",
)

AGENT_CONTEXT_FUNCTIONS = (
    "get_dashboard_context",
    "get_reliability_summary",
    "get_compliance_context",
    "get_event_context",
    "get_asset_context",
    "get_circuit_history",
    "get_timeseries_interpretability_context",
)

DEFAULT_CONTEXT_TOOLS_SCHEMA = "agent_tools"


def _settings_with_app_defaults():
    if os.getenv("APP_WAREHOUSE_ID") and not os.getenv("DATABRICKS_SQL_WAREHOUSE_ID"):
        os.environ["DATABRICKS_SQL_WAREHOUSE_ID"] = os.environ["APP_WAREHOUSE_ID"]
    if os.getenv("APP_CATALOG_NAME") and not os.getenv("DATABRICKS_CATALOG_NAME"):
        os.environ["DATABRICKS_CATALOG_NAME"] = os.environ["APP_CATALOG_NAME"]
    if os.getenv("APP_CHATBOT_CONTEXT_TOOLS_SCHEMA") and not os.getenv("CHATBOT_CONTEXT_TOOLS_SCHEMA"):
        os.environ["CHATBOT_CONTEXT_TOOLS_SCHEMA"] = os.environ["APP_CHATBOT_CONTEXT_TOOLS_SCHEMA"]
    if not os.getenv("CHATBOT_CONTEXT_TOOLS_SCHEMA"):
        os.environ["CHATBOT_CONTEXT_TOOLS_SCHEMA"] = DEFAULT_CONTEXT_TOOLS_SCHEMA
    return load_settings()


def _dashboard_context_function_sql(
    *,
    function_name: str,
    catalog: str,
    tools_schema: str,
    gold_schema: str,
) -> str:
    function_ref = sql_table_name(catalog, tools_schema, function_name)
    view_ref = sql_table_name(catalog, gold_schema, "gold_agent_view_context")
    source_function = f"{catalog}.{tools_schema}.{function_name}"
    source_view = f"{catalog}.{gold_schema}.gold_agent_view_context"
    return f"""
CREATE OR REPLACE FUNCTION {function_ref}(period_arg STRING, municipio_arg STRING, circuits_arg STRING)
RETURNS STRING
LANGUAGE SQL
RETURN
WITH filtered AS (
  SELECT *
  FROM {view_ref}
  WHERE map_period = period_arg
    AND municipio = municipio_arg
    AND (
      circuits_arg IS NULL
      OR circuits_arg = ''
      OR lower(circuits_arg) = 'todos'
      OR array_contains(split(regexp_replace(circuits_arg, '\\\\s+', ''), ','), circuito)
    )
),
limited_records AS (
  SELECT *
  FROM filtered
  ORDER BY saidi_total + saifi_total DESC, event_count DESC, duration_total_h DESC
  LIMIT 25
),
records_agg AS (
  SELECT collect_list(named_struct(
    'record_type', 'reliability_daily',
    'period', map_period,
    'municipio', municipio,
    'circuito', circuito,
    'event_family', event_family,
    'event_count', event_count,
    'saidi', saidi_total,
    'saifi', saifi_total,
    'duration_h', duration_total_h,
    'users_affected', users_affected_total
  )) AS records
  FROM limited_records
),
metrics AS (
  SELECT
    coalesce(sum(event_count), 0) AS event_count,
    coalesce(round(sum(saidi_total), 4), 0.0D) AS saidi_total,
    coalesce(round(sum(saifi_total), 4), 0.0D) AS saifi_total,
    coalesce(round(sum(duration_total_h), 2), 0.0D) AS duration_total_h,
    coalesce(sum(users_affected_total), 0) AS users_affected_total,
    cast(min(first_event_ts) AS STRING) AS first_event_ts,
    cast(max(last_event_ts) AS STRING) AS last_event_ts
  FROM filtered
),
payload AS (
  SELECT
    substr(sha2(concat_ws('|',
      {sql_literal(function_name)},
      coalesce(period_arg, ''),
      coalesce(municipio_arg, ''),
      coalesce(circuits_arg, ''),
      cast(event_count AS STRING),
      cast(saidi_total AS STRING),
      cast(saifi_total AS STRING)
    ), 256), 1, 16) AS context_hash,
    *
  FROM metrics
)
SELECT to_json(named_struct(
  'kind', 'view',
  'tool_name', {sql_literal(function_name)},
  'source_function', {sql_literal(source_function)},
  'source_view', {sql_literal(source_view)},
  'parameters', named_struct('period', period_arg, 'municipio', municipio_arg, 'circuits', circuits_arg),
  'context_hash', context_hash,
  'context_id', concat('view-', context_hash),
  'summary', named_struct(
    'text', concat('Vista ', municipio_arg, ' / ', period_arg, ' / ', coalesce(nullif(circuits_arg, ''), 'Todos'), '. Eventos: ', cast(event_count AS STRING), ', SAIDI: ', cast(saidi_total AS STRING), ', SAIFI: ', cast(saifi_total AS STRING), '.'),
    'selected_period', period_arg,
    'selected_municipio', municipio_arg,
    'scope_label', coalesce(nullif(circuits_arg, ''), 'Todos')
  ),
  'records', coalesce(records_agg.records, array()),
  'metrics', named_struct(
    'kpi_summary', named_struct(
      'event_count', event_count,
      'saidi_total', saidi_total,
      'saifi_total', saifi_total,
      'duration_total_h', duration_total_h,
      'users_affected_total', users_affected_total
    ),
    'date_bounds', named_struct('start', first_event_ts, 'end', last_event_ts)
  ),
  'traceability', named_struct('source_view', {sql_literal(source_view)}, 'claim_scope', 'dashboard_filter_aggregate', 'read_only', true),
  'selected_period', period_arg,
  'selected_municipio', municipio_arg,
  'selected_circuits', split(regexp_replace(coalesce(nullif(circuits_arg, ''), 'Todos'), '\\\\s+', ''), ','),
  'scope_label', coalesce(nullif(circuits_arg, ''), 'Todos'),
  'kpi_summary', named_struct(
    'event_count', event_count,
    'saidi_total', saidi_total,
    'saifi_total', saifi_total,
    'duration_total_h', duration_total_h,
    'users_affected_total', users_affected_total
  ),
  'date_bounds', named_struct('start', first_event_ts, 'end', last_event_ts)
))
FROM payload
CROSS JOIN records_agg
""".strip()


def _event_context_function_sql(*, catalog: str, tools_schema: str, gold_schema: str) -> str:
    function_name = "get_event_context"
    function_ref = sql_table_name(catalog, tools_schema, function_name)
    view_ref = sql_table_name(catalog, gold_schema, "gold_agent_event_context")
    source_function = f"{catalog}.{tools_schema}.{function_name}"
    source_view = f"{catalog}.{gold_schema}.gold_agent_event_context"
    return f"""
CREATE OR REPLACE FUNCTION {function_ref}(event_id_arg STRING)
RETURNS STRING
LANGUAGE SQL
RETURN
WITH record AS (
  SELECT *
  FROM {view_ref}
  WHERE event_id = event_id_arg
  LIMIT 1
),
records_agg AS (
  SELECT collect_list(named_struct(
    'event_id', event_id,
    'map_period', map_period,
    'map_date', cast(map_date AS STRING),
    'municipio', municipio,
    'circuito', circuito,
    'equipo_ope', equipo_ope,
    'event_family', event_family,
    'causa', causa,
    'saidi', SAIDI,
    'saifi', SAIFI,
    'duration_h', duracion_h
  )) AS records
  FROM record
),
metrics AS (
  SELECT
    coalesce(max(SAIDI), 0.0D) AS saidi,
    coalesce(max(SAIFI), 0.0D) AS saifi,
    coalesce(max(duracion_h), 0.0D) AS duration_h,
    max(circuito) AS circuito,
    max(equipo_ope) AS equipo_ope,
    max(causa) AS causa
  FROM record
),
payload AS (
  SELECT substr(sha2(concat_ws('|', {sql_literal(function_name)}, coalesce(event_id_arg, ''), cast(saidi AS STRING), cast(saifi AS STRING)), 256), 1, 16) AS context_hash, *
  FROM metrics
)
SELECT to_json(named_struct(
  'kind', 'event',
  'tool_name', {sql_literal(function_name)},
  'source_function', {sql_literal(source_function)},
  'source_view', {sql_literal(source_view)},
  'parameters', named_struct('event_id', event_id_arg),
  'context_hash', context_hash,
  'context_id', concat('event-', context_hash),
  'summary', named_struct('text', concat('Evento ', coalesce(equipo_ope, 'N/D'), ' en circuito ', coalesce(circuito, 'N/D'), '. Causa: ', coalesce(causa, 'N/D'), '.')),
  'records', coalesce(records_agg.records, array()),
  'metrics', named_struct('saidi', saidi, 'saifi', saifi, 'duration_h', duration_h),
  'traceability', named_struct('source_view', {sql_literal(source_view)}, 'record_id', event_id_arg, 'read_only', true),
  'event_id', event_id_arg,
  'circuito', circuito,
  'cto_equi_ope', circuito,
  'equipo_ope', equipo_ope,
  'causa', causa,
  'SAIDI', saidi,
  'SAIFI', saifi,
  'duracion_h', duration_h
))
FROM payload
CROSS JOIN records_agg
""".strip()


def _asset_context_function_sql(*, catalog: str, tools_schema: str, gold_schema: str) -> str:
    function_name = "get_asset_context"
    function_ref = sql_table_name(catalog, tools_schema, function_name)
    view_ref = sql_table_name(catalog, gold_schema, "gold_agent_asset_context")
    source_function = f"{catalog}.{tools_schema}.{function_name}"
    source_view = f"{catalog}.{gold_schema}.gold_agent_asset_context"
    return f"""
CREATE OR REPLACE FUNCTION {function_ref}(asset_id_arg STRING)
RETURNS STRING
LANGUAGE SQL
RETURN
WITH record AS (
  SELECT *
  FROM {view_ref}
  WHERE asset_id = asset_id_arg
  LIMIT 1
),
records_agg AS (
  SELECT collect_list(named_struct(
    'asset_id', asset_id,
    'asset_family', asset_family,
    'display_label', display_label,
    'municipio', municipio,
    'circuito', circuito,
    'code', CODE,
    'latitude', latitude,
    'longitude', longitude
  )) AS records
  FROM record
),
metrics AS (
  SELECT
    max(asset_family) AS asset_family,
    max(display_label) AS display_label,
    max(municipio) AS municipio,
    max(circuito) AS circuito,
    max(CODE) AS code,
    max(latitude) AS latitude,
    max(longitude) AS longitude
  FROM record
),
payload AS (
  SELECT substr(sha2(concat_ws('|', {sql_literal(function_name)}, coalesce(asset_id_arg, ''), coalesce(display_label, ''), coalesce(circuito, '')), 256), 1, 16) AS context_hash, *
  FROM metrics
)
SELECT to_json(named_struct(
  'kind', 'asset',
  'tool_name', {sql_literal(function_name)},
  'source_function', {sql_literal(source_function)},
  'source_view', {sql_literal(source_view)},
  'parameters', named_struct('asset_id', asset_id_arg),
  'context_hash', context_hash,
  'context_id', concat('asset-', context_hash),
  'summary', named_struct('text', concat(coalesce(asset_family, 'Activo'), ' ', coalesce(display_label, code, asset_id_arg), ' asociado al circuito ', coalesce(circuito, 'N/D'), ' en ', coalesce(municipio, 'N/D'), '.')),
  'records', coalesce(records_agg.records, array()),
  'metrics', named_struct('latitude', latitude, 'longitude', longitude),
  'traceability', named_struct('source_view', {sql_literal(source_view)}, 'record_id', asset_id_arg, 'read_only', true),
  'asset_id', asset_id_arg,
  'asset_family', asset_family,
  'family', asset_family,
  'display_label', display_label,
  'CODE', code,
  'circuito', circuito,
  'FPARENT', circuito,
  'municipio', municipio,
  'MUN', municipio,
  'latitude', latitude,
  'longitude', longitude
))
FROM payload
CROSS JOIN records_agg
""".strip()


def _circuit_history_function_sql(*, catalog: str, tools_schema: str, gold_schema: str) -> str:
    function_name = "get_circuit_history"
    function_ref = sql_table_name(catalog, tools_schema, function_name)
    view_ref = sql_table_name(catalog, gold_schema, "gold_agent_circuit_history")
    source_function = f"{catalog}.{tools_schema}.{function_name}"
    source_view = f"{catalog}.{gold_schema}.gold_agent_circuit_history"
    return f"""
CREATE OR REPLACE FUNCTION {function_ref}(circuit_arg STRING, start_date_arg STRING, end_date_arg STRING)
RETURNS STRING
LANGUAGE SQL
RETURN
WITH filtered AS (
  SELECT *
  FROM {view_ref}
  WHERE circuito = circuit_arg
    AND fecha_dia BETWEEN CAST(start_date_arg AS DATE) AND CAST(end_date_arg AS DATE)
),
limited_records AS (
  SELECT *
  FROM filtered
  ORDER BY fecha_dia DESC
  LIMIT 50
),
records_agg AS (
  SELECT collect_list(named_struct(
    'fecha_dia', cast(fecha_dia AS STRING),
    'municipio', municipio,
    'circuito', circuito,
    'event_count', event_count,
    'saidi', saidi_total,
    'saifi', saifi_total,
    'duration_h', duration_total_h,
    'users_affected', users_affected_total
  )) AS records
  FROM limited_records
),
metrics AS (
  SELECT
    coalesce(sum(event_count), 0) AS event_count,
    coalesce(round(sum(saidi_total), 4), 0.0D) AS saidi_total,
    coalesce(round(sum(saifi_total), 4), 0.0D) AS saifi_total,
    coalesce(round(sum(duration_total_h), 2), 0.0D) AS duration_total_h,
    coalesce(sum(users_affected_total), 0) AS users_affected_total
  FROM filtered
),
payload AS (
  SELECT substr(sha2(concat_ws('|', {sql_literal(function_name)}, coalesce(circuit_arg, ''), coalesce(start_date_arg, ''), coalesce(end_date_arg, ''), cast(event_count AS STRING)), 256), 1, 16) AS context_hash, *
  FROM metrics
)
SELECT to_json(named_struct(
  'kind', 'circuit_history',
  'tool_name', {sql_literal(function_name)},
  'source_function', {sql_literal(source_function)},
  'source_view', {sql_literal(source_view)},
  'parameters', named_struct('circuit', circuit_arg, 'start_date', start_date_arg, 'end_date', end_date_arg),
  'context_hash', context_hash,
  'context_id', concat('circuit_history-', context_hash),
  'summary', named_struct('text', concat('Historial del circuito ', circuit_arg, ' entre ', start_date_arg, ' y ', end_date_arg, '. Eventos: ', cast(event_count AS STRING), '.')),
  'records', coalesce(records_agg.records, array()),
  'metrics', named_struct('event_count', event_count, 'saidi_total', saidi_total, 'saifi_total', saifi_total, 'duration_total_h', duration_total_h, 'users_affected_total', users_affected_total),
  'traceability', named_struct('source_view', {sql_literal(source_view)}, 'claim_scope', 'circuit_history', 'read_only', true),
  'circuito', circuit_arg
))
FROM payload
CROSS JOIN records_agg
""".strip()


def _timeseries_interpretability_context_function_sql(
    *,
    catalog: str,
    tools_schema: str,
    gold_schema: str,
) -> str:
    function_name = "get_timeseries_interpretability_context"
    function_ref = sql_table_name(catalog, tools_schema, function_name)
    attribution_ref = sql_table_name(catalog, gold_schema, "gold_timeseries_daily_attribution")
    source_function = f"{catalog}.{tools_schema}.{function_name}"
    source_view = f"{catalog}.{gold_schema}.gold_timeseries_daily_attribution"
    return f"""
CREATE OR REPLACE FUNCTION {function_ref}(circuit_arg STRING, start_date_arg STRING, end_date_arg STRING, dates_arg STRING)
RETURNS STRING
LANGUAGE SQL
RETURN
WITH filtered AS (
  SELECT *
  FROM {attribution_ref}
  WHERE fecha_dia BETWEEN CAST(start_date_arg AS DATE) AND CAST(end_date_arg AS DATE)
    AND (
      circuit_arg IS NULL
      OR circuit_arg = ''
      OR lower(circuit_arg) = 'todos'
      OR circuito = circuit_arg
    )
    AND (
      dates_arg IS NULL
      OR dates_arg = ''
      OR array_contains(split(regexp_replace(dates_arg, '\\\\s+', ''), ','), CAST(fecha_dia AS STRING))
    )
),
limited_records AS (
  SELECT *
  FROM filtered
  ORDER BY fecha_dia, saidi_total + saifi_total DESC, event_count DESC, duration_total_h DESC
  LIMIT 75
),
records_agg AS (
  SELECT collect_list(named_struct(
    'fecha_dia', CAST(fecha_dia AS STRING),
    'circuito', circuito,
    'municipio', municipio,
    'causa', causa,
    'event_family', event_family,
    'equipo_ope', equipo_ope,
    'tipo_equi_ope', tipo_equi_ope,
    'event_count', event_count,
    'saidi_total', saidi_total,
    'saifi_total', saifi_total,
    'duration_total_h', duration_total_h,
    'users_affected_total', users_affected_total
  )) AS records
  FROM limited_records
),
metrics AS (
  SELECT
    coalesce(count(DISTINCT fecha_dia), 0) AS critical_date_count,
    coalesce(sum(event_count), 0) AS event_count,
    coalesce(round(sum(saidi_total), 4), 0.0D) AS saidi_total,
    coalesce(round(sum(saifi_total), 4), 0.0D) AS saifi_total,
    coalesce(round(sum(duration_total_h), 2), 0.0D) AS duration_total_h,
    coalesce(sum(users_affected_total), 0.0D) AS users_affected_total
  FROM filtered
),
payload AS (
  SELECT substr(sha2(concat_ws('|', {sql_literal(function_name)}, coalesce(circuit_arg, ''), coalesce(start_date_arg, ''), coalesce(end_date_arg, ''), coalesce(dates_arg, ''), cast(event_count AS STRING)), 256), 1, 16) AS context_hash, *
  FROM metrics
)
SELECT to_json(named_struct(
  'kind', 'timeseries_criticality',
  'tool_name', {sql_literal(function_name)},
  'source_function', {sql_literal(source_function)},
  'source_view', {sql_literal(source_view)},
  'parameters', named_struct('circuit', circuit_arg, 'start_date', start_date_arg, 'end_date', end_date_arg, 'dates', dates_arg),
  'context_hash', context_hash,
  'context_id', concat('timeseries-criticality-', context_hash),
  'summary', named_struct('text', concat('Contexto de interpretabilidad SAIDI/SAIFI entre ', start_date_arg, ' y ', end_date_arg, '. Eventos: ', cast(event_count AS STRING), '.')),
  'records', coalesce(records_agg.records, array()),
  'metrics', named_struct(
    'critical_date_count', critical_date_count,
    'event_count', event_count,
    'saidi_total', saidi_total,
    'saifi_total', saifi_total,
    'duration_total_h', duration_total_h,
    'users_affected_total', users_affected_total
  ),
  'traceability', named_struct('source_view', {sql_literal(source_view)}, 'claim_scope', 'timeseries_interpretability', 'read_only', true),
  'circuito', circuit_arg
))
FROM payload
CROSS JOIN records_agg
""".strip()


def main() -> int:
    settings = _settings_with_app_defaults()
    client = DatabricksSQLWarehouseClient(settings)
    catalog = settings.databricks_catalog_name
    gold_schema = settings.databricks_gold_schema
    tools_schema = settings.chatbot_context_tools_schema

    client.fetch_dataframe(f"CREATE SCHEMA IF NOT EXISTS {sql_table_name(catalog, tools_schema)}")

    daily_table = sql_table_name(catalog, gold_schema, "gold_saidi_saifi_daily")
    event_days_table = sql_table_name(catalog, gold_schema, "gold_map_event_days")
    points_table = sql_table_name(catalog, gold_schema, "gold_map_points")
    lines_table = sql_table_name(catalog, gold_schema, "gold_map_line_segments")

    client.fetch_dataframe(
        f"""
CREATE OR REPLACE VIEW {sql_table_name(catalog, gold_schema, "gold_agent_view_context")} AS
SELECT
  DATE_FORMAT(CAST(fecha_dia AS DATE), 'yyyy-MM') AS map_period,
  municipio,
  circuito,
  event_family,
  COALESCE(SUM(saidi_total), 0.0D) AS saidi_total,
  COALESCE(SUM(saifi_total), 0.0D) AS saifi_total,
  COALESCE(SUM(event_count), 0) AS event_count,
  COALESCE(SUM(duration_total_h), 0.0D) AS duration_total_h,
  COALESCE(SUM(users_affected_total), 0.0D) AS users_affected_total,
  MIN(first_event_ts) AS first_event_ts,
  MAX(last_event_ts) AS last_event_ts
FROM {daily_table}
GROUP BY DATE_FORMAT(CAST(fecha_dia AS DATE), 'yyyy-MM'), municipio, circuito, event_family
""".strip()
    )

    client.fetch_dataframe(
        f"""
CREATE OR REPLACE VIEW {sql_table_name(catalog, gold_schema, "gold_agent_event_context")} AS
SELECT
  CONCAT('event-', SUBSTR(SHA2(CONCAT_WS('|',
    COALESCE(CAST(map_period AS STRING), ''),
    COALESCE(CAST(map_day AS STRING), ''),
    COALESCE(CAST(municipio AS STRING), ''),
    COALESCE(CAST(cto_equi_ope AS STRING), ''),
    COALESCE(CAST(equipo_ope AS STRING), ''),
    COALESCE(CAST(event_family AS STRING), ''),
    COALESCE(CAST(causa AS STRING), ''),
    COALESCE(CAST(SAIDI AS STRING), ''),
    COALESCE(CAST(SAIFI AS STRING), '')
  ), 256), 1, 16)) AS event_id,
  *
FROM {event_days_table}
""".strip()
    )

    client.fetch_dataframe(
        f"""
CREATE OR REPLACE VIEW {sql_table_name(catalog, gold_schema, "gold_agent_asset_context")} AS
SELECT
  CONCAT('asset-', SUBSTR(SHA2(CONCAT_WS('|',
    COALESCE(CAST(asset_family AS STRING), ''),
    COALESCE(CAST(display_label AS STRING), ''),
    COALESCE(CAST(circuito AS STRING), ''),
    COALESCE(CAST(municipio AS STRING), ''),
    COALESCE(CAST(latitude AS STRING), ''),
    COALESCE(CAST(longitude AS STRING), '')
  ), 256), 1, 16)) AS asset_id,
  asset_family,
  display_label,
  COALESCE(CAST(CODE AS STRING), CAST(equipo_ope AS STRING), CAST(display_label AS STRING)) AS CODE,
  equipo_ope,
  circuito,
  municipio,
  map_period,
  map_day,
  map_date,
  latitude,
  longitude,
  latitude_end,
  longitude_end,
  geometry_kind,
  popup_text,
  source_logical_name,
  source_table
FROM {points_table}
WHERE point_kind = 'asset'
UNION ALL
SELECT
  CONCAT('asset-', SUBSTR(SHA2(CONCAT_WS('|',
    COALESCE(CAST(asset_family AS STRING), ''),
    COALESCE(CAST(display_label AS STRING), ''),
    COALESCE(CAST(circuito AS STRING), ''),
    COALESCE(CAST(municipio AS STRING), ''),
    COALESCE(CAST(latitude AS STRING), ''),
    COALESCE(CAST(longitude AS STRING), ''),
    COALESCE(CAST(latitude_end AS STRING), ''),
    COALESCE(CAST(longitude_end AS STRING), '')
  ), 256), 1, 16)) AS asset_id,
  asset_family,
  display_label,
  COALESCE(CAST(CODE AS STRING), CAST(equipo_ope AS STRING), CAST(display_label AS STRING)) AS CODE,
  equipo_ope,
  circuito,
  municipio,
  map_period,
  map_day,
  map_date,
  latitude,
  longitude,
  latitude_end,
  longitude_end,
  geometry_kind,
  popup_text,
  source_logical_name,
  source_table
FROM {lines_table}
""".strip()
    )

    client.fetch_dataframe(
        f"""
CREATE OR REPLACE VIEW {sql_table_name(catalog, gold_schema, "gold_agent_circuit_history")} AS
SELECT
  CAST(fecha_dia AS DATE) AS fecha_dia,
  municipio,
  circuito,
  COALESCE(SUM(saidi_total), 0.0D) AS saidi_total,
  COALESCE(SUM(saifi_total), 0.0D) AS saifi_total,
  COALESCE(SUM(event_count), 0) AS event_count,
  COALESCE(SUM(duration_total_h), 0.0D) AS duration_total_h,
  COALESCE(SUM(users_affected_total), 0.0D) AS users_affected_total,
  MIN(first_event_ts) AS first_event_ts,
  MAX(last_event_ts) AS last_event_ts
FROM {daily_table}
GROUP BY CAST(fecha_dia AS DATE), municipio, circuito
""".strip()
    )

    for function_name in ("get_dashboard_context", "get_reliability_summary", "get_compliance_context"):
        client.fetch_dataframe(
            _dashboard_context_function_sql(
                function_name=function_name,
                catalog=catalog,
                tools_schema=tools_schema,
                gold_schema=gold_schema,
            )
        )
    client.fetch_dataframe(_event_context_function_sql(catalog=catalog, tools_schema=tools_schema, gold_schema=gold_schema))
    client.fetch_dataframe(_asset_context_function_sql(catalog=catalog, tools_schema=tools_schema, gold_schema=gold_schema))
    client.fetch_dataframe(_circuit_history_function_sql(catalog=catalog, tools_schema=tools_schema, gold_schema=gold_schema))
    client.fetch_dataframe(
        _timeseries_interpretability_context_function_sql(
            catalog=catalog,
            tools_schema=tools_schema,
            gold_schema=gold_schema,
        )
    )

    print(
        "Phase 4 context tools are ready: "
        f"{', '.join(AGENT_CONTEXT_VIEWS)} and {', '.join(AGENT_CONTEXT_FUNCTIONS)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
