from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROMPT_NAME = "time_series_interpretability"
PROMPT_VERSION = "1"


def prompt_path() -> Path:
    return Path(__file__).resolve().parents[2] / "agent_prompts" / "time_series_interpretability.v1.md"


def load_timeseries_prompt_template() -> str:
    return prompt_path().read_text(encoding="utf-8")


def prompt_hash(template: str) -> str:
    return hashlib.sha256(template.encode("utf-8")).hexdigest()[:16]


def format_chunks_for_prompt(chunks: list[dict[str, Any]]) -> str:
    snippets: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        title = chunk.get("document_title") or chunk.get("title") or "Documento tecnico"
        source = chunk.get("source_path") or chunk.get("source_uri") or "fuente no especificada"
        page = chunk.get("page")
        page_text = f", pagina {page}" if page not in (None, "") else ""
        text = str(chunk.get("snippet") or chunk.get("text") or "").strip()
        if not text:
            continue
        snippets.append(f"[{index}] {title} ({source}{page_text})\n{text[:1200]}")
    return "\n\n".join(snippets)


def render_timeseries_prompt(
    *,
    context_package: dict[str, Any],
    docs_text: str,
    question_text: str,
) -> tuple[str, dict[str, str]]:
    template = load_timeseries_prompt_template()
    values = {
        "context_json": json.dumps(context_package, ensure_ascii=False, indent=2, default=str),
        "docs_text": docs_text or "Sin documentos recuperados.",
        "question_text": question_text,
    }
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    metadata = {
        "prompt_name": PROMPT_NAME,
        "prompt_version": PROMPT_VERSION,
        "prompt_hash": prompt_hash(template),
    }
    return rendered, metadata
