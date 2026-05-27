from __future__ import annotations

import base64
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from chec_dashboard.core.config import Settings
from chec_dashboard.services.cache import CACHE, build_cache_key
from chec_dashboard.services.databricks_sql import (
    INTEGER_TYPES,
    NUMERIC_TYPES,
    TEMPORAL_TYPES,
    DatabricksSQLWarehouseClient,
    TableSchema,
    sql_identifier,
    sql_literal,
    sql_table_name,
)
from chec_dashboard.services.map_service import (
    ALL_CIRCUITS_LABEL,
    FilteredMapDataset,
    describe_selected_circuits,
    normalize_selected_circuits,
    render_base_map,
)
from chec_dashboard.services.probability_service import (
    criteria_options,
    generate_probability_graph,
)


METADATA_CACHE_SECONDS = 600
MAP_CACHE_SECONDS = 45
SUMMARY_CACHE_SECONDS = 120
PROBABILITY_META_CACHE_SECONDS = 120
MAX_PROBABILITY_VALUE_OPTIONS = 1000
MAX_PROBABILITY_SAMPLE_ROWS = 50000
MAP_OUTPUT_OPTIONS = ["BASE"]
MAP_ASSET_POINT_FAMILIES = {
    "Transformers": "trafos",
    "Supports": "apoyos",
    "Switches": "switches",
}


def _cache_get(settings: Settings, key: str) -> Any | None:
    if not settings.cache_enabled:
        return None
    return CACHE.get(key)


def _cache_set(settings: Settings, key: str, value: Any, ttl_seconds: int) -> None:
    if not settings.cache_enabled:
        return
    CACHE.set(key, value, ttl_seconds=ttl_seconds)


def _warehouse_client(settings: Settings) -> DatabricksSQLWarehouseClient:
    return DatabricksSQLWarehouseClient(settings)


def _gold_table(settings: Settings, table_name: str) -> str:
    return sql_table_name(settings.databricks_catalog_name, settings.databricks_gold_schema, table_name)


def _normalize_period(selected_period: str) -> str:
    parsed = pd.to_datetime(f"{selected_period}-01", errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"selected_period must use YYYY-MM format. Received: {selected_period}")
    return parsed.strftime("%Y-%m")


def _coerce_float(value: Any) -> float:
    coerced = pd.to_numeric(value, errors="coerce")
    if pd.isna(coerced):
        return 0.0
    return float(coerced)


def _coerce_int(value: Any) -> int:
    coerced = pd.to_numeric(value, errors="coerce")
    if pd.isna(coerced):
        return 0
    return int(coerced)


def _coerce_window_from_bounds(
    min_date: date,
    max_date: date,
    start_date_raw: str | None,
    end_date_raw: str | None,
    days: int = 180,
) -> tuple[date, date]:
    end_default = max_date
    start_default = max(min_date, end_default - timedelta(days=max(days - 1, 0)))
    start_date = (
        pd.to_datetime(start_date_raw, errors="coerce").date() if start_date_raw else start_default
    )
    end_date = (
        pd.to_datetime(end_date_raw, errors="coerce").date() if end_date_raw else end_default
    )
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    start_date = max(start_date, min_date)
    end_date = min(end_date, max_date)
    return start_date, end_date


def _summary_bounds(settings: Settings) -> tuple[date, date]:
    cache_key = build_cache_key("dbx", "summary", "bounds")
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    table_name = _gold_table(settings, "gold_saidi_saifi_daily")
    frame = _warehouse_client(settings).fetch_dataframe(
        f"""
        SELECT
          MIN(CAST(fecha_dia AS DATE)) AS min_date,
          MAX(CAST(fecha_dia AS DATE)) AS max_date
        FROM {table_name}
        """
    )
    if frame.empty or pd.isna(frame.iloc[0]["min_date"]) or pd.isna(frame.iloc[0]["max_date"]):
        raise ValueError("Databricks summary table does not contain usable date bounds.")

    bounds = (
        pd.to_datetime(frame.iloc[0]["min_date"]).date(),
        pd.to_datetime(frame.iloc[0]["max_date"]).date(),
    )
    _cache_set(settings, cache_key, bounds, METADATA_CACHE_SECONDS)
    return bounds


