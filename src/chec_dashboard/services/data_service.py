from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from chec_dashboard.core.config import Settings
from chec_dashboard.services import databricks_data_service
from chec_dashboard.services.cache import CACHE, build_cache_key
from chec_dashboard.services.map_service import (
    ALL_CIRCUITS_LABEL,
    describe_selected_circuits,
    filter_map_dataset,
    get_map_circuit_options,
    load_map_filter_options,
    load_map_dataset,
    normalize_selected_circuits,
    render_base_map,
)
from chec_dashboard.services.probability_service import (
    apply_filters,
    criteria_options,
    generate_probability_graph,
    get_dataframe_by_criteria,
    infer_filter_type,
    load_probability_dataset,
)
from chec_dashboard.services.summary_service import (
    aggregate_daily,
    coerce_window,
    compute_kpis,
    filter_summary_data,
    get_circuit_options,
    get_default_window,
    load_summary_dataset,
)


# Cache policy intentionally targets only shared-safe computations (no user-specific secrets).
METADATA_CACHE_SECONDS = 600
MAP_CACHE_SECONDS = 45
SUMMARY_CACHE_SECONDS = 120
PROBABILITY_META_CACHE_SECONDS = 120
MAX_PROBABILITY_VALUE_OPTIONS = 1000
MAP_OUTPUT_OPTIONS = ["BASE"]


def _use_databricks_backend(settings: Settings) -> bool:
    return settings.data_backend == "databricks_sql"



def _cache_get(settings: Settings, key: str) -> Any | None:
    if not settings.cache_enabled:
        return None
    return CACHE.get(key)



def _cache_set(settings: Settings, key: str, value: Any, ttl_seconds: int) -> None:
    if not settings.cache_enabled:
        return
    CACHE.set(key, value, ttl_seconds=ttl_seconds)



def get_dashboard_metadata(settings: Settings) -> dict[str, Any]:
    if _use_databricks_backend(settings):
        return databricks_data_service.get_dashboard_metadata(settings)
    return {
        "map": get_map_metadata(settings),
        "summary": get_summary_metadata(settings),
        "probability": get_probability_metadata(settings),
    }



