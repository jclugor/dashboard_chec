from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any, Callable
from urllib.parse import quote

import httpx

from chec_dashboard.core.config import Settings
from chec_dashboard.services.agent_context_service import tokenize_text


@dataclass(frozen=True)
class Corpus:
    chunks: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    variables: list[dict[str, Any]]


_CORPUS_CACHE: dict[str, tuple[float, Corpus]] = {}
_DATABRICKS_TOKEN_CACHE: dict[str, Any] = {}

SUPPORTED_RETRIEVER_BACKENDS = {"local_jsonl", "databricks_ai_search"}
AI_SEARCH_COLUMNS = [
    "chunk_id",
    "document_id",
    "document_title",
    "document_type",
    "source_path",
    "source_uri",
    "page",
    "section_title",
    "section_number",
    "effective_date",
    "version",
    "jurisdiction",
    "topic_tags",
    "analysis_tags",
    "authority_level",
    "text",
    "text_hash",
]


def databricks_host() -> str | None:
    host = os.getenv("DATABRICKS_HOST", "").strip().rstrip("/")
    if not host:
        return None
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host


def is_volume_path(path: Path) -> bool:
    return str(path).startswith("/Volumes/")


def databricks_api_auth_headers() -> dict[str, str] | None:
    host = databricks_host()
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


def databricks_files_url(kind: str, path: Path) -> str | None:
    host = databricks_host()
    if not host:
        return None
    encoded_path = quote(str(path), safe="/")
    return f"{host}/api/2.0/fs/{kind}{encoded_path}"