def _schema_for_table(settings: Settings, table_name: str) -> TableSchema:
    cache_key = build_cache_key("dbx", "schema", table_name)
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached
    schema = _warehouse_client(settings).describe_table(table_name)
    _cache_set(settings, cache_key, schema, METADATA_CACHE_SECONDS)
    return schema


def _probability_schema(settings: Settings) -> TableSchema:
    return _schema_for_table(settings, _gold_table(settings, "gold_probability_inputs"))


def _validate_probability_criteria(criteria: str) -> str:
    valid_values = {
        entry["value"]
        for entry in criteria_options()
        if entry.get("value")
    }
    if criteria not in valid_values:
        raise ValueError("Criterio no válido")
    return criteria


def _probability_filter_kind(sql_type: str) -> str:
    normalized = sql_type.lower()
    if normalized in INTEGER_TYPES or normalized.startswith("int"):
        return "seleccion"
    if normalized in NUMERIC_TYPES or normalized.startswith("decimal"):
        return "rango_num"
    if normalized in TEMPORAL_TYPES:
        return "fecha"
    return "seleccion"


def _sql_date_text_expression(column_name: str, sql_type: str) -> str:
    column_expr = sql_identifier(column_name)
    normalized = sql_type.lower()
    if normalized == "date":
        return f"DATE_FORMAT({column_expr}, 'yyyy-MM-dd')"
    return f"DATE_FORMAT(CAST({column_expr} AS TIMESTAMP), 'yyyy-MM-dd')"


def _validate_probability_column(settings: Settings, column_name: str) -> str:
    schema = _probability_schema(settings)
    if column_name not in schema.columns:
        raise ValueError(f"La columna '{column_name}' no existe para el criterio seleccionado")
    return column_name


def _build_probability_where_clause(
    settings: Settings,
    *,
    criteria: str,
    filters: list[list[str | float | int | None]],
) -> str:
    schema = _probability_schema(settings)
    clauses = [f"{sql_identifier('criteria_group')} = {sql_literal(criteria)}"]
    operator_allowlist = {"<", ">", "==", "<=", ">=", "!=", "="}

    for filter_row in filters:
        if len(filter_row) < 4:
            continue
        filter_type = str(filter_row[0] or "").strip()
        column_name = str(filter_row[1] or "").strip()
        value_1 = filter_row[2]
        value_2 = filter_row[3]

        if not filter_type or not column_name or value_1 in (None, ""):
            continue
        if column_name not in schema.columns:
            continue

        column_expr = sql_identifier(column_name)
        sql_type = schema.types.get(column_name, "string")

        if filter_type == "seleccion":
            clauses.append(f"CAST({column_expr} AS STRING) = {sql_literal(str(value_1))}")
            continue

        if filter_type == "rango_num" and value_2 not in (None, ""):
            operator_token = str(value_1).strip()
            if operator_token not in operator_allowlist:
                continue
            normalized_operator = "=" if operator_token == "==" else operator_token
            numeric_value = pd.to_numeric(value_2, errors="coerce")
            if pd.isna(numeric_value):
                continue
            clauses.append(
                f"CAST({column_expr} AS DOUBLE) {normalized_operator} {sql_literal(float(numeric_value))}"
            )
            continue

        if filter_type == "fecha" and value_2 not in (None, ""):
            start_value = pd.to_datetime(value_1, errors="coerce")
            end_value = pd.to_datetime(value_2, errors="coerce")
            if pd.isna(start_value) or pd.isna(end_value):
                continue
            if start_value > end_value:
                start_value, end_value = end_value, start_value
            if sql_type.lower() == "date":
                clauses.append(
                    f"{column_expr} BETWEEN {sql_literal(start_value.date().isoformat())} "
                    f"AND {sql_literal(end_value.date().isoformat())}"
                )
            else:
                clauses.append(
                    f"CAST({column_expr} AS TIMESTAMP) BETWEEN "
                    f"CAST({sql_literal(start_value.isoformat())} AS TIMESTAMP) AND "
                    f"CAST({sql_literal(end_value.isoformat())} AS TIMESTAMP)"
                )

    return " AND ".join(clauses)