def get_map_metadata(settings: Settings) -> dict[str, Any]:
    if _use_databricks_backend(settings):
        return databricks_data_service.get_map_metadata(settings)
    cache_key = build_cache_key("meta", "map")
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    map_dates, map_municipios = load_map_filter_options(str(settings.data_dir))
    payload = {
        "action": None,
        "dates": map_dates,
        "municipios": map_municipios,
        "default_date": map_dates[0] if map_dates else None,
        "default_municipio": map_municipios[0] if map_municipios else None,
        "circuits": [],
        "default_circuit": "Todos",
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
    if _use_databricks_backend(settings):
        return databricks_data_service.get_map_filter_metadata(
            settings=settings,
            action=action,
            selected_period=selected_period,
            selected_municipio=selected_municipio,
        )
    if action != "circuits":
        raise ValueError(f"Unsupported map metadata action: {action}")
    if not selected_period or not selected_municipio:
        raise ValueError("selected_period and selected_municipio are required for map metadata")

    cache_key = build_cache_key("meta", "map", action, selected_period, selected_municipio)
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    dataset = load_map_dataset(str(settings.data_dir))
    circuits = get_map_circuit_options(
        dataset,
        selected_period=selected_period,
        selected_municipio=selected_municipio,
    )
    payload = {
        "action": action,
        "dates": [],
        "municipios": [],
        "default_date": selected_period,
        "default_municipio": selected_municipio,
        "circuits": circuits,
        "default_circuit": circuits[0] if circuits else "Todos",
        "outputs": MAP_OUTPUT_OPTIONS,
        "default_output": MAP_OUTPUT_OPTIONS[0],
    }
    _cache_set(settings, cache_key, payload, METADATA_CACHE_SECONDS)
    return payload


def get_summary_metadata(settings: Settings) -> dict[str, Any]:
    if _use_databricks_backend(settings):
        return databricks_data_service.get_summary_metadata(settings)
    cache_key = build_cache_key("meta", "summary")
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    summary_dataset = load_summary_dataset(str(settings.data_dir))
    circuits = get_circuit_options(summary_dataset)
    default_start, default_end = get_default_window(summary_dataset, days=180)
    payload = {
        "circuits": circuits,
        "default_circuit": circuits[0] if circuits else None,
        "min_date": summary_dataset.min_date.isoformat(),
        "max_date": summary_dataset.max_date.isoformat(),
        "default_start": default_start.isoformat(),
        "default_end": default_end.isoformat(),
    }
    _cache_set(settings, cache_key, payload, METADATA_CACHE_SECONDS)
    return payload



def get_probability_metadata(settings: Settings) -> dict[str, Any]:
    if _use_databricks_backend(settings):
        return databricks_data_service.get_probability_metadata(settings)
    cache_key = build_cache_key("meta", "probability", "criteria")
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
    if _use_databricks_backend(settings):
        return databricks_data_service.get_probability_columns_metadata(settings, criteria)
    if not criteria:
        raise ValueError("criteria is required for probability columns metadata")

    cache_key = build_cache_key("meta", "probability", "columns", criteria)
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    dataset = load_probability_dataset(str(settings.data_dir))
    source_df = get_dataframe_by_criteria(dataset, criteria)
    if source_df is None:
        raise ValueError("Criterio no válido")

    payload = {
        "action": "columns",
        "criteria_options": [],
        "columns": source_df.columns.astype(str).tolist(),
        "filter_kind": None,
        "value_options": [],
        "is_empty": False,
        "message": None,
    }
    _cache_set(settings, cache_key, payload, PROBABILITY_META_CACHE_SECONDS)
    return payload



def _serialize_value_options(series: pd.Series) -> list[str]:
    unique_values = series.dropna().unique().tolist()
    as_strings: list[str] = []
    for value in unique_values:
        if isinstance(value, pd.Timestamp):
            as_strings.append(value.date().isoformat())
        else:
            as_strings.append(str(value))

    as_strings = sorted({value for value in as_strings if value != ""})
    if len(as_strings) > MAX_PROBABILITY_VALUE_OPTIONS:
        return as_strings[:MAX_PROBABILITY_VALUE_OPTIONS]
    return as_strings



def get_probability_filter_options_metadata(
    settings: Settings,
    criteria: str,
    selected_column: str,
    previous_filters: list[list[Any]],
) -> dict[str, Any]:
    if _use_databricks_backend(settings):
        return databricks_data_service.get_probability_filter_options_metadata(
            settings=settings,
            criteria=criteria,
            selected_column=selected_column,
            previous_filters=previous_filters,
        )
    if not criteria:
        raise ValueError("criteria is required for probability filter metadata")
    if not selected_column:
        raise ValueError("selected_column is required for probability filter metadata")

    cache_key = build_cache_key(
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

    dataset = load_probability_dataset(str(settings.data_dir))
    source_df = get_dataframe_by_criteria(dataset, criteria)
    if source_df is None:
        raise ValueError("Criterio no válido")

    filtered_df = apply_filters(source_df, previous_filters)
    if selected_column not in filtered_df.columns:
        raise ValueError(f"La columna '{selected_column}' no existe para el criterio seleccionado")

    series = filtered_df[selected_column]
    dtype_name = series.dtype.name
    filter_kind = infer_filter_type(dtype_name)

    if filter_kind == "":
        raise ValueError(f"No se soporta el tipo de filtro para la columna '{selected_column}'")

    is_empty = filtered_df.empty
    value_options: list[str] = []
    if filter_kind in {"seleccion", "fecha"}:
        value_options = _serialize_value_options(series)

    payload = {
        "action": "filter_options",
        "criteria_options": [],
        "columns": [],
        "filter_kind": filter_kind,
        "value_options": value_options,
        "is_empty": is_empty,
        "message": "No hay opciones con filtros previos." if is_empty else None,
    }
    _cache_set(settings, cache_key, payload, PROBABILITY_META_CACHE_SECONDS)
    return payload



def get_map_payload(
    settings: Settings,
    selected_period: str,
    selected_municipio: str,
    selected_circuit: str | None,
    selected_output: str | None,
    day: int,
    selected_circuits: list[str] | None = None,
) -> dict[str, Any]:
    if _use_databricks_backend(settings):
        return databricks_data_service.get_map_payload(
            settings=settings,
            selected_period=selected_period,
            selected_municipio=selected_municipio,
            selected_circuit=selected_circuit,
            selected_circuits=selected_circuits,
            selected_output=selected_output,
            day=day,
        )
    if not selected_period or not selected_municipio:
        raise ValueError("selected_period and selected_municipio are required")

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
        "map",
        selected_period,
        selected_municipio,
        circuit_cache_token,
        normalized_output,
        str(safe_day),
    )
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    dataset = load_map_dataset(str(settings.data_dir))
    filtered = filter_map_dataset(
        dataset,
        selected_period=selected_period,
        selected_municipio=selected_municipio,
        selected_circuit=selected_circuit,
        selected_circuits=selected_circuits,
        selected_output=selected_output,
    )

    map_html = render_base_map(filtered, day=safe_day)
    if len(map_html) > settings.max_map_html_chars:
        raise ValueError(
            "Rendered map payload is too large for safe transfer. "
            "Narrow filters or increase MAX_MAP_HTML_CHARS explicitly."
        )

    status = (
        f"Mapa cargado para municipio {selected_municipio}, {circuit_label}, "
        f"salida {normalized_output}, período {selected_period}. Día actual: {safe_day}."
    )

    payload = {
        "map_html": map_html,
        "current_day": safe_day,
        "status_text": status,
    }
    _cache_set(settings, cache_key, payload, MAP_CACHE_SECONDS)
    return payload



def _daily_records(daily_data: pd.DataFrame, max_points: int) -> tuple[list[dict[str, Any]], bool]:
    if daily_data.empty:
        return [], False

    frame = daily_data.copy()
    truncated = False
    if len(frame) > max_points:
        truncated = True
        # Evenly sample to keep payloads bounded while preserving temporal shape.
        step = max(int(len(frame) / max_points), 1)
        frame = frame.iloc[::step].head(max_points)

    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        date_value = row["fecha_dia"]
        if isinstance(date_value, pd.Timestamp):
            date_str = date_value.date().isoformat()
        elif isinstance(date_value, date):
            date_str = date_value.isoformat()
        else:
            date_str = str(date_value)

        records.append(
            {
                "fecha_dia": date_str,
                "SAIDI": float(row["SAIDI"]),
                "SAIFI": float(row["SAIFI"]),
            }
        )
    return records, truncated



def get_summary_payload(
    settings: Settings,
    start_date_raw: str | None,
    end_date_raw: str | None,
    circuito: str | None,
    metric_mode: str,
) -> dict[str, Any]:
    if _use_databricks_backend(settings):
        return databricks_data_service.get_summary_payload(
            settings=settings,
            start_date_raw=start_date_raw,
            end_date_raw=end_date_raw,
            circuito=circuito,
            metric_mode=metric_mode,
        )
    dataset = load_summary_dataset(str(settings.data_dir))
    start_date, end_date = coerce_window(dataset, start_date_raw, end_date_raw)
    metric_mode = metric_mode or "BOTH"

    cache_key = build_cache_key(
        "summary",
        circuito or "TODOS",
        metric_mode,
        start_date.isoformat(),
        end_date.isoformat(),
    )
    cached = _cache_get(settings, cache_key)
    if cached is not None:
        return cached

    filtered = filter_summary_data(dataset, circuito, start_date, end_date)
    daily_data = aggregate_daily(filtered, start_date, end_date)
    kpis = compute_kpis(filtered)

    circuit_label = circuito or "TODOS"
    if filtered.empty:
        status_text = (
            f"No se encontraron eventos para el circuito {circuit_label} "
            f"entre {start_date.isoformat()} y {end_date.isoformat()}. "
            "Se muestran series en cero."
        )
    else:
        status_text = (
            f"Circuito: {circuit_label}. "
            f"Ventana: {start_date.isoformat()} a {end_date.isoformat()}. "
            f"Eventos: {kpis['event_count']}."
        )

    daily_records, truncated = _daily_records(daily_data, settings.max_summary_points)
    if truncated:
        status_text = (
            f"{status_text} Se aplicó muestreo de puntos para limitar el contenido "
            f"a {settings.max_summary_points} puntos."
        )

    payload = {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "circuit_label": circuit_label,
        "metric_mode": metric_mode,
        "saidi_total": float(kpis["saidi_total"]),
        "saifi_total": float(kpis["saifi_total"]),
        "event_count": int(kpis["event_count"]),
        "daily_data": daily_records,
        "status_text": status_text,
    }
    _cache_set(settings, cache_key, payload, SUMMARY_CACHE_SECONDS)
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
    if _use_databricks_backend(settings):
        return databricks_data_service.get_probability_payload(
            settings=settings,
            criteria=criteria,
            target_column=target_column,
            filters=filters,
        )
    if not criteria:
        raise ValueError("criteria is required")
    if not target_column:
        raise ValueError("target_column is required")

    dataset = load_probability_dataset(str(settings.data_dir))
    source_df = get_dataframe_by_criteria(dataset, criteria)
    if source_df is None:
        raise ValueError("Criterio no válido")

    filtered_df = apply_filters(source_df, filters)
    probability_text = _build_probability_text(criteria, target_column, filters)

    if filtered_df.empty:
        return {
            "probability_text": probability_text,
            "status_text": "No hay registros para la combinación seleccionada.",
            "graph_name": None,
            "graph_data_uri": None,
        }

    graph_path: Path = generate_probability_graph(
        filtered_df,
        target_column=target_column,
        probability_text=probability_text,
        output_dir=settings.output_dir,
    )
    graph_bytes = graph_path.read_bytes()
    graph_data_uri = f"data:image/png;base64,{base64.b64encode(graph_bytes).decode('ascii')}"

    return {
        "probability_text": probability_text,
        "status_text": "Distribución generada correctamente.",
        "graph_name": graph_path.name,
        "graph_data_uri": graph_data_uri,
    }
