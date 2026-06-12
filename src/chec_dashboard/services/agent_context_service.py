from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

import pandas as pd

from chec_dashboard.core.config import Settings
from chec_dashboard.services.databricks_sql import DatabricksSQLWarehouseClient, sql_literal, sql_table_name
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
            "id": "reliability_impact_uiti",
            "label": "Impacto UITI",
            "question": "¿Qué explica el impacto UITI en esta vista?",
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
            "question": "¿Cómo se relaciona esto con calidad del servicio e interrupciones bajo CREG 015?",
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

AGENT_CONTEXT_VIEWS = {
    "view": "gold_agent_view_context",
    "event": "gold_agent_event_context",
    "asset": "gold_agent_asset_context",
    "circuit_history": "gold_agent_circuit_history",
}

AGENT_CONTEXT_FUNCTIONS = {
    "dashboard": "get_dashboard_context",
    "reliability": "get_reliability_summary",
    "compliance": "get_compliance_context",
    "event": "get_event_context",
    "asset": "get_asset_context",
    "circuit_history": "get_circuit_history",
}

MAX_CONTEXT_TOOL_RECORDS = 50


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


def json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned_dict = {}
        for key, item in value.items():
            cleaned = json_clean(item)
            if has_clean_value(cleaned):
                cleaned_dict[str(key)] = cleaned
        return cleaned_dict
    if isinstance(value, (list, tuple, set)):
        cleaned_items = []
        for item in value:
            cleaned = json_clean(item)
            if has_clean_value(cleaned):
                cleaned_items.append(cleaned)
        return cleaned_items
    return json_safe(value)


def has_clean_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


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


def context_tools_schema(settings: Settings) -> str:
    return settings.chatbot_context_tools_schema


def context_tool_function_name(settings: Settings, function_name: str) -> str:
    return sql_table_name(settings.databricks_catalog_name, context_tools_schema(settings), function_name)


def context_tool_view_name(settings: Settings, view_name: str) -> str:
    return sql_table_name(settings.databricks_catalog_name, settings.databricks_gold_schema, view_name)


def selected_circuits_argument(selected_circuits: list[str] | None) -> str:
    if selected_circuits is None:
        return "Todos"
    return ",".join(str(circuit).strip() for circuit in selected_circuits if str(circuit).strip())