def get_dashboard_metadata(settings: Settings) -> dict[str, Any]:
    return {
        "map": get_map_metadata(settings),
        "summary": get_summary_metadata(settings),
        "probability": get_probability_metadata(settings),
    }


def get_summary_metadata(settings: Settings) -> dict[str, Any]:
    cache_key = build_cache_key("dbx", "meta", "summary")
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    min_date, max_date = _summary_bounds(settings)
    default_end = max_date
    default_start = max(min_date, default_end - timedelta(days=179))
    circuits_frame = _warehouse_client(settings).fetch_dataframe(
        f"""
        SELECT DISTINCT circuito
        FROM {_gold_table(settings, 'gold_saidi_saifi_circuit_summary')}
        WHERE circuito IS NOT NULL
        ORDER BY circuito
        """
    )
    circuits = circuits_frame["circuito"].dropna().astype(str).tolist() if not circuits_frame.empty else []

    payload = {
        "circuits": circuits,
        "default_circuit": circuits[0] if circuits else None,
        "min_date": min_date.isoformat(),
        "max_date": max_date.isoformat(),
        "default_start": default_start.isoformat(),
        "default_end": default_end.isoformat(),
    }
    _cache_set(settings, cache_key, payload, METADATA_CACHE_SECONDS)
    return payload


def get_summary_payload(
    settings: Settings,
    start_date_raw: str | None,
    end_date_raw: str | None,
    circuito: str | None,
    metric_mode: str,
) -> dict[str, Any]:
    min_date, max_date = _summary_bounds(settings)
    start_date, end_date = _coerce_window_from_bounds(
        min_date,
        max_date,
        start_date_raw,
        end_date_raw,
        days=180,
    )
    metric_mode = metric_mode or "BOTH"
    circuit_label = circuito or "TODOS"

    cache_key = build_cache_key(
        "dbx",
        "summary",
        circuit_label,
        metric_mode,
        start_date.isoformat(),
        end_date.isoformat(),
    )
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    where_clauses = [
        f"CAST(fecha_dia AS DATE) BETWEEN {sql_literal(start_date.isoformat())} AND {sql_literal(end_date.isoformat())}"
    ]
    if circuito:
        where_clauses.append(f"{sql_identifier('circuito')} = {sql_literal(circuito)}")
    where_clause = " AND ".join(where_clauses)
    table_name = _gold_table(settings, "gold_saidi_saifi_daily")

    totals_frame = _warehouse_client(settings).fetch_dataframe(
        f"""
        SELECT
          COALESCE(SUM(COALESCE(saidi_total, 0.0)), 0.0) AS saidi_total,
          COALESCE(SUM(COALESCE(saifi_total, 0.0)), 0.0) AS saifi_total,
          COALESCE(SUM(COALESCE(event_count, 0)), 0) AS event_count
        FROM {table_name}
        WHERE {where_clause}
        """
    )
    daily_frame = _warehouse_client(settings).fetch_dataframe(
        f"""
        SELECT
          CAST(fecha_dia AS DATE) AS fecha_dia,
          COALESCE(SUM(COALESCE(saidi_total, 0.0)), 0.0) AS SAIDI,
          COALESCE(SUM(COALESCE(saifi_total, 0.0)), 0.0) AS SAIFI
        FROM {table_name}
        WHERE {where_clause}
        GROUP BY CAST(fecha_dia AS DATE)
        ORDER BY CAST(fecha_dia AS DATE)
        """
    )

    date_index = pd.date_range(start=start_date, end=end_date, freq="D")
    if daily_frame.empty:
        normalized_daily = pd.DataFrame({"fecha_dia": date_index, "SAIDI": 0.0, "SAIFI": 0.0})
    else:
        daily_frame["fecha_dia"] = pd.to_datetime(daily_frame["fecha_dia"], errors="coerce")
        daily_frame["SAIDI"] = pd.to_numeric(daily_frame["SAIDI"], errors="coerce").fillna(0.0)
        daily_frame["SAIFI"] = pd.to_numeric(daily_frame["SAIFI"], errors="coerce").fillna(0.0)
        normalized_daily = (
            daily_frame.set_index("fecha_dia")[["SAIDI", "SAIFI"]]
            .reindex(date_index, fill_value=0.0)
            .reset_index()
            .rename(columns={"index": "fecha_dia"})
        )

    saidi_total = 0.0
    saifi_total = 0.0
    event_count = 0
    if not totals_frame.empty:
        saidi_total = _coerce_float(totals_frame.iloc[0]["saidi_total"])
        saifi_total = _coerce_float(totals_frame.iloc[0]["saifi_total"])
        event_count = _coerce_int(totals_frame.iloc[0]["event_count"])

    daily_records = [
        {
            "fecha_dia": pd.to_datetime(row["fecha_dia"]).date().isoformat(),
            "SAIDI": float(row["SAIDI"]),
            "SAIFI": float(row["SAIFI"]),
        }
        for _, row in normalized_daily.iterrows()
    ]

    if event_count == 0:
        status_text = (
            f"No se encontraron eventos para el circuito {circuit_label} "
            f"entre {start_date.isoformat()} y {end_date.isoformat()}. "
            "Se muestran series en cero."
        )
    else:
        status_text = (
            f"Circuito: {circuit_label}. "
            f"Ventana: {start_date.isoformat()} a {end_date.isoformat()}. "
            f"Eventos: {event_count}."
        )

    payload = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "circuit_label": circuit_label,
        "metric_mode": metric_mode,
        "saidi_total": saidi_total,
        "saifi_total": saifi_total,
        "event_count": event_count,
        "daily_data": daily_records,
        "status_text": status_text,
    }
    _cache_set(settings, cache_key, payload, SUMMARY_CACHE_SECONDS)
    return payload


