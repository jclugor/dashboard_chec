from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any
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
    char_budget = settings.chatbot_max_context_chars
    used_chars = 0
    for score, chunk in scored[: effective_top_k * 3]:
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
        if len(results) >= effective_top_k:
            break
    return results


def _effective_top_k(settings: Settings, skill_resolution: Any | None) -> int:
    default_top_k = max(int(settings.chatbot_retrieval_top_k), 1)
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
