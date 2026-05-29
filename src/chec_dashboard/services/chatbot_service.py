from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from typing import Any
from urllib.parse import quote

import httpx
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


@dataclass(frozen=True)
class Corpus:
    chunks: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    variables: list[dict[str, Any]]


_CORPUS_CACHE: dict[str, tuple[float, Corpus]] = {}
_DATABRICKS_TOKEN_CACHE: dict[str, Any] = {}


def _databricks_host() -> str | None:
    host = os.getenv("DATABRICKS_HOST", "").strip().rstrip("/")
    if not host:
        return None
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host


def _is_volume_path(path: Path) -> bool:
    return str(path).startswith("/Volumes/")


def _databricks_api_auth_headers() -> dict[str, str] | None:
    host = _databricks_host()
    client_id = os.getenv("DATABRICKS_CLIENT_ID")
    client_secret = os.getenv("DATABRICKS_CLIENT_SECRET")
    if not host or not client_id or not client_secret:
        return None

    now = time.time()
    cached_token = _DATABRICKS_TOKEN_CACHE.get("access_token")
    expires_at = float(_DATABRICKS_TOKEN_CACHE.get("expires_at") or 0)
    if cached_token and now < expires_at - 60:
        return {"Authorization": f"Bearer {cached_token}"}

    response = httpx.post(
        f"{host}/oidc/v1/token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials", "scope": "all-apis"},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    token = str(payload["access_token"])
    expires_in = int(payload.get("expires_in") or 3600)
    _DATABRICKS_TOKEN_CACHE.update({"access_token": token, "expires_at": now + expires_in})
    return {"Authorization": f"Bearer {token}"}


def _databricks_files_url(kind: str, path: Path) -> str | None:
    host = _databricks_host()
    if not host:
        return None
    encoded_path = quote(str(path), safe="/")
    return f"{host}/api/2.0/fs/{kind}{encoded_path}"