def get_probability_metadata(settings: Settings) -> dict[str, Any]:
    cache_key = build_cache_key("dbx", "meta", "probability", "criteria")
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    payload = {
        "action": "criteria",
        "criteria_options": criteria_options(),
        "columns": [],
        "filter_kind": None,
        "value_options": [],
        "is_empty": False,
        "message": None,
    }
    _cache_set(settings, cache_key, payload, METADATA_CACHE_SECONDS)
    return payload


def get_probability_columns_metadata(settings: Settings, criteria: str) -> dict[str, Any]:
    if not criteria:
        raise ValueError("criteria is required for probability columns metadata")
    _validate_probability_criteria(criteria)

    cache_key = build_cache_key("dbx", "meta", "probability", "columns", criteria)
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    schema = _probability_schema(settings)
    payload = {
        "action": "columns",
        "criteria_options": [],
        "columns": schema.columns,
        "filter_kind": None,
        "value_options": [],
        "is_empty": False,
        "message": None,
    }
    _cache_set(settings, cache_key, payload, PROBABILITY_META_CACHE_SECONDS)
    return payload


def get_probability_filter_options_metadata(
    settings: Settings,
    criteria: str,
    selected_column: str,
    previous_filters: list[list[Any]],
) -> dict[str, Any]:
    if not criteria:
        raise ValueError("criteria is required for probability filter metadata")
    if not selected_column:
        raise ValueError("selected_column is required for probability filter metadata")
    _validate_probability_criteria(criteria)

    cache_key = build_cache_key(
        "dbx",
        "meta",
        "probability",
        "filter",
        criteria,
        selected_column,
        str(previous_filters),
    )
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    selected_column = _validate_probability_column(settings, selected_column)
    schema = _probability_schema(settings)
    sql_type = schema.types.get(selected_column, "string")
    filter_kind = _probability_filter_kind(sql_type)
    where_clause = _build_probability_where_clause(
        settings,
        criteria=criteria,
        filters=previous_filters,
    )
    table_name = _gold_table(settings, "gold_probability_inputs")

    count_frame = _warehouse_client(settings).fetch_dataframe(
        f"SELECT COUNT(*) AS row_count FROM {table_name} WHERE {where_clause}"
    )
    row_count = _coerce_int(count_frame.iloc[0]["row_count"])

    value_options: list[str] = []
    if filter_kind in {"seleccion", "fecha"}:
        if filter_kind == "fecha":
            value_expr = _sql_date_text_expression(selected_column, sql_type)
        else:
            value_expr = f"CAST({sql_identifier(selected_column)} AS STRING)"

        options_frame = _warehouse_client(settings).fetch_dataframe(
            f"""
            SELECT DISTINCT {value_expr} AS option_value
            FROM {table_name}
            WHERE {where_clause} AND {sql_identifier(selected_column)} IS NOT NULL
            ORDER BY option_value
            LIMIT {MAX_PROBABILITY_VALUE_OPTIONS}
            """
        )
        if not options_frame.empty:
            value_options = (
                options_frame["option_value"].dropna().astype(str).tolist()
            )

    payload = {
        "action": "filter_options",
        "criteria_options": [],
        "columns": [],
        "filter_kind": filter_kind,
        "value_options": value_options,
        "is_empty": row_count == 0,
        "message": "No hay opciones con filtros previos." if row_count == 0 else None,
    }
    _cache_set(settings, cache_key, payload, PROBABILITY_META_CACHE_SECONDS)
    return payload