def build_context_tool_payload(
    *,
    kind: str,
    tool_name: str,
    source_function: str,
    source_view: str,
    parameters: dict[str, Any],
    summary: dict[str, Any],
    records: list[dict[str, Any]] | None = None,
    metrics: dict[str, Any] | None = None,
    traceability: dict[str, Any] | None = None,
    compatibility_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bounded_records = [json_clean(record) for record in (records or [])[:MAX_CONTEXT_TOOL_RECORDS]]
    payload = {
        "kind": kind,
        "tool_name": tool_name,
        "source_function": source_function,
        "source_view": source_view,
        "parameters": json_clean(parameters),
        "summary": json_clean(summary),
        "records": bounded_records,
        "metrics": json_clean(metrics or {}),
        "traceability": json_clean(traceability or {}),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    payload["context_hash"] = digest[:16]
    payload["context_id"] = f"{kind}-{digest[:16]}"
    for key, value in (compatibility_fields or {}).items():
        cleaned = json_clean(value)
        if has_clean_value(cleaned):
            payload[key] = cleaned
    return payload


def _local_source_function(function_name: str) -> str:
    return f"local.agent_tools.{function_name}"


def _local_source_view(view_name: str) -> str:
    return f"local.gold.{view_name}"


def _tool_payload_from_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def fetch_databricks_context_tool(
    settings: Settings,
    function_name: str,
    *arguments: Any,
) -> dict[str, Any]:
    if function_name not in set(AGENT_CONTEXT_FUNCTIONS.values()):
        raise ValueError(f"Unsupported governed context function: {function_name}")
    client = DatabricksSQLWarehouseClient(settings)
    function_ref = context_tool_function_name(settings, function_name)
    argument_sql = ", ".join(sql_literal(argument) for argument in arguments)
    payload = client.fetch_scalar(f"SELECT {function_ref}({argument_sql}) AS payload", default="{}")
    return _tool_payload_from_json(payload)


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
            "uiti": numeric_series(frame, ["UITI", "uiti_total", "severity_uiti"]),
            "uiti_vano": numeric_series(
                frame,
                ["UITI_VANO", "uiti_vano_total", "severity_uiti_vano"],
            ),
            "duration_raw": numeric_series(frame, ["DURATION_RAW", "duration_raw", "duration_raw_total", "duration_hours", "duracion_h", "duration_total_h"]),
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
            uiti=("uiti", "sum"),
            uiti_vano=("uiti_vano", "sum"),
            duration_raw=("duration_raw", "sum"),
            users_affected=("users_affected", "sum"),
        )
        .reset_index()
    )
    if grouped.empty:
        return []
    grouped["impact_score"] = grouped["uiti"] + grouped["uiti_vano"]
    grouped = grouped.sort_values(
        ["impact_score", "event_count", "duration_raw"],
        ascending=[False, False, False],
    ).head(limit)
    return [
        {
            "label": str(row["group"]),
            "event_count": int(row["event_count"]),
            "uiti": rounded(row["uiti"]),
            "uiti_vano": rounded(row["uiti_vano"]),
            "duration_raw": rounded(row["duration_raw"], 2),
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
    uiti_total = series_total(frame, ["UITI", "uiti_total", "severity_uiti"])
    uiti_vano_total = series_total(
        frame,
        ["UITI_VANO", "uiti_vano_total", "severity_uiti_vano"],
    )
    event_count = int(series_total(frame, ["event_count"])) if "event_count" in frame.columns else int(len(frame))
    duration_raw_total = series_total(frame, ["DURATION_RAW", "duration_raw", "duration_raw_total", "duration_hours", "duracion_h", "duration_total_h"])
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
            "uiti_total": rounded(uiti_total),
            "uiti_vano_total": rounded(uiti_vano_total),
            "duration_raw_total": rounded(duration_raw_total, 2),
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
        f"UITI: {kpis.get('uiti_total', 0)}, "
        f"UITI vano: {kpis.get('uiti_vano_total', 0)}."
    )
    return {
        "id": context_id("view", context),
        "label": f"Vista filtrada | {municipio} | {selected_period} | {scope}"[:180],
        "kind": "view",
        "summary": summary,
        "context": dashboard_context_tool_payload(context),
    }


def dashboard_context_tool_payload(
    context: dict[str, Any],
    *,
    source_function: str | None = None,
    source_view: str | None = None,
    tool_name: str = "get_dashboard_context",
) -> dict[str, Any]:
    selected_period = context.get("selected_period") or "Sin periodo"
    municipio = context.get("selected_municipio") or "Sin municipio"
    scope = context.get("scope_label") or "todos los circuitos"
    kpis = context.get("kpi_summary") or {}
    summary_text = (
        f"Vista {municipio} / {selected_period} / {scope}. "
        f"Eventos: {kpis.get('event_count', 0)}, "
        f"UITI: {kpis.get('uiti_total', 0)}, "
        f"UITI vano: {kpis.get('uiti_vano_total', 0)}."
    )
    records: list[dict[str, Any]] = []
    for record_type in ("top_circuits", "top_event_families", "top_causes"):
        for record in context.get(record_type) or []:
            if isinstance(record, dict):
                records.append({"record_type": record_type, **record})
    return build_context_tool_payload(
        kind="view",
        tool_name=tool_name,
        source_function=source_function or _local_source_function(tool_name),
        source_view=source_view or _local_source_view(AGENT_CONTEXT_VIEWS["view"]),
        parameters={
            "period": selected_period,
            "municipio": municipio,
            "circuits": selected_circuits_argument(context.get("selected_circuits")),
        },
        summary={
            "text": summary_text,
            "selected_period": selected_period,
            "selected_municipio": municipio,
            "scope_label": scope,
        },
        records=records,
        metrics={
            "kpi_summary": kpis,
            "date_bounds": context.get("date_bounds") or {},
            "external_signals": context.get("external_signals") or {},
        },
        traceability={
            "source_view": source_view or _local_source_view(AGENT_CONTEXT_VIEWS["view"]),
            "claim_scope": "dashboard_filter_aggregate",
            "read_only": True,
        },
        compatibility_fields={
            "selected_period": selected_period,
            "selected_municipio": municipio,
            "selected_circuits": context.get("selected_circuits"),
            "scope_label": scope,
            "date_bounds": context.get("date_bounds"),
            "kpi_summary": kpis,
            "top_circuits": context.get("top_circuits"),
            "top_event_families": context.get("top_event_families"),
            "top_causes": context.get("top_causes"),
            "external_signals": context.get("external_signals"),
        },
    )


def context_search_matches(context: dict[str, Any], search: str | None) -> bool:
    if not search:
        return True
    search_tokens = tokenize_text(search)
    if not search_tokens:
        return True
    haystack = tokenize_text(" ".join(str(value) for value in context.values()))
    return bool(search_tokens & haystack)


def event_tool_payload(
    context: dict[str, Any],
    *,
    source_function: str | None = None,
    source_view: str | None = None,
) -> dict[str, Any]:
    event_id = str(context.get("event_id") or context_id("event", context))
    circuito = context.get("cto_equi_ope") or context.get("circuito") or "Sin circuito"
    equipo = context.get("equipo_ope") or context.get("display_label") or "Evento"
    causa = context.get("causa") or context.get("event_family") or "Sin causa"
    inicio = context.get("inicio") or context.get("inicio_ts") or context.get("map_date")
    context = {**context, "event_id": event_id}
    return build_context_tool_payload(
        kind="event",
        tool_name="get_event_context",
        source_function=source_function or _local_source_function("get_event_context"),
        source_view=source_view or _local_source_view(AGENT_CONTEXT_VIEWS["event"]),
        parameters={"event_id": event_id},
        summary={
            "text": f"Evento {equipo} en circuito {circuito}. Causa: {causa}. Inicio: {inicio or 'N/D'}.",
            "event_id": event_id,
        },
        records=[context],
        metrics=selected_context_metrics(context),
        traceability={
            "source_view": source_view or _local_source_view(AGENT_CONTEXT_VIEWS["event"]),
            "record_id": event_id,
            "read_only": True,
        },
        compatibility_fields=context,
    )


def event_items_from_frame(
    frame: pd.DataFrame,
    *,
    search: str | None,
    limit: int,
    source_function: str | None = None,
    source_view: str | None = None,
) -> list[dict[str, Any]]:
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
            f"UITI: {context.get('UITI') or context.get('uiti_total') or 'N/D'}, "
            f"UITI vano: {context.get('UITI_VANO') or context.get('uiti_vano_total') or 'N/D'}."
        )
        tool_context = event_tool_payload(
            context,
            source_function=source_function,
            source_view=source_view,
        )
        items.append(
            {
                "id": tool_context["context_id"],
                "label": label[:180],
                "kind": "event",
                "summary": summary,
                "context": tool_context,
            }
        )
        if len(items) >= limit:
            break
    return items


