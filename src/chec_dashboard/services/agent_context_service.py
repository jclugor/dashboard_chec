from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

import pandas as pd

from chec_dashboard.core.config import Settings
from chec_dashboard.services import databricks_data_service
from chec_dashboard.services.databricks_sql import DatabricksSQLWarehouseClient, sql_literal
from chec_dashboard.services.map_service import (
    FilteredMapDataset,
    filter_map_dataset,
    load_map_dataset,
)


SPANISH_STOPWORDS = {
    "para",
    "por",
    "con",
    "sin",
    "del",
    "las",
    "los",
    "una",
    "uno",
    "que",
    "como",
    "sobre",
    "esta",
    "este",
    "estos",
    "estas",
    "entre",
    "desde",
    "hacia",
    "cual",
    "cuales",
    "estado",
    "evento",
    "elemento",
}

BRIEFING_TYPES = {"reliability", "compliance", "maintenance"}

GUIDED_QUESTIONS: dict[str, list[dict[str, str]]] = {
    "reliability": [
        {
            "id": "reliability_saidi_saifi",
            "label": "SAIDI / SAIFI",
            "question": "¿Qué explica el comportamiento de SAIDI/SAIFI en esta vista?",
        },
        {
            "id": "reliability_hotspots",
            "label": "Concentración",
            "question": "¿Qué circuitos o municipios concentran mayor impacto histórico?",
        },
        {
            "id": "reliability_recurrence",
            "label": "Recurrencia",
            "question": "¿Este evento se parece a fallas recurrentes del mismo circuito/equipo?",
        },
        {
            "id": "reliability_external",
            "label": "Entorno",
            "question": "¿Hay señales de lluvia, viento, rayos o vegetación asociadas?",
        },
    ],
    "compliance": [
        {
            "id": "compliance_requirements",
            "label": "Requisitos",
            "question": "¿Qué requisitos técnicos aplican a este evento o activo?",
        },
        {
            "id": "compliance_risk_flags",
            "label": "Banderas",
            "question": "¿Qué señales sugieren posible incumplimiento o riesgo regulatorio?",
        },
        {
            "id": "compliance_missing_data",
            "label": "Datos faltantes",
            "question": "¿Qué información falta para sustentar una conclusión de cumplimiento?",
        },
        {
            "id": "compliance_creg_quality",
            "label": "CREG 015",
            "question": "¿Cómo se relaciona esto con calidad del servicio SAIDI/SAIFI bajo CREG 015?",
        },
    ],
    "maintenance": [
        {
            "id": "maintenance_field_checks",
            "label": "Campo",
            "question": "¿Qué revisión de campo debería priorizarse?",
        },
        {
            "id": "maintenance_priority_assets",
            "label": "Priorización",
            "question": "¿Qué activos o circuitos ameritan intervención preventiva?",
        },
        {
            "id": "maintenance_root_cause",
            "label": "Causa raíz",
            "question": "¿Qué causa raíz probable se puede investigar primero?",
        },
        {
            "id": "maintenance_pre_rainy",
            "label": "Lluvias",
            "question": "¿Qué acciones reducirían recurrencia antes de temporada de lluvias?",
        },
    ],
}

BRIEFING_LABELS = {
    "reliability": "Confiabilidad",
    "compliance": "Cumplimiento",
    "maintenance": "Mantenimiento",
}


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = "".join(
        char
        for char in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9_./:-]+", " ", text).strip()


def tokenize_text(value: Any) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if len(token) >= 3 and token not in SPANISH_STOPWORDS
    }


def json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def row_context(row: pd.Series, *, kind: str, family: str | None = None) -> dict[str, Any]:
    context = {
        str(column): json_safe(value)
        for column, value in row.items()
        if json_safe(value) not in {None, ""}
    }
    context["kind"] = kind
    if family:
        context["family"] = family
    return context


def context_id(kind: str, context: dict[str, Any]) -> str:
    payload = json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}"


def sanitize_briefing_type(briefing_type: str | None) -> str:
    if briefing_type in BRIEFING_TYPES:
        return str(briefing_type)
    return "reliability"