def _build_probability_text(
    criteria: str,
    target_column: str,
    filters: list[list[str | float | int | None]],
) -> str:
    parts = [f"P({target_column} | {criteria}"]
    for filter_row in filters:
        if len(filter_row) < 4:
            continue
        filter_type = filter_row[0]
        name = filter_row[1]
        value_1 = filter_row[2]
        value_2 = filter_row[3]
        if not all([filter_type, name, value_1]):
            continue

        if filter_type == "seleccion":
            parts.append(f"{name} = {value_1}")
        elif filter_type == "rango_num" and value_2 is not None:
            parts.append(f"{name} {value_1} {value_2}")
        elif filter_type == "fecha" and value_2:
            parts.append(f"{name} {value_1} - {value_2}")

    return ", ".join(parts) + ")"


def get_probability_payload(
    settings: Settings,
    criteria: str,
    target_column: str,
    filters: list[list[str | float | int | None]],
) -> dict[str, Any]:
    if not criteria:
        raise ValueError("criteria is required")
    if not target_column:
        raise ValueError("target_column is required")
    _validate_probability_criteria(criteria)

    target_column = _validate_probability_column(settings, target_column)
    schema = _probability_schema(settings)
    sql_type = schema.types.get(target_column, "string")
    where_clause = _build_probability_where_clause(
        settings,
        criteria=criteria,
        filters=filters,
    )
    table_name = _gold_table(settings, "gold_probability_inputs")
    probability_text = _build_probability_text(criteria, target_column, filters)

    frame = _warehouse_client(settings).fetch_dataframe(
        f"""
        SELECT {sql_identifier(target_column)} AS {sql_identifier(target_column)}
        FROM {table_name}
        WHERE {where_clause} AND {sql_identifier(target_column)} IS NOT NULL
        LIMIT {MAX_PROBABILITY_SAMPLE_ROWS}
        """
    )
    if frame.empty:
        return {
            "probability_text": probability_text,
            "status_text": "No hay registros para la combinación seleccionada.",
            "graph_name": None,
            "graph_data_uri": None,
        }

    output_path: Path = generate_probability_graph(
        frame,
        target_column=target_column,
        probability_text=probability_text,
        output_dir=settings.output_dir,
    )
    graph_bytes = output_path.read_bytes()
    graph_data_uri = f"data:image/png;base64,{base64.b64encode(graph_bytes).decode('ascii')}"

    target_kind = _probability_filter_kind(sql_type)
    if target_kind == "rango_num":
        status_text = "Distribución numérica generada correctamente."
    else:
        status_text = "Distribución categorizada generada correctamente."

    return {
        "probability_text": probability_text,
        "status_text": status_text,
        "graph_name": output_path.name,
        "graph_data_uri": graph_data_uri,
    }