def asset_tool_payload(
    context: dict[str, Any],
    *,
    source_function: str | None = None,
    source_view: str | None = None,
) -> dict[str, Any]:
    asset_id = str(context.get("asset_id") or context_id("asset", context))
    family = context.get("family") or context.get("asset_family") or "Activo"
    code = context.get("CODE") or context.get("equipo_ope") or context.get("display_label") or family
    circuito = context.get("FPARENT") or context.get("circuito") or "Sin circuito"
    municipio = context.get("MUN") or context.get("municipio") or "Sin municipio"
    context = {
        **context,
        "asset_id": asset_id,
        "CODE": code,
        "family": family,
        "FPARENT": circuito,
        "MUN": municipio,
    }
    return build_context_tool_payload(
        kind="asset",
        tool_name="get_asset_context",
        source_function=source_function or _local_source_function("get_asset_context"),
        source_view=source_view or _local_source_view(AGENT_CONTEXT_VIEWS["asset"]),
        parameters={"asset_id": asset_id},
        summary={
            "text": f"{family} {code} asociado al circuito {circuito} en {municipio}.",
            "asset_id": asset_id,
        },
        records=[context],
        metrics=selected_context_metrics(context),
        traceability={
            "source_view": source_view or _local_source_view(AGENT_CONTEXT_VIEWS["asset"]),
            "record_id": asset_id,
            "read_only": True,
        },
        compatibility_fields=context,
    )


