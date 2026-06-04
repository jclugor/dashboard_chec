from __future__ import annotations

from typing import Any


def citation_payload(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


_citation_payload = citation_payload