def get_map_metadata(settings: Settings) -> dict[str, Any]:
    cache_key = build_cache_key("dbx", "meta", "map")
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    filter_index = _gold_table(settings, "gold_map_filter_index")
    periods_frame = _warehouse_client(settings).fetch_dataframe(
        f"""
        SELECT DISTINCT map_period
        FROM {filter_index}
        WHERE map_period IS NOT NULL
        ORDER BY map_period
        """
    )
    municipios_frame = _warehouse_client(settings).fetch_dataframe(
        f"""
        SELECT DISTINCT municipio
        FROM {filter_index}
        WHERE municipio IS NOT NULL
        ORDER BY municipio
        """
    )

    dates = periods_frame["map_period"].dropna().astype(str).tolist() if not periods_frame.empty else []
    municipios = municipios_frame["municipio"].dropna().astype(str).tolist() if not municipios_frame.empty else []
    payload = {
        "action": None,
        "dates": dates,
        "municipios": municipios,
        "default_date": dates[0] if dates else None,
        "default_municipio": municipios[0] if municipios else None,
        "circuits": [],
        "default_circuit": ALL_CIRCUITS_LABEL,
        "outputs": MAP_OUTPUT_OPTIONS,
        "default_output": MAP_OUTPUT_OPTIONS[0],
    }
    _cache_set(settings, cache_key, payload, METADATA_CACHE_SECONDS)
    return payload


def get_map_filter_metadata(
    settings: Settings,
    action: str,
    selected_period: str,
    selected_municipio: str,
) -> dict[str, Any]:
    if action != "circuits":
        raise ValueError(f"Unsupported map metadata action: {action}")
    if not selected_period or not selected_municipio:
        raise ValueError("selected_period and selected_municipio are required for map metadata")

    normalized_period = _normalize_period(selected_period)
    cache_key = build_cache_key("dbx", "meta", "map", action, normalized_period, selected_municipio)
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    filter_index = _gold_table(settings, "gold_map_filter_index")
    circuits_frame = _warehouse_client(settings).fetch_dataframe(
        f"""
        SELECT DISTINCT circuito
        FROM {filter_index}
        WHERE map_period = {sql_literal(normalized_period)}
          AND municipio = {sql_literal(selected_municipio)}
          AND circuito IS NOT NULL
        ORDER BY circuito
        """
    )
    circuits = [ALL_CIRCUITS_LABEL]
    if not circuits_frame.empty:
        circuits.extend(circuits_frame["circuito"].dropna().astype(str).tolist())

    payload = {
        "action": action,
        "dates": [],
        "municipios": [],
        "default_date": normalized_period,
        "default_municipio": selected_municipio,
        "circuits": circuits,
        "default_circuit": circuits[0],
        "outputs": MAP_OUTPUT_OPTIONS,
        "default_output": MAP_OUTPUT_OPTIONS[0],
    }
    _cache_set(settings, cache_key, payload, METADATA_CACHE_SECONDS)
    return payload


def _build_map_where_clause(
    *,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None,
) -> str:
    clauses = [
        f"map_period = {sql_literal(selected_period)}",
        f"municipio = {sql_literal(selected_municipio)}",
    ]
    if selected_circuits is not None:
        if not selected_circuits:
            clauses.append("1 = 0")
        elif len(selected_circuits) == 1:
            clauses.append(f"circuito = {sql_literal(selected_circuits[0])}")
        else:
            literals = ", ".join(sql_literal(circuit) for circuit in selected_circuits)
            clauses.append(f"circuito IN ({literals})")
    return " AND ".join(clauses)