def asset_items_from_filtered(
    filtered: FilteredMapDataset,
    *,
    search: str | None,
    limit: int,
    source_function: str | None = None,
    source_view: str | None = None,
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
            tool_context = asset_tool_payload(
                context,
                source_function=source_function,
                source_view=source_view,
            )
            items.append(
                {
                    "id": tool_context["context_id"],
                    "label": label[:180],
                    "kind": "asset",
                    "summary": summary,
                    "context": tool_context,
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


def get_dashboard_context_tool(
    settings: Settings,
    *,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None,
) -> dict[str, Any]:
    if settings.data_backend == "databricks_sql":
        return fetch_databricks_context_tool(
            settings,
            AGENT_CONTEXT_FUNCTIONS["dashboard"],
            selected_period,
            selected_municipio,
            selected_circuits_argument(selected_circuits),
        )
    dataset = load_map_dataset(str(settings.data_dir))
    filtered = filter_map_dataset(
        dataset,
        selected_period=selected_period,
        selected_municipio=selected_municipio,
        selected_circuits=selected_circuits,
        selected_output="BASE",
    )
    events = pd.concat(filtered.events_by_day, ignore_index=True) if filtered.events_by_day else pd.DataFrame()
    context = view_context_from_events(
        events,
        selected_period=selected_period,
        selected_municipio=selected_municipio,
        selected_circuits=selected_circuits,
    )
    return dashboard_context_tool_payload(context)


def get_reliability_summary_tool(
    settings: Settings,
    *,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None,
) -> dict[str, Any]:
    if settings.data_backend == "databricks_sql":
        return fetch_databricks_context_tool(
            settings,
            AGENT_CONTEXT_FUNCTIONS["reliability"],
            selected_period,
            selected_municipio,
            selected_circuits_argument(selected_circuits),
        )
    payload = get_dashboard_context_tool(
        settings,
        selected_period=selected_period,
        selected_municipio=selected_municipio,
        selected_circuits=selected_circuits,
    )
    return {**payload, "tool_name": "get_reliability_summary", "source_function": _local_source_function("get_reliability_summary")}


def get_compliance_context_tool(
    settings: Settings,
    *,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None,
) -> dict[str, Any]:
    if settings.data_backend == "databricks_sql":
        return fetch_databricks_context_tool(
            settings,
            AGENT_CONTEXT_FUNCTIONS["compliance"],
            selected_period,
            selected_municipio,
            selected_circuits_argument(selected_circuits),
        )
    payload = get_dashboard_context_tool(
        settings,
        selected_period=selected_period,
        selected_municipio=selected_municipio,
        selected_circuits=selected_circuits,
    )
    return {**payload, "tool_name": "get_compliance_context", "source_function": _local_source_function("get_compliance_context")}


def get_event_context_tool(
    settings: Settings,
    *,
    event_id: str,
    fallback_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if settings.data_backend == "databricks_sql":
        return fetch_databricks_context_tool(settings, AGENT_CONTEXT_FUNCTIONS["event"], event_id)
    return event_tool_payload({**(fallback_context or {}), "event_id": event_id})


def get_asset_context_tool(
    settings: Settings,
    *,
    asset_id: str,
    fallback_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if settings.data_backend == "databricks_sql":
        return fetch_databricks_context_tool(settings, AGENT_CONTEXT_FUNCTIONS["asset"], asset_id)
    return asset_tool_payload({**(fallback_context or {}), "asset_id": asset_id})


def get_circuit_history_tool(
    settings: Settings,
    *,
    circuit: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    if settings.data_backend == "databricks_sql":
        return fetch_databricks_context_tool(
            settings,
            AGENT_CONTEXT_FUNCTIONS["circuit_history"],
            circuit,
            start_date,
            end_date,
        )
    return build_context_tool_payload(
        kind="circuit_history",
        tool_name="get_circuit_history",
        source_function=_local_source_function("get_circuit_history"),
        source_view=_local_source_view(AGENT_CONTEXT_VIEWS["circuit_history"]),
        parameters={"circuit": circuit, "start_date": start_date, "end_date": end_date},
        summary={"text": f"Historial local del circuito {circuit} entre {start_date} y {end_date}."},
        records=[],
        metrics={},
        traceability={"read_only": True},
        compatibility_fields={"circuito": circuit},
    )


def databricks_view_items(
    settings: Settings,
    *,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None,
) -> list[dict[str, Any]]:
    context = get_dashboard_context_tool(
        settings,
        selected_period=selected_period,
        selected_municipio=selected_municipio,
        selected_circuits=selected_circuits,
    )
    selected_period = context.get("selected_period") or selected_period
    municipio = context.get("selected_municipio") or selected_municipio
    scope = context.get("scope_label") or "todos los circuitos"
    summary = (context.get("summary") or {}).get("text") or f"Vista {municipio} / {selected_period} / {scope}."
    return [
        {
            "id": context.get("context_id") or context_id("view", context),
            "label": f"Vista filtrada | {municipio} | {selected_period} | {scope}"[:180],
            "kind": "view",
            "summary": summary,
            "context": context,
        }
    ]


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
        table = context_tool_view_name(settings, AGENT_CONTEXT_VIEWS["event"])
        frame = client.fetch_dataframe(
            f"""
            SELECT *
            FROM {table}
            WHERE {where_clause}
            ORDER BY map_day, equipo_ope
            LIMIT {int(limit)}
            """
        )
        return event_items_from_frame(
            frame,
            search=search,
            limit=limit,
            source_function=context_tool_function_name(settings, AGENT_CONTEXT_FUNCTIONS["event"]),
            source_view=table,
        )

    points_table = context_tool_view_name(settings, AGENT_CONTEXT_VIEWS["asset"])
    points = client.fetch_dataframe(
        f"""
        SELECT *
        FROM {points_table}
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
    lines = points[points["asset_family"] == "LineSegments"].copy() if "asset_family" in points else points
    filtered = FilteredMapDataset(
        trafos=filtered_points[0],
        apoyos=filtered_points[1],
        switches=filtered_points[2],
        redmt=lines,
        events_by_day=[],
    )
    return asset_items_from_filtered(
        filtered,
        search=search,
        limit=limit,
        source_function=context_tool_function_name(settings, AGENT_CONTEXT_FUNCTIONS["asset"]),
        source_view=points_table,
    )


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
        "tool_name",
        "source_function",
        "source_view",
        "context_id",
        "context_hash",
        "family",
        "event_id",
        "asset_id",
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
    tool_metrics = context.get("metrics")
    if isinstance(tool_metrics, dict) and tool_metrics:
        nested_kpis = tool_metrics.get("kpi_summary")
        if isinstance(nested_kpis, dict):
            return {**nested_kpis, **{key: value for key, value in tool_metrics.items() if key != "kpi_summary"}}
        return tool_metrics
    metric_candidates = {
        "uiti": ["UITI", "uiti_total", "severity_uiti"],
        "uiti_vano": ["UITI_VANO", "uiti_vano_total", "severity_uiti_vano"],
        "duration_raw": ["DURATION_RAW", "duration_raw", "duration_raw_total", "duracion_h", "duration_hours", "duration_total_h"],
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
    if selected_context.get("tool_name"):
        package["structured_context_tool"] = {
            "tool_name": selected_context.get("tool_name"),
            "source_function": selected_context.get("source_function"),
            "source_view": selected_context.get("source_view"),
            "context_id": selected_context.get("context_id"),
            "context_hash": selected_context.get("context_hash"),
            "parameters": selected_context.get("parameters") or {},
            "summary": selected_context.get("summary") or {},
            "records": (selected_context.get("records") or [])[:MAX_CONTEXT_TOOL_RECORDS],
            "metrics": selected_context.get("metrics") or {},
            "traceability": selected_context.get("traceability") or {},
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
        "impacto UITI, usuarios, duración fuente, ubicación, causas y variables ambientales cuando están presentes."
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