def guided_question_text(briefing_type: str, question_id: str | None) -> str | None:
    if not question_id:
        return None
    for question in GUIDED_QUESTIONS.get(briefing_type, []):
        if question["id"] == question_id:
            return question["question"]
    return None


def resolve_question(briefing_type: str, question_id: str | None, question: str | None) -> str:
    guided_question = guided_question_text(briefing_type, question_id)
    parts = [guided_question] if guided_question else []
    cleaned_question = (question or "").strip()
    if cleaned_question:
        parts.append(cleaned_question)
    if parts:
        return "\n".join(parts)
    fallback = GUIDED_QUESTIONS.get(briefing_type, GUIDED_QUESTIONS["reliability"])[0]
    return fallback["question"]


def first_existing_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def numeric_series(frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
    column = first_existing_column(frame, candidates)
    if column is None or frame.empty:
        return pd.Series([0.0] * len(frame), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def series_total(frame: pd.DataFrame, candidates: list[str]) -> float:
    if frame.empty:
        return 0.0
    return float(numeric_series(frame, candidates).sum())


def rounded(value: float | int | None, digits: int = 4) -> float:
    try:
        return round(float(value or 0.0), digits)
    except (TypeError, ValueError):
        return 0.0


def date_bounds(frame: pd.DataFrame, candidates: list[str]) -> dict[str, str | None]:
    column = first_existing_column(frame, candidates)
    if column is None or frame.empty:
        return {"start": None, "end": None}
    dates = pd.to_datetime(frame[column], errors="coerce").dropna()
    if dates.empty:
        return {"start": None, "end": None}
    return {
        "start": dates.min().isoformat(),
        "end": dates.max().isoformat(),
    }


def top_records_from_frame(
    frame: pd.DataFrame,
    group_candidates: list[str],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    group_column = first_existing_column(frame, group_candidates)
    if group_column is None or frame.empty:
        return []
    work = pd.DataFrame(
        {
            "group": frame[group_column].fillna("Sin dato").astype(str).str.strip(),
            "saidi": numeric_series(frame, ["severity_saidi", "SAIDI", "saidi_total"]),
            "saifi": numeric_series(frame, ["severity_saifi", "SAIFI", "saifi_total"]),
            "duration_h": numeric_series(frame, ["duration_hours", "duracion_h", "duration_total_h"]),
            "users_affected": numeric_series(frame, ["cnt_usus", "users_affected_total"]),
            "event_count": numeric_series(frame, ["event_count"]),
        }
    )
    if work["event_count"].sum() == 0:
        work["event_count"] = 1
    grouped = (
        work[work["group"] != ""]
        .groupby("group", dropna=False)
        .agg(
            event_count=("event_count", "sum"),
            saidi=("saidi", "sum"),
            saifi=("saifi", "sum"),
            duration_h=("duration_h", "sum"),
            users_affected=("users_affected", "sum"),
        )
        .reset_index()
    )
    if grouped.empty:
        return []
    grouped["impact_score"] = grouped["saidi"] + grouped["saifi"]
    grouped = grouped.sort_values(
        ["impact_score", "event_count", "duration_h"],
        ascending=[False, False, False],
    ).head(limit)
    return [
        {
            "label": str(row["group"]),
            "event_count": int(row["event_count"]),
            "saidi": rounded(row["saidi"]),
            "saifi": rounded(row["saifi"]),
            "duration_h": rounded(row["duration_h"], 2),
            "users_affected": int(row["users_affected"]),
        }
        for _, row in grouped.iterrows()
    ]


def weather_columns(context: dict[str, Any] | pd.DataFrame, metric: str) -> list[str]:
    columns = context.columns if isinstance(context, pd.DataFrame) else context.keys()
    suffix = f"-{metric}"
    return [str(column) for column in columns if str(column).endswith(suffix)]


def external_signals_from_frame(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}

    def metric_summary(metric: str, reducer: str) -> float | None:
        columns = weather_columns(frame, metric)
        if not columns:
            return None
        values = pd.to_numeric(frame[columns].stack(), errors="coerce").dropna()
        if values.empty:
            return None
        if reducer == "sum":
            return rounded(float(values.sum()), 2)
        if reducer == "mean":
            return rounded(float(values.mean()), 2)
        return rounded(float(values.max()), 2)

    signals = {
        "precip_total_mm": metric_summary("precip", "sum"),
        "precip_max_mm_h": metric_summary("precip", "max"),
        "wind_gust_max": metric_summary("wind_gust_spd", "max"),
        "wind_speed_max": metric_summary("wind_spd", "max"),
        "humidity_avg": metric_summary("rh", "mean"),
        "temperature_avg_c": metric_summary("temp", "mean"),
    }
    return {key: value for key, value in signals.items() if value is not None}


def external_signals_from_context(context: dict[str, Any]) -> dict[str, Any]:
    if not context:
        return {}
    frame = pd.DataFrame([context])
    return external_signals_from_frame(frame)


def selected_circuits_payload(selected_circuits: list[str] | None) -> list[str] | None:
    if selected_circuits is None:
        return None
    return [str(circuit) for circuit in selected_circuits if str(circuit).strip()]


def view_context_from_events(
    frame: pd.DataFrame,
    *,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None,
) -> dict[str, Any]:
    selected_circuits = selected_circuits_payload(selected_circuits)
    saidi_total = series_total(frame, ["severity_saidi", "SAIDI", "saidi_total"])
    saifi_total = series_total(frame, ["severity_saifi", "SAIFI", "saifi_total"])
    event_count = int(series_total(frame, ["event_count"])) if "event_count" in frame.columns else int(len(frame))
    duration_total_h = series_total(frame, ["duration_hours", "duracion_h", "duration_total_h"])
    users_affected = series_total(frame, ["cnt_usus", "users_affected_total"])
    return {
        "kind": "view",
        "selected_period": selected_period,
        "selected_municipio": selected_municipio,
        "selected_circuits": selected_circuits,
        "scope_label": "todos los circuitos" if selected_circuits is None else ", ".join(selected_circuits) or "sin circuitos",
        "date_bounds": date_bounds(frame, ["fecha_dia", "inicio_ts", "inicio", "map_date"]),
        "kpi_summary": {
            "event_count": event_count,
            "saidi_total": rounded(saidi_total),
            "saifi_total": rounded(saifi_total),
            "duration_total_h": rounded(duration_total_h, 2),
            "users_affected_total": int(users_affected),
        },
        "top_circuits": top_records_from_frame(frame, ["circuito", "cto_equi_ope", "FPARENT"]),
        "top_event_families": top_records_from_frame(frame, ["event_family", "tipo_equi_ope"]),
        "top_causes": top_records_from_frame(frame, ["causa"]),
        "external_signals": external_signals_from_frame(frame),
    }


def view_item_from_context(context: dict[str, Any]) -> dict[str, Any]:
    selected_period = context.get("selected_period") or "Sin periodo"
    municipio = context.get("selected_municipio") or "Sin municipio"
    scope = context.get("scope_label") or "todos los circuitos"
    kpis = context.get("kpi_summary") or {}
    summary = (
        f"Vista {municipio} / {selected_period} / {scope}. "
        f"Eventos: {kpis.get('event_count', 0)}, "
        f"SAIDI: {kpis.get('saidi_total', 0)}, "
        f"SAIFI: {kpis.get('saifi_total', 0)}."
    )
    return {
        "id": context_id("view", context),
        "label": f"Vista filtrada | {municipio} | {selected_period} | {scope}"[:180],
        "kind": "view",
        "summary": summary,
        "context": context,
    }


def context_search_matches(context: dict[str, Any], search: str | None) -> bool:
    if not search:
        return True
    search_tokens = tokenize_text(search)
    if not search_tokens:
        return True
    haystack = tokenize_text(" ".join(str(value) for value in context.values()))
    return bool(search_tokens & haystack)


def event_items_from_frame(frame: pd.DataFrame, *, search: str | None, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for _, row in frame.head(max(limit * 3, limit)).iterrows():
        context = row_context(row, kind="event")
        if not context_search_matches(context, search):
            continue
        inicio = context.get("inicio") or context.get("inicio_ts") or context.get("map_date")
        circuito = context.get("cto_equi_ope") or context.get("circuito") or "Sin circuito"
        equipo = context.get("equipo_ope") or context.get("display_label") or "Evento"
        causa = context.get("causa") or context.get("event_family") or "Sin causa"
        label = f"{equipo} | {circuito} | {causa} | {inicio}"
        summary = (
            f"Evento en circuito {circuito}. Causa: {causa}. "
            f"SAIDI: {context.get('SAIDI') or context.get('severity_saidi') or 'N/D'}, "
            f"SAIFI: {context.get('SAIFI') or context.get('severity_saifi') or 'N/D'}."
        )
        items.append(
            {
                "id": context_id("event", context),
                "label": label[:180],
                "kind": "event",
                "summary": summary,
                "context": context,
            }
        )
        if len(items) >= limit:
            break
    return items


def asset_items_from_filtered(
    filtered: FilteredMapDataset,
    *,
    search: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    frames = [
        ("Transformador", filtered.trafos),
        ("Apoyo", filtered.apoyos),
        ("Seccionador", filtered.switches),
        ("Tramo de red MT", filtered.redmt),
    ]
    items: list[dict[str, Any]] = []
    for family, frame in frames:
        for _, row in frame.head(max(limit * 2, limit)).iterrows():
            context = row_context(row, kind="asset", family=family)
            if not context_search_matches(context, search):
                continue
            code = context.get("CODE") or context.get("display_label") or family
            circuito = context.get("FPARENT") or context.get("circuito") or "Sin circuito"
            municipio = context.get("MUN") or context.get("municipio") or "Sin municipio"
            label = f"{family} {code} | {circuito} | {municipio}"
            summary = f"{family} asociado al circuito {circuito} en {municipio}."
            items.append(
                {
                    "id": context_id("asset", context),
                    "label": label[:180],
                    "kind": "asset",
                    "summary": summary,
                    "context": context,
                }
            )
            if len(items) >= limit:
                return items
    return items


def selected_circuits_where(selected_circuits: list[str] | None) -> str:
    if selected_circuits is None:
        return ""
    if not selected_circuits:
        return " AND 1 = 0"
    if len(selected_circuits) == 1:
        return f" AND circuito = {sql_literal(selected_circuits[0])}"
    literals = ", ".join(sql_literal(circuit) for circuit in selected_circuits)
    return f" AND circuito IN ({literals})"


def databricks_view_items(
    settings: Settings,
    *,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None,
) -> list[dict[str, Any]]:
    client = DatabricksSQLWarehouseClient(settings)
    daily_table = databricks_data_service._gold_table(settings, "gold_saidi_saifi_daily")
    where_clause = (
        f"DATE_FORMAT(CAST(fecha_dia AS DATE), 'yyyy-MM') = {sql_literal(selected_period)} "
        f"AND municipio = {sql_literal(selected_municipio)}"
        f"{selected_circuits_where(selected_circuits)}"
    )
    daily_frame = client.fetch_dataframe(
        f"""
        SELECT
          CAST(fecha_dia AS DATE) AS fecha_dia,
          circuito,
          municipio,
          event_family,
          COALESCE(saidi_total, 0.0) AS saidi_total,
          COALESCE(saifi_total, 0.0) AS saifi_total,
          COALESCE(event_count, 0) AS event_count,
          COALESCE(duration_total_h, 0.0) AS duration_total_h,
          COALESCE(users_affected_total, 0.0) AS users_affected_total
        FROM {daily_table}
        WHERE {where_clause}
        """
    )

    context = view_context_from_events(
        daily_frame,
        selected_period=selected_period,
        selected_municipio=selected_municipio,
        selected_circuits=selected_circuits,
    )

    try:
        events_table = databricks_data_service._gold_table(settings, "gold_map_event_days")
        events_frame = client.fetch_dataframe(
            f"""
            SELECT *
            FROM {events_table}
            WHERE map_period = {sql_literal(selected_period)}
              AND municipio = {sql_literal(selected_municipio)}
              {selected_circuits_where(selected_circuits)}
            LIMIT 5000
            """
        )
    except Exception:
        events_frame = pd.DataFrame()

    if not events_frame.empty:
        context["top_causes"] = top_records_from_frame(events_frame, ["causa"])
        context["external_signals"] = external_signals_from_frame(events_frame)

    return [view_item_from_context(context)]


def databricks_context_options(
    settings: Settings,
    *,
    context_kind: str,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None,
    search: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    client = DatabricksSQLWarehouseClient(settings)
    where_clause = (
        f"map_period = {sql_literal(selected_period)} "
        f"AND municipio = {sql_literal(selected_municipio)}"
        f"{selected_circuits_where(selected_circuits)}"
    )
    if context_kind == "view":
        return databricks_view_items(
            settings,
            selected_period=selected_period,
            selected_municipio=selected_municipio,
            selected_circuits=selected_circuits,
        )
    if context_kind == "event":
        table = databricks_data_service._gold_table(settings, "gold_map_event_days")
        frame = client.fetch_dataframe(
            f"""
            SELECT *
            FROM {table}
            WHERE {where_clause}
            ORDER BY map_day, equipo_ope
            LIMIT {int(limit)}
            """
        )
        return event_items_from_frame(frame, search=search, limit=limit)

    points_table = databricks_data_service._gold_table(settings, "gold_map_points")
    lines_table = databricks_data_service._gold_table(settings, "gold_map_line_segments")
    points = client.fetch_dataframe(
        f"""
        SELECT *
        FROM {points_table}
        WHERE point_kind = 'asset' AND {where_clause}
        ORDER BY asset_family, display_label
        LIMIT {int(limit)}
        """
    )
    lines = client.fetch_dataframe(
        f"""
        SELECT *
        FROM {lines_table}
        WHERE {where_clause}
        ORDER BY asset_family, display_label
        LIMIT {int(limit)}
        """
    )
    if points.empty or "asset_family" not in points:
        filtered_points = (points, points, points)
    else:
        asset_family = points["asset_family"]
        filtered_points = (
            points[asset_family == "Transformers"].copy(),
            points[asset_family == "Supports"].copy(),
            points[asset_family == "Switches"].copy(),
        )
    filtered = FilteredMapDataset(
        trafos=filtered_points[0],
        apoyos=filtered_points[1],
        switches=filtered_points[2],
        redmt=lines,
        events_by_day=[],
    )
    return asset_items_from_filtered(filtered, search=search, limit=limit)


def get_chatbot_context_options(
    settings: Settings,
    *,
    context_kind: str,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None,
    search: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    if not selected_period or not selected_municipio:
        return {"items": [], "status_text": "Selecciona período y municipio para buscar contexto."}

    safe_limit = max(1, min(int(limit), 200))
    if settings.data_backend == "databricks_sql":
        items = databricks_context_options(
            settings,
            context_kind=context_kind,
            selected_period=selected_period,
            selected_municipio=selected_municipio,
            selected_circuits=selected_circuits,
            search=search,
            limit=safe_limit,
        )
    else:
        dataset = load_map_dataset(str(settings.data_dir))
        filtered = filter_map_dataset(
            dataset,
            selected_period=selected_period,
            selected_municipio=selected_municipio,
            selected_circuits=selected_circuits,
            selected_output="BASE",
        )
        if context_kind == "view":
            events = pd.concat(filtered.events_by_day, ignore_index=True) if filtered.events_by_day else pd.DataFrame()
            context = view_context_from_events(
                events,
                selected_period=selected_period,
                selected_municipio=selected_municipio,
                selected_circuits=selected_circuits,
            )
            items = [view_item_from_context(context)]
        elif context_kind == "event":
            events = pd.concat(filtered.events_by_day, ignore_index=True) if filtered.events_by_day else pd.DataFrame()
            items = event_items_from_frame(events, search=search, limit=safe_limit)
        else:
            items = asset_items_from_filtered(filtered, search=search, limit=safe_limit)

    label = {
        "view": "vistas filtradas",
        "event": "eventos",
        "asset": "elementos de red",
    }.get(context_kind, "contextos")
    status = (
        f"Se encontraron {len(items)} {label} para {selected_municipio} en {selected_period}."
        if items
        else f"No se encontraron {label} con esos filtros."
    )
    return {"items": items, "status_text": status}


def has_context_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    try:
        if bool(pd.isna(value)):
            return False
    except (TypeError, ValueError):
        pass
    return True


def context_identity(context: dict[str, Any]) -> dict[str, Any]:
    identity_keys = [
        "kind",
        "family",
        "selected_period",
        "selected_municipio",
        "selected_circuits",
        "scope_label",
        "evento",
        "equipo_ope",
        "display_label",
        "CODE",
        "cto_equi_ope",
        "circuito",
        "FPARENT",
        "MUN",
        "municipio",
        "inicio",
        "inicio_ts",
        "fin",
        "fin_ts",
        "causa",
        "event_family",
        "tipo_equi_ope",
        "tipo_elemento",
    ]
    identity: dict[str, Any] = {}
    for key in identity_keys:
        value = context.get(key)
        if not has_context_value(value):
            continue
        identity[key] = value
    return identity


def selected_context_metrics(context: dict[str, Any]) -> dict[str, Any]:
    metric_candidates = {
        "saidi": ["SAIDI", "severity_saidi", "saidi_total"],
        "saifi": ["SAIFI", "severity_saifi", "saifi_total"],
        "duration_h": ["duracion_h", "duration_hours", "duration_total_h"],
        "users_affected": ["cnt_usus", "users_affected_total"],
        "transformers_affected": ["CNT_TRAFOS_AFEC"],
        "kva": ["KVA"],
        "kv": ["KV", "KV1", "KVNOM"],
        "length": ["LENGTH"],
        "capacity": ["CAPACITY"],
        "resistance": ["RESISTANCE"],
        "impedance": ["IMPEDANCE"],
    }
    metrics: dict[str, Any] = {}
    for metric_name, candidates in metric_candidates.items():
        for candidate in candidates:
            value = context.get(candidate)
            if has_context_value(value):
                metrics[metric_name] = value
                break
    return metrics


def build_chatbot_context_package(
    *,
    selected_context: dict[str, Any],
    briefing_type: str,
    question_id: str | None,
) -> dict[str, Any]:
    context_kind = str(selected_context.get("kind") or selected_context.get("context_kind") or "event")
    selected_external_signals = selected_context.get("external_signals")
    if not isinstance(selected_external_signals, dict):
        selected_external_signals = external_signals_from_context(selected_context)
    package: dict[str, Any] = {
        "tipo_analisis": briefing_type,
        "nombre_analisis": BRIEFING_LABELS.get(briefing_type, "Confiabilidad"),
        "question_id": question_id,
        "context_kind": context_kind,
        "selected_context": context_identity(selected_context),
        "metrics": selected_context_metrics(selected_context),
        "external_signals": selected_external_signals,
    }
    if context_kind == "view":
        package["view_context"] = selected_context
    else:
        for key in (
            "kpi_summary",
            "date_bounds",
            "top_circuits",
            "top_event_families",
            "top_causes",
            "external_signals",
        ):
            if key in selected_context and key not in package:
                package[key] = selected_context[key]
    package["data_source_scope"] = (
        "Datos internos CHEC disponibles en el dashboard: eventos, activos, "
        "SAIDI/SAIFI, ubicación, causas y variables ambientales cuando están presentes."
    )
    package["response_guardrails"] = {
        "compliance": (
            "Usar banderas de evidencia y datos faltantes; no emitir aprobado/reprobado, "
            "puntuaciones formales ni conclusiones legales definitivas."
        ),
        "citations": "Citar documentos recuperados con [1], [2], etc. cuando soporten una afirmación.",
    }
    return package


_normalize_text = normalize_text
_tokenize = tokenize_text
_json_safe = json_safe
_context_id = context_id
_sanitize_briefing_type = sanitize_briefing_type
_resolve_question = resolve_question