def get_map_payload(
    settings: Settings,
    selected_period: str,
    selected_municipio: str,
    selected_circuit: str | None,
    selected_output: str | None,
    day: int,
    selected_circuits: list[str] | None = None,
) -> dict[str, Any]:
    if not selected_period or not selected_municipio:
        raise ValueError("selected_period and selected_municipio are required")
    if selected_output not in {None, "", "BASE"}:
        raise ValueError(f"Salida de mapa no soportada: {selected_output}")

    normalized_period = _normalize_period(selected_period)
    safe_day = max(1, min(int(day), 31))
    normalized_circuits = normalize_selected_circuits(
        selected_circuit=selected_circuit,
        selected_circuits=selected_circuits,
    )
    circuit_label = describe_selected_circuits(normalized_circuits)
    circuit_cache_token = (
        ALL_CIRCUITS_LABEL
        if normalized_circuits is None
        else "SIN_CIRCUITOS"
        if not normalized_circuits
        else "|".join(sorted(normalized_circuits))
    )
    normalized_output = selected_output or MAP_OUTPUT_OPTIONS[0]
    cache_key = build_cache_key(
        "dbx",
        "map",
        normalized_period,
        selected_municipio,
        circuit_cache_token,
        normalized_output,
        str(safe_day),
    )
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    where_clause = _build_map_where_clause(
        selected_period=normalized_period,
        selected_municipio=selected_municipio,
        selected_circuits=normalized_circuits,
    )

    points_table = _gold_table(settings, "gold_map_points")
    lines_table = _gold_table(settings, "gold_map_line_segments")
    event_days_table = _gold_table(settings, "gold_map_event_days")
    client = _warehouse_client(settings)

    asset_points = client.fetch_dataframe(
        f"""
        SELECT *
        FROM {points_table}
        WHERE point_kind = 'asset' AND {where_clause}
        """
    )
    if normalized_circuits is not None:
        apoyos = asset_points.iloc[0:0].copy()
    else:
        apoyos = asset_points[asset_points["asset_family"] == "Supports"].copy()
    trafos = asset_points[asset_points["asset_family"] == "Transformers"].copy()
    switches = asset_points[asset_points["asset_family"] == "Switches"].copy()
    redmt = client.fetch_dataframe(
        f"""
        SELECT *
        FROM {lines_table}
        WHERE {where_clause}
        """
    )
    day_events = client.fetch_dataframe(
        f"""
        SELECT *
        FROM {event_days_table}
        WHERE {where_clause}
        """
    )

    events_by_day: list[pd.DataFrame] = []
    if day_events.empty:
        events_by_day = [pd.DataFrame() for _ in range(31)]
    else:
        day_events["map_day"] = pd.to_numeric(day_events["map_day"], errors="coerce").fillna(0).astype(int)
        for current_day in range(1, 32):
            events_by_day.append(day_events[day_events["map_day"] == current_day].copy())

    filtered = FilteredMapDataset(
        trafos=trafos,
        apoyos=apoyos,
        switches=switches,
        redmt=redmt,
        events_by_day=events_by_day,
    )
    map_html = render_base_map(filtered, day=safe_day)
    if len(map_html) > settings.max_map_html_chars:
        raise ValueError(
            "Rendered map payload is too large for safe transfer. Narrow filters or increase "
            "MAX_MAP_HTML_CHARS explicitly."
        )

    payload = {
        "map_html": map_html,
        "current_day": safe_day,
        "status_text": (
            f"Mapa cargado para municipio {selected_municipio}, {circuit_label}, "
            f"salida {normalized_output}, período {normalized_period}. Día actual: {safe_day}."
        ),
    }
    _cache_set(settings, cache_key, payload, MAP_CACHE_SECONDS)
    return payload


def databricks_data_readiness_check(settings: Settings) -> tuple[bool, str]:
    required_tables = [
        "gold_saidi_saifi_daily",
        "gold_saidi_saifi_circuit_summary",
        "gold_probability_inputs",
        "gold_map_points",
        "gold_map_line_segments",
        "gold_map_filter_index",
        "gold_map_event_days",
    ]
    client = _warehouse_client(settings)
    try:
        client.ping()
        for table_name in required_tables:
            schema = _schema_for_table(settings, _gold_table(settings, table_name))
            if not schema.columns:
                raise ValueError(f"Required table {table_name} is empty or unavailable.")
    except Exception as exc:
        return False, f"Databricks data backend is not ready: {exc}"
    return True, "Databricks data backend ready"
