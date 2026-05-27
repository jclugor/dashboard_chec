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
        if context_kind == "event":
            events = pd.concat(filtered.events_by_day, ignore_index=True) if filtered.events_by_day else pd.DataFrame()
            items = _event_items_from_frame(events, search=search, limit=safe_limit)
        else:
            items = _asset_items_from_filtered(filtered, search=search, limit=safe_limit)

    label = "eventos" if context_kind == "event" else "elementos de red"
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


def _build_prompt(
    *,
    selected_context: dict[str, Any],
    question: str | None,
    chunks: list[dict[str, Any]],
) -> str:
    context_json = json.dumps(selected_context, ensure_ascii=False, indent=2, default=str)
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

Reglas:
- Usa únicamente el contexto seleccionado y los documentos recuperados.
- Si falta información, dilo claramente y sugiere qué dato falta.
- Cita los documentos usando referencias como [1], [2].
- No inventes requisitos que no estén soportados por los documentos.

Contexto seleccionado:
{context_json}

Pregunta adicional del usuario:
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
) -> dict[str, Any]:
    status = get_chatbot_status(settings)
    if not selected_context:
        return {
            "answer": "Selecciona primero un evento o elemento de red para analizar.",
            "citations": [],
            "status_text": "Falta contexto seleccionado.",
            "ready": False,
        }

    chunks = retrieve_chatbot_chunks(settings, selected_context=selected_context, question=question)
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
        }

    prompt = _build_prompt(selected_context=selected_context, question=question, chunks=chunks)
    try:
        answer = _generate_gemini_answer(settings, prompt)
    except Exception as exc:
        return {
            "answer": f"No fue posible generar el análisis con Gemini: {exc}",
            "citations": citations,
            "status_text": "Error al consultar Gemini.",
            "ready": False,
        }

    return {
        "answer": answer,
        "citations": citations,
        "status_text": "Análisis generado con documentos técnicos recuperados.",
        "ready": True,
    }