def _read_databricks_file_text(path: Path) -> str | None:
    if not _is_volume_path(path):
        return None
    headers = _databricks_api_auth_headers()
    url = _databricks_files_url("files", path)
    if not headers or not url:
        return None

    response = httpx.get(url, headers=headers, timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text


def _databricks_file_exists(path: Path) -> bool | None:
    if not _is_volume_path(path):
        return None
    headers = _databricks_api_auth_headers()
    url = _databricks_files_url("files", path)
    if not headers or not url:
        return None

    response = httpx.head(url, headers=headers, timeout=15)
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return True


def _list_databricks_directory(path: Path) -> tuple[list[str], str | None] | None:
    if not _is_volume_path(path):
        return None
    headers = _databricks_api_auth_headers()
    url = _databricks_files_url("directories", path)
    if not headers or not url:
        return None

    response = httpx.get(url, headers=headers, timeout=15)
    if response.status_code == 404:
        return [], None
    response.raise_for_status()
    payload = response.json()
    raw_entries = payload.get("contents") or payload.get("files") or payload.get("objects") or []
    entries: list[str] = []
    for entry in raw_entries:
        if isinstance(entry, str):
            entries.append(Path(entry).name)
        elif isinstance(entry, dict):
            entry_path = entry.get("path") or entry.get("name") or ""
            entries.append(Path(str(entry_path)).name)
    return sorted(entry for entry in entries if entry), None


def _read_corpus_text(path: Path) -> str | None:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return _read_databricks_file_text(path)


def _normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = "".join(
        char
        for char in unicodedata.normalize("NFD", text.lower())
        if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9_./:-]+", " ", text).strip()


def _tokenize(value: Any) -> set[str]:
    return {
        token
        for token in _normalize_text(value).split()
        if len(token) >= 3 and token not in SPANISH_STOPWORDS
    }


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, float) and pd.isna(value):
        return None
    if pd.isna(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _row_context(row: pd.Series, *, kind: str, family: str | None = None) -> dict[str, Any]:
    context = {
        str(column): _json_safe(value)
        for column, value in row.items()
        if _json_safe(value) not in {None, ""}
    }
    context["kind"] = kind
    if family:
        context["family"] = family
    return context


def _context_id(kind: str, context: dict[str, Any]) -> str:
    payload = json.dumps(context, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
    return f"{kind}-{digest}"


def _sanitize_briefing_type(briefing_type: str | None) -> str:
    if briefing_type in BRIEFING_TYPES:
        return str(briefing_type)
    return "reliability"


def _guided_question_text(briefing_type: str, question_id: str | None) -> str | None:
    if not question_id:
        return None
    for question in GUIDED_QUESTIONS.get(briefing_type, []):
        if question["id"] == question_id:
            return question["question"]
    return None


def _resolve_question(briefing_type: str, question_id: str | None, question: str | None) -> str:
    guided_question = _guided_question_text(briefing_type, question_id)
    parts = [guided_question] if guided_question else []
    cleaned_question = (question or "").strip()
    if cleaned_question:
        parts.append(cleaned_question)
    if parts:
        return "\n".join(parts)
    fallback = GUIDED_QUESTIONS.get(briefing_type, GUIDED_QUESTIONS["reliability"])[0]
    return fallback["question"]


def _first_existing_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def _numeric_series(frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
    column = _first_existing_column(frame, candidates)
    if column is None or frame.empty:
        return pd.Series([0.0] * len(frame), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce").fillna(0.0)


def _series_total(frame: pd.DataFrame, candidates: list[str]) -> float:
    if frame.empty:
        return 0.0
    return float(_numeric_series(frame, candidates).sum())


def _rounded(value: float | int | None, digits: int = 4) -> float:
    try:
        return round(float(value or 0.0), digits)
    except (TypeError, ValueError):
        return 0.0


def _date_bounds(frame: pd.DataFrame, candidates: list[str]) -> dict[str, str | None]:
    column = _first_existing_column(frame, candidates)
    if column is None or frame.empty:
        return {"start": None, "end": None}
    dates = pd.to_datetime(frame[column], errors="coerce").dropna()
    if dates.empty:
        return {"start": None, "end": None}
    return {
        "start": dates.min().isoformat(),
        "end": dates.max().isoformat(),
    }


def _top_records_from_frame(
    frame: pd.DataFrame,
    group_candidates: list[str],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    group_column = _first_existing_column(frame, group_candidates)
    if group_column is None or frame.empty:
        return []
    work = pd.DataFrame(
        {
            "group": frame[group_column].fillna("Sin dato").astype(str).str.strip(),
            "saidi": _numeric_series(frame, ["severity_saidi", "SAIDI", "saidi_total"]),
            "saifi": _numeric_series(frame, ["severity_saifi", "SAIFI", "saifi_total"]),
            "duration_h": _numeric_series(frame, ["duration_hours", "duracion_h", "duration_total_h"]),
            "users_affected": _numeric_series(frame, ["cnt_usus", "users_affected_total"]),
            "event_count": _numeric_series(frame, ["event_count"]),
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
            "saidi": _rounded(row["saidi"]),
            "saifi": _rounded(row["saifi"]),
            "duration_h": _rounded(row["duration_h"], 2),
            "users_affected": int(row["users_affected"]),
        }
        for _, row in grouped.iterrows()
    ]


def _weather_columns(context: dict[str, Any] | pd.DataFrame, metric: str) -> list[str]:
    if isinstance(context, pd.DataFrame):
        columns = context.columns
    else:
        columns = context.keys()
    suffix = f"-{metric}"
    return [str(column) for column in columns if str(column).endswith(suffix)]


def _external_signals_from_frame(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}

    def metric_summary(metric: str, reducer: str) -> float | None:
        columns = _weather_columns(frame, metric)
        if not columns:
            return None
        values = pd.to_numeric(frame[columns].stack(), errors="coerce").dropna()
        if values.empty:
            return None
        if reducer == "sum":
            return _rounded(float(values.sum()), 2)
        if reducer == "mean":
            return _rounded(float(values.mean()), 2)
        return _rounded(float(values.max()), 2)

    signals = {
        "precip_total_mm": metric_summary("precip", "sum"),
        "precip_max_mm_h": metric_summary("precip", "max"),
        "wind_gust_max": metric_summary("wind_gust_spd", "max"),
        "wind_speed_max": metric_summary("wind_spd", "max"),
        "humidity_avg": metric_summary("rh", "mean"),
        "temperature_avg_c": metric_summary("temp", "mean"),
    }
    return {key: value for key, value in signals.items() if value is not None}


def _external_signals_from_context(context: dict[str, Any]) -> dict[str, Any]:
    if not context:
        return {}
    frame = pd.DataFrame([context])
    return _external_signals_from_frame(frame)


def _selected_circuits_payload(selected_circuits: list[str] | None) -> list[str] | None:
    if selected_circuits is None:
        return None
    return [str(circuit) for circuit in selected_circuits if str(circuit).strip()]


def _view_context_from_events(
    frame: pd.DataFrame,
    *,
    selected_period: str,
    selected_municipio: str,
    selected_circuits: list[str] | None,
) -> dict[str, Any]:
    selected_circuits = _selected_circuits_payload(selected_circuits)
    saidi_total = _series_total(frame, ["severity_saidi", "SAIDI", "saidi_total"])
    saifi_total = _series_total(frame, ["severity_saifi", "SAIFI", "saifi_total"])
    event_count = int(_series_total(frame, ["event_count"])) if "event_count" in frame.columns else int(len(frame))
    duration_total_h = _series_total(frame, ["duration_hours", "duracion_h", "duration_total_h"])
    users_affected = _series_total(frame, ["cnt_usus", "users_affected_total"])
    return {
        "kind": "view",
        "selected_period": selected_period,
        "selected_municipio": selected_municipio,
        "selected_circuits": selected_circuits,
        "scope_label": "todos los circuitos" if selected_circuits is None else ", ".join(selected_circuits) or "sin circuitos",
        "date_bounds": _date_bounds(frame, ["fecha_dia", "inicio_ts", "inicio", "map_date"]),
        "kpi_summary": {
            "event_count": event_count,
            "saidi_total": _rounded(saidi_total),
            "saifi_total": _rounded(saifi_total),
            "duration_total_h": _rounded(duration_total_h, 2),
            "users_affected_total": int(users_affected),
        },
        "top_circuits": _top_records_from_frame(frame, ["circuito", "cto_equi_ope", "FPARENT"]),
        "top_event_families": _top_records_from_frame(frame, ["event_family", "tipo_equi_ope"]),
        "top_causes": _top_records_from_frame(frame, ["causa"]),
        "external_signals": _external_signals_from_frame(frame),
    }


def _view_item_from_context(context: dict[str, Any]) -> dict[str, Any]:
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
        "id": _context_id("view", context),
        "label": f"Vista filtrada | {municipio} | {selected_period} | {scope}"[:180],
        "kind": "view",
        "summary": summary,
        "context": context,
    }


def load_chatbot_corpus(settings: Settings) -> Corpus:
    corpus_dir = settings.chatbot_corpus_dir
    chunks_path = corpus_dir / "chunks.jsonl"
    manifest_path = corpus_dir / "documents_manifest.json"
    variables_path = corpus_dir / "variables_manifest.json"

    chunks_text = _read_corpus_text(chunks_path)
    if not chunks_text:
        return Corpus(chunks=[], documents=[], variables=[])

    cache_key = str(chunks_path)
    if chunks_path.exists():
        mtime = chunks_path.stat().st_mtime
        cached = _CORPUS_CACHE.get(cache_key)
        if cached and cached[0] == mtime:
            return cached[1]
    else:
        mtime = 0.0

    chunks: list[dict[str, Any]] = []
    for line in chunks_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            chunk = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(chunk.get("text", "")).strip():
            chunks.append(chunk)

    documents: list[dict[str, Any]] = []
    manifest_text = _read_corpus_text(manifest_path)
    if manifest_text:
        try:
            documents = json.loads(manifest_text).get("documents", [])
        except (json.JSONDecodeError, AttributeError):
            documents = []

    variables: list[dict[str, Any]] = []
    variables_text = _read_corpus_text(variables_path)
    if variables_text:
        try:
            variables = json.loads(variables_text).get("variables", [])
        except (json.JSONDecodeError, AttributeError):
            variables = []

    corpus = Corpus(chunks=chunks, documents=documents, variables=variables)
    _CORPUS_CACHE[cache_key] = (mtime, corpus)
    return corpus


def _corpus_runtime_diagnostics(settings: Settings) -> dict[str, Any]:
    corpus_dir = settings.chatbot_corpus_dir
    chunks_path = corpus_dir / "chunks.jsonl"
    api_chunks_exists: bool | None = None
    api_entries: list[str] | None = None
    api_error: str | None = None
    if not chunks_path.exists():
        try:
            api_chunks_exists = _databricks_file_exists(chunks_path)
        except Exception as exc:
            api_error = str(exc)
    if not corpus_dir.exists():
        try:
            listed = _list_databricks_directory(corpus_dir)
            if listed is not None:
                api_entries, api_error = listed
        except Exception as exc:
            api_error = str(exc)

    diagnostics: dict[str, Any] = {
        "corpus_dir": str(corpus_dir),
        "chunks_path": str(chunks_path),
        "corpus_dir_exists": corpus_dir.exists() or api_entries is not None,
        "chunks_path_exists": chunks_path.exists() or bool(api_chunks_exists),
        "files_api_available": api_chunks_exists is not None or api_entries is not None,
    }
    try:
        diagnostics["corpus_dir_entries"] = sorted(path.name for path in corpus_dir.iterdir())[:20]
    except OSError as exc:
        diagnostics["corpus_dir_entries"] = (api_entries or [])[:20]
        diagnostics["corpus_dir_error"] = str(exc)
    if api_error:
        diagnostics["files_api_error"] = api_error
    return diagnostics


def get_chatbot_status(settings: Settings) -> dict[str, Any]:
    corpus_error = None
    try:
        corpus = load_chatbot_corpus(settings)
    except Exception as exc:
        corpus = Corpus(chunks=[], documents=[], variables=[])
        corpus_error = str(exc)
    diagnostics = _corpus_runtime_diagnostics(settings)
    enabled = settings.chatbot_enabled
    gemini_configured = bool(settings.gemini_api_key)
    corpus_available = bool(corpus.chunks)
    ready = enabled and gemini_configured and corpus_available

    if not enabled:
        message = "El asistente técnico está deshabilitado en esta instalación."
    elif not corpus_available:
        message = "El corpus técnico no está disponible. Carga los documentos antes de analizar."
    elif not gemini_configured:
        message = "Gemini no está configurado. La pestaña puede mostrar contexto, pero no generar análisis."
    else:
        message = "Asistente técnico listo para generar análisis."

    return {
        "enabled": enabled,
        "gemini_configured": gemini_configured,
        "corpus_available": corpus_available,
        "ready": ready,
        "documents_count": len(corpus.documents),
        "chunks_count": len(corpus.chunks),
        "message": message,
        **diagnostics,
    }
    if corpus_error:
        payload["corpus_load_error"] = corpus_error
    return payload


def _context_search_matches(context: dict[str, Any], search: str | None) -> bool:
    if not search:
        return True
    search_tokens = _tokenize(search)
    if not search_tokens:
        return True
    haystack = _tokenize(" ".join(str(value) for value in context.values()))
    return bool(search_tokens & haystack)


def _event_items_from_frame(frame: pd.DataFrame, *, search: str | None, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for _, row in frame.head(max(limit * 3, limit)).iterrows():
        context = _row_context(row, kind="event")
        if not _context_search_matches(context, search):
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
                "id": _context_id("event", context),
                "label": label[:180],
                "kind": "event",
                "summary": summary,
                "context": context,
            }
        )
        if len(items) >= limit:
            break
    return items


def _asset_items_from_filtered(
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
            context = _row_context(row, kind="asset", family=family)
            if not _context_search_matches(context, search):
                continue
            code = context.get("CODE") or context.get("display_label") or family
            circuito = context.get("FPARENT") or context.get("circuito") or "Sin circuito"
            municipio = context.get("MUN") or context.get("municipio") or "Sin municipio"
            label = f"{family} {code} | {circuito} | {municipio}"
            summary = f"{family} asociado al circuito {circuito} en {municipio}."
            items.append(
                {
                    "id": _context_id("asset", context),
                    "label": label[:180],
                    "kind": "asset",
                    "summary": summary,
                    "context": context,
                }
            )
            if len(items) >= limit:
                return items
    return items


def _selected_circuits_where(selected_circuits: list[str] | None) -> str:
    if selected_circuits is None:
        return ""
    if not selected_circuits:
        return " AND 1 = 0"
    if len(selected_circuits) == 1:
        return f" AND circuito = {sql_literal(selected_circuits[0])}"
    literals = ", ".join(sql_literal(circuit) for circuit in selected_circuits)
    return f" AND circuito IN ({literals})"


def _databricks_view_items(
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
        f"{_selected_circuits_where(selected_circuits)}"
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

    context = _view_context_from_events(
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
              {_selected_circuits_where(selected_circuits)}
            LIMIT 5000
            """
        )
    except Exception:
        events_frame = pd.DataFrame()

    if not events_frame.empty:
        context["top_causes"] = _top_records_from_frame(events_frame, ["causa"])
        context["external_signals"] = _external_signals_from_frame(events_frame)

    return [_view_item_from_context(context)]


def _databricks_context_options(
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
        f"{_selected_circuits_where(selected_circuits)}"
    )
    if context_kind == "view":
        return _databricks_view_items(
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
        return _event_items_from_frame(frame, search=search, limit=limit)

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
    filtered = FilteredMapDataset(
        trafos=points[points.get("asset_family", "") == "Transformers"].copy() if not points.empty else points,
        apoyos=points[points.get("asset_family", "") == "Supports"].copy() if not points.empty else points,
        switches=points[points.get("asset_family", "") == "Switches"].copy() if not points.empty else points,
        redmt=lines,
        events_by_day=[],
    )
    return _asset_items_from_filtered(filtered, search=search, limit=limit)


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
        items = _databricks_context_options(
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
            context = _view_context_from_events(
                events,
                selected_period=selected_period,
                selected_municipio=selected_municipio,
                selected_circuits=selected_circuits,
            )
            items = [_view_item_from_context(context)]
        elif context_kind == "event":
            events = pd.concat(filtered.events_by_day, ignore_index=True) if filtered.events_by_day else pd.DataFrame()
            items = _event_items_from_frame(events, search=search, limit=safe_limit)
        else:
            items = _asset_items_from_filtered(filtered, search=search, limit=safe_limit)

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


def retrieve_chatbot_chunks(
    settings: Settings,
    *,
    selected_context: dict[str, Any],
    question: str | None,
) -> list[dict[str, Any]]:
    corpus = load_chatbot_corpus(settings)
    if not corpus.chunks:
        return []

    context_text = json.dumps(selected_context, ensure_ascii=False, default=str)
    query_tokens = _tokenize(f"{question or ''} {context_text}")
    if not query_tokens:
        query_tokens = _tokenize(context_text)

    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in corpus.chunks:
        chunk_text = str(chunk.get("text", ""))
        chunk_tokens = _tokenize(chunk_text)
        if not chunk_tokens:
            continue
        title_tokens = _tokenize(chunk.get("document_title") or chunk.get("title") or "")
        tag_tokens = _tokenize(" ".join(str(tag) for tag in chunk.get("tags", [])))
        score = float(len(query_tokens & chunk_tokens))
        score += 1.7 * len(query_tokens & title_tokens)
        score += 1.3 * len(query_tokens & tag_tokens)
        if score <= 0:
            continue
        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[dict[str, Any]] = []
    char_budget = settings.chatbot_max_context_chars
    used_chars = 0
    for score, chunk in scored[: settings.chatbot_retrieval_top_k * 3]:
        text = str(chunk.get("text", "")).strip()
        if not text:
            continue
        if used_chars >= char_budget:
            break
        snippet = text[: min(len(text), 900)]
        used_chars += len(snippet)
        citation = dict(chunk)
        citation["score"] = score
        citation["snippet"] = snippet
        results.append(citation)
        if len(results) >= settings.chatbot_retrieval_top_k:
            break
    return results


def _citation_payload(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        citations.append(
            {
                "id": str(chunk.get("chunk_id") or f"doc-{index}"),
                "title": str(chunk.get("document_title") or chunk.get("title") or "Documento técnico"),
                "source_path": chunk.get("source_path"),
                "page": chunk.get("page"),
                "snippet": str(chunk.get("snippet") or chunk.get("text") or "")[:900],
                "score": float(chunk.get("score") or 0.0),
            }
        )
    return citations


def _has_context_value(value: Any) -> bool:
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


def _context_identity(context: dict[str, Any]) -> dict[str, Any]:
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
        if not _has_context_value(value):
            continue
        identity[key] = value
    return identity


def _selected_context_metrics(context: dict[str, Any]) -> dict[str, Any]:
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
            if _has_context_value(value):
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
        selected_external_signals = _external_signals_from_context(selected_context)
    package: dict[str, Any] = {
        "tipo_analisis": briefing_type,
        "nombre_analisis": BRIEFING_LABELS.get(briefing_type, "Confiabilidad"),
        "question_id": question_id,
        "context_kind": context_kind,
        "selected_context": _context_identity(selected_context),
        "metrics": _selected_context_metrics(selected_context),
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


def _briefing_instruction(briefing_type: str) -> str:
    if briefing_type == "compliance":
        return (
            "Enfoca la respuesta en cumplimiento técnico/regulatorio. Usa una sección "
            "'Banderas de evidencia' con señales soportadas por datos y citas. No uses "
            "lenguaje de cumple/no cumple, aprobado/reprobado ni puntajes formales."
        )
    if briefing_type == "maintenance":
        return (
            "Enfoca la respuesta en priorización de mantenimiento: causa raíz probable, "
            "revisiones de campo, activos/circuitos a priorizar y acciones preventivas."
        )
    return (
        "Enfoca la respuesta en confiabilidad: SAIDI/SAIFI, recurrencia, concentración "
        "por circuito/municipio/causa y señales ambientales u operativas."
    )


def _build_prompt(
    *,
    context_package: dict[str, Any],
    question: str | None,
    briefing_type: str,
    chunks: list[dict[str, Any]],
) -> str:
    context_json = json.dumps(context_package, ensure_ascii=False, indent=2, default=str)
    snippets = []
    for index, chunk in enumerate(chunks, start=1):
        title = chunk.get("document_title") or chunk.get("title") or "Documento técnico"
        snippets.append(f"[{index}] {title}\n{chunk.get('snippet') or chunk.get('text')}")
    docs_text = "\n\n".join(snippets)
    return f"""
Eres un asistente técnico para CHEC. Responde siempre en español.

Objetivo:
Analiza el evento o elemento de red seleccionado con base en requisitos técnicos,
condiciones externas y valores de indicadores. Explica el estado observado, si
hay señales de cumplimiento o posible incumplimiento, qué condiciones pueden
explicar los valores, y qué revisiones de campo o datos recomendarías.

Tipo de análisis:
{BRIEFING_LABELS.get(briefing_type, "Confiabilidad")}

Instrucción específica:
{_briefing_instruction(briefing_type)}

Reglas:
- Usa únicamente el contexto seleccionado y los documentos recuperados.
- Si falta información, dilo claramente y sugiere qué dato falta.
- Cita los documentos usando referencias como [1], [2].
- No inventes requisitos que no estén soportados por los documentos.
- Sé conciso, orientado a las personas interesadas y accionable.
- No uses términos en inglés cuando exista una alternativa clara en español.

Paquete de contexto estructurado:
{context_json}

Pregunta guía y/o pregunta adicional del usuario:
{question or "Sin pregunta adicional."}

Documentos recuperados:
{docs_text or "No se recuperaron documentos."}
""".strip()


def _generate_gemini_answer(settings: Settings, prompt: str) -> str:
    try:
        from google import genai
    except ImportError as exc:  # pragma: no cover - depends on runtime installation
        raise RuntimeError("La dependencia google-genai no está instalada.") from exc

    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY no está configurada.")

    client = genai.Client(api_key=settings.gemini_api_key)
    response = client.models.generate_content(model=settings.gemini_model, contents=prompt)
    text = getattr(response, "text", None)
    if text:
        return str(text)
    candidates = getattr(response, "candidates", None)
    if candidates:
        return str(candidates[0])
    raise RuntimeError("Gemini no devolvió texto utilizable.")


def assess_chatbot_context(
    settings: Settings,
    *,
    selected_context: dict[str, Any],
    question: str | None,
    briefing_type: str = "reliability",
    question_id: str | None = None,
) -> dict[str, Any]:
    briefing_type = _sanitize_briefing_type(briefing_type)
    resolved_question = _resolve_question(briefing_type, question_id, question)
    status = get_chatbot_status(settings)
    if not selected_context:
        return {
            "answer": "Selecciona primero un evento o elemento de red para analizar.",
            "citations": [],
            "status_text": "Falta contexto seleccionado.",
            "ready": False,
            "briefing_type": briefing_type,
        }

    context_package = build_chatbot_context_package(
        selected_context=selected_context,
        briefing_type=briefing_type,
        question_id=question_id,
    )
    chunks = retrieve_chatbot_chunks(
        settings,
        selected_context=context_package,
        question=resolved_question,
    )
    citations = _citation_payload(chunks)

    if not status["enabled"]:
        return {
            "answer": (
                "El asistente técnico está deshabilitado. El contexto fue seleccionado, "
                "pero no se generó análisis. Activa CHATBOT_ENABLED para usar esta pestaña."
            ),
            "citations": citations,
            "status_text": status["message"],
            "ready": False,
            "briefing_type": briefing_type,
        }
    if not chunks:
        return {
            "answer": (
                "No se encontraron documentos técnicos relevantes en el corpus. "
                "Carga o reconstruye el corpus antes de solicitar el análisis."
            ),
            "citations": [],
            "status_text": "Corpus técnico sin resultados para este contexto.",
            "ready": False,
            "briefing_type": briefing_type,
        }
    if not status["gemini_configured"]:
        return {
            "answer": (
                "Gemini no está configurado todavía. Ya se recuperó contexto técnico, "
                "pero falta configurar GEMINI_API_KEY para generar el análisis."
            ),
            "citations": citations,
            "status_text": status["message"],
            "ready": False,
            "briefing_type": briefing_type,
        }

    prompt = _build_prompt(
        context_package=context_package,
        question=resolved_question,
        briefing_type=briefing_type,
        chunks=chunks,
    )
    try:
        answer = _generate_gemini_answer(settings, prompt)
    except Exception as exc:
        return {
            "answer": f"No fue posible generar el análisis con Gemini: {exc}",
            "citations": citations,
            "status_text": "Error al consultar Gemini.",
            "ready": False,
            "briefing_type": briefing_type,
        }

    return {
        "answer": answer,
        "citations": citations,
        "status_text": "Análisis generado con documentos técnicos recuperados.",
        "ready": True,
        "briefing_type": briefing_type,
    }