def read_databricks_file_text(path: Path) -> str | None:
    if not is_volume_path(path):
        return None
    headers = databricks_api_auth_headers()
    url = databricks_files_url("files", path)
    if not headers or not url:
        return None

    response = httpx.get(url, headers=headers, timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.text


def databricks_file_exists(path: Path) -> bool | None:
    if not is_volume_path(path):
        return None
    headers = databricks_api_auth_headers()
    url = databricks_files_url("files", path)
    if not headers or not url:
        return None

    response = httpx.head(url, headers=headers, timeout=15)
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return True


def list_databricks_directory(path: Path) -> tuple[list[str], str | None] | None:
    if not is_volume_path(path):
        return None
    headers = databricks_api_auth_headers()
    url = databricks_files_url("directories", path)
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


def read_corpus_text(path: Path) -> str | None:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return read_databricks_file_text(path)


def retriever_backend(settings: Settings) -> str:
    backend = (settings.retriever_backend or "local_jsonl").strip().lower()
    if backend in SUPPORTED_RETRIEVER_BACKENDS:
        return backend
    return backend


def ai_search_configured(settings: Settings) -> bool:
    return bool((settings.ai_search_index_name or "").strip())


def retriever_runtime_diagnostics(settings: Settings) -> dict[str, Any]:
    backend = retriever_backend(settings)
    payload: dict[str, Any] = {
        "retriever_backend": backend,
        "retriever_supported": backend in SUPPORTED_RETRIEVER_BACKENDS,
        "ai_search_endpoint_name": settings.ai_search_endpoint_name,
        "ai_search_index_name": settings.ai_search_index_name,
        "ai_search_top_k": settings.ai_search_top_k,
        "ai_search_query_type": settings.ai_search_query_type,
        "ai_search_embedding_endpoint_name": settings.ai_search_embedding_endpoint_name,
        "ai_search_endpoint_type": settings.ai_search_endpoint_type,
        "ai_search_configured": ai_search_configured(settings),
    }
    if backend == "databricks_ai_search":
        payload["retriever_configured"] = bool(payload["retriever_supported"] and payload["ai_search_configured"])
    else:
        payload["retriever_configured"] = payload["retriever_supported"]
    return payload


def load_chatbot_corpus(settings: Settings) -> Corpus:
    corpus_dir = settings.chatbot_corpus_dir
    chunks_path = corpus_dir / "chunks.jsonl"
    manifest_path = corpus_dir / "documents_manifest.json"
    variables_path = corpus_dir / "variables_manifest.json"

    chunks_text = read_corpus_text(chunks_path)
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
    manifest_text = read_corpus_text(manifest_path)
    if manifest_text:
        try:
            documents = json.loads(manifest_text).get("documents", [])
        except (json.JSONDecodeError, AttributeError):
            documents = []

    variables: list[dict[str, Any]] = []
    variables_text = read_corpus_text(variables_path)
    if variables_text:
        try:
            variables = json.loads(variables_text).get("variables", [])
        except (json.JSONDecodeError, AttributeError):
            variables = []

    corpus = Corpus(chunks=chunks, documents=documents, variables=variables)
    _CORPUS_CACHE[cache_key] = (mtime, corpus)
    return corpus


def corpus_runtime_diagnostics(settings: Settings) -> dict[str, Any]:
    corpus_dir = settings.chatbot_corpus_dir
    chunks_path = corpus_dir / "chunks.jsonl"
    api_chunks_exists: bool | None = None
    api_entries: list[str] | None = None
    api_error: str | None = None
    if not chunks_path.exists():
        try:
            api_chunks_exists = databricks_file_exists(chunks_path)
        except Exception as exc:
            api_error = str(exc)
    if not corpus_dir.exists():
        try:
            listed = list_databricks_directory(corpus_dir)
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


def retrieve_chatbot_chunks(
    settings: Settings,
    *,
    selected_context: dict[str, Any],
    question: str | None,
    skill_resolution: Any | None = None,
) -> list[dict[str, Any]]:
    if retriever_backend(settings) == "databricks_ai_search":
        return DatabricksAISearchRetriever(settings).retrieve(
            selected_context=selected_context,
            question=question,
            skill_resolution=skill_resolution,
        )
    return retrieve_local_jsonl_chunks(
        settings,
        selected_context=selected_context,
        question=question,
        skill_resolution=skill_resolution,
    )


def retrieve_local_jsonl_chunks(
    settings: Settings,
    *,
    selected_context: dict[str, Any],
    question: str | None,
    skill_resolution: Any | None = None,
) -> list[dict[str, Any]]:
    corpus = load_chatbot_corpus(settings)
    if not corpus.chunks:
        return []

    context_text = json.dumps(selected_context, ensure_ascii=False, default=str)
    query_tokens = tokenize_text(f"{question or ''} {context_text}")
    if not query_tokens:
        query_tokens = tokenize_text(context_text)
    effective_top_k = _effective_top_k(settings, skill_resolution)
    boost_tags = _skill_boost_tags(skill_resolution)

    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in corpus.chunks:
        chunk_text = str(chunk.get("text", ""))
        chunk_tokens = tokenize_text(chunk_text)
        if not chunk_tokens:
            continue
        title_tokens = tokenize_text(chunk.get("document_title") or chunk.get("title") or "")
        tag_tokens = tokenize_text(" ".join(str(tag) for tag in chunk.get("tags", [])))
        score = float(len(query_tokens & chunk_tokens))
        score += 1.7 * len(query_tokens & title_tokens)
        score += 1.3 * len(query_tokens & tag_tokens)
        score += 2.0 * len(boost_tags & tag_tokens)
        if score <= 0:
            continue
        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    results: list[dict[str, Any]] = []
    used_chars = 0
    for score, chunk in scored[: effective_top_k * 3]:
        text = str(chunk.get("text", "")).strip()
        if not text:
            continue
        if used_chars >= settings.chatbot_max_context_chars:
            break
        snippet = text[: min(len(text), 900)]
        used_chars += len(snippet)
        citation = dict(chunk)
        citation["score"] = score
        citation["snippet"] = snippet
        results.append(citation)
        if len(results) >= effective_top_k:
            break
    return results


class DatabricksAISearchRetriever:
    def __init__(
        self,
        settings: Settings,
        *,
        workspace_client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.settings = settings
        self._workspace_client_factory = workspace_client_factory

    def retrieve(
        self,
        *,
        selected_context: dict[str, Any],
        question: str | None,
        skill_resolution: Any | None = None,
    ) -> list[dict[str, Any]]:
        if not ai_search_configured(self.settings):
            return []
        effective_top_k = _effective_top_k(
            self.settings,
            skill_resolution,
            default_top_k=self.settings.ai_search_top_k,
        )
        query_top_k = max(effective_top_k, int(self.settings.ai_search_top_k))
        query_text = _ai_search_query_text(selected_context=selected_context, question=question)
        if not query_text:
            return []

        response = self._query_index(query_text=query_text, num_results=query_top_k)
        parsed_chunks = _parse_ai_search_response(response)
        return _bounded_chunks(
            parsed_chunks,
            limit=effective_top_k,
            char_budget=self.settings.chatbot_max_context_chars,
        )

    def _query_index(self, *, query_text: str, num_results: int) -> Any:
        client = self._workspace_client()
        return client.vector_search_indexes.query_index(
            index_name=str(self.settings.ai_search_index_name),
            columns=AI_SEARCH_COLUMNS,
            num_results=int(num_results),
            query_text=query_text,
            query_type=self.settings.ai_search_query_type,
        )

    def _workspace_client(self) -> Any:
        if self._workspace_client_factory is not None:
            return self._workspace_client_factory()
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient()


def _ai_search_query_text(*, selected_context: dict[str, Any], question: str | None) -> str:
    context_bits = []
    if question:
        context_bits.append(str(question))
    for key in (
        "document_title",
        "tool_name",
        "source_view",
        "summary",
        "nombre_analisis",
        "causa",
        "tipo_elemento",
        "equipo_ope",
        "CODE",
        "FPARENT",
        "circuito",
        "selected_context",
        "structured_context_tool",
        "metrics",
    ):
        value = selected_context.get(key)
        if value:
            context_bits.append(json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value))
    return " ".join(" ".join(context_bits).split())[:4000]


def _bounded_chunks(
    chunks: list[dict[str, Any]],
    *,
    limit: int,
    char_budget: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    used_chars = 0
    for chunk in chunks:
        text = str(chunk.get("text", "")).strip()
        if not text:
            continue
        if used_chars >= char_budget:
            break
        snippet = str(chunk.get("snippet") or text[: min(len(text), 900)]).strip()
        used_chars += len(snippet)
        citation = dict(chunk)
        citation["snippet"] = snippet
        results.append(citation)
        if len(results) >= limit:
            break
    return results


def _parse_ai_search_response(response: Any) -> list[dict[str, Any]]:
    column_names = _ai_search_column_names(response)
    rows = _ai_search_rows(response)
    chunks: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows, start=1):
        row_values = list(row) if isinstance(row, (list, tuple)) else []
        mapped = {
            str(column_name): row_values[index]
            for index, column_name in enumerate(column_names)
            if index < len(row_values)
        }
        text = str(mapped.get("text") or "").strip()
        if not text:
            continue
        score = mapped.get("score") or mapped.get("_score") or mapped.get("similarity_score")
        chunk = {
            "chunk_id": mapped.get("chunk_id") or f"ai-search-{row_index}",
            "document_id": mapped.get("document_id"),
            "document_title": mapped.get("document_title") or mapped.get("title"),
            "document_type": mapped.get("document_type"),
            "source_path": mapped.get("source_path"),
            "source_uri": mapped.get("source_uri"),
            "page": mapped.get("page"),
            "section_title": mapped.get("section_title"),
            "section_number": mapped.get("section_number"),
            "effective_date": mapped.get("effective_date"),
            "version": mapped.get("version"),
            "jurisdiction": mapped.get("jurisdiction"),
            "topic_tags": mapped.get("topic_tags") or [],
            "analysis_tags": mapped.get("analysis_tags") or [],
            "authority_level": mapped.get("authority_level"),
            "text": text,
            "text_hash": mapped.get("text_hash"),
            "score": _score_value(score, row_index),
        }
        chunks.append({key: value for key, value in chunk.items() if value not in (None, "")})
    return chunks


def _score_value(value: Any, row_index: int) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0 / max(row_index, 1)


def _ai_search_column_names(response: Any) -> list[str]:
    manifest = _field(response, "manifest", {})
    columns = _field(manifest, "columns", []) or []
    names: list[str] = []
    for column in columns:
        name = _field(column, "name")
        if name:
            names.append(str(name))
    return names


def _ai_search_rows(response: Any) -> list[Any]:
    result = _field(response, "result", {})
    rows = _field(result, "data_array", []) or []
    return list(rows)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    if hasattr(value, "as_dict"):
        try:
            return value.as_dict().get(name, default)
        except Exception:
            pass
    return getattr(value, name, default)


def _effective_top_k(settings: Settings, skill_resolution: Any | None, *, default_top_k: int | None = None) -> int:
    default_top_k = max(int(default_top_k or settings.chatbot_retrieval_top_k), 1)
    if skill_resolution is None:
        return default_top_k
    skill = getattr(skill_resolution, "skill", None)
    retrieval_policy = getattr(skill_resolution, "retrieval_policy", None)
    skill_top_k = getattr(skill, "retrieval_top_k", None) or default_top_k
    policy_max_top_k = getattr(retrieval_policy, "retrieval_max_top_k", None) or max(default_top_k, skill_top_k)
    return max(1, min(int(skill_top_k), int(policy_max_top_k)))


def _skill_boost_tags(skill_resolution: Any | None) -> set[str]:
    if skill_resolution is None:
        return set()
    skill = getattr(skill_resolution, "skill", None)
    raw_tags = getattr(skill, "retrieval_boost_tags", ()) or ()
    return tokenize_text(" ".join(str(tag) for tag in raw_tags))


_databricks_host = databricks_host
_is_volume_path = is_volume_path
_databricks_api_auth_headers = databricks_api_auth_headers
_databricks_files_url = databricks_files_url
_read_databricks_file_text = read_databricks_file_text
_databricks_file_exists = databricks_file_exists
_list_databricks_directory = list_databricks_directory
_read_corpus_text = read_corpus_text
_corpus_runtime_diagnostics = corpus_runtime_diagnostics
