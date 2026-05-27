#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

import pandas as pd
from pypdf import PdfReader


DEFAULT_EXCLUDE_PATTERNS = (
    "borrar",
    "becarios",
    "convocatoria",
    "__pycache__",
)


def _slug(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "documento"


def _hash_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _should_exclude(path: Path, patterns: Iterable[str]) -> bool:
    name = path.name.lower()
    return any(pattern.lower() in name for pattern in patterns)


def _split_text(text: str, *, chunk_words: int, overlap_words: int) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    words = cleaned.split()
    if len(words) <= chunk_words:
        return [cleaned]

    chunks: list[str] = []
    step = max(chunk_words - overlap_words, 1)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_words])
        if chunk:
            chunks.append(chunk)
        if start + chunk_words >= len(words):
            break
    return chunks


def _pdf_chunks(path: Path, *, chunk_words: int, overlap_words: int) -> tuple[list[dict], dict]:
    reader = PdfReader(str(path))
    document_id = f"pdf-{_slug(path.stem)}-{_hash_text(str(path))}"
    chunks: list[dict] = []
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        for chunk_index, text in enumerate(
            _split_text(page_text, chunk_words=chunk_words, overlap_words=overlap_words),
            start=1,
        ):
            chunk_id = f"{document_id}-p{page_index}-{chunk_index}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "document_title": path.stem.replace("_", " "),
                    "source_path": str(path),
                    "source_type": "pdf",
                    "page": page_index,
                    "tags": [_slug(path.stem)],
                    "text": text,
                }
            )
    manifest = {
        "document_id": document_id,
        "title": path.stem.replace("_", " "),
        "source_path": str(path),
        "source_type": "pdf",
        "chunks": len(chunks),
    }
    return chunks, manifest


def _excel_chunks(path: Path) -> tuple[list[dict], dict, list[dict]]:
    document_id = f"xlsx-{_slug(path.stem)}-{_hash_text(str(path))}"
    chunks: list[dict] = []
    variables: list[dict] = []
    try:
        sheets = pd.read_excel(path, sheet_name=None)
    except Exception:
        sheets = {}

    for sheet_name, frame in sheets.items():
        frame = frame.dropna(how="all")
        for row_index, row in frame.iterrows():
            parts = []
            row_payload = {}
            for column, value in row.items():
                if pd.isna(value):
                    continue
                column_text = str(column).strip()
                value_text = str(value).strip()
                if not column_text or not value_text:
                    continue
                parts.append(f"{column_text}: {value_text}")
                row_payload[column_text] = value_text
            if not parts:
                continue
            text = " | ".join(parts)
            variable_name = row_payload.get("Variables") or row_payload.get("Variable") or path.stem
            chunk_id = f"{document_id}-{_slug(str(sheet_name))}-{int(row_index)}"
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "document_title": path.stem.replace("_", " "),
                    "source_path": str(path),
                    "source_type": "xlsx",
                    "sheet": str(sheet_name),
                    "tags": [_slug(path.stem), _slug(str(variable_name))],
                    "text": text,
                }
            )
            variables.append(
                {
                    "source_path": str(path),
                    "sheet": str(sheet_name),
                    "variable": str(variable_name),
                    "metadata": row_payload,
                }
            )

    manifest = {
        "document_id": document_id,
        "title": path.stem.replace("_", " "),
        "source_path": str(path),
        "source_type": "xlsx",
        "chunks": len(chunks),
    }
    return chunks, manifest, variables


def build_corpus(
    *,
    source_dirs: list[Path],
    output_dir: Path,
    chunk_words: int,
    overlap_words: int,
    exclude_patterns: Iterable[str],
) -> dict[str, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[dict] = []
    documents: list[dict] = []
    variables: list[dict] = []

    candidate_files: list[Path] = []
    for source_dir in source_dirs:
        if not source_dir.exists():
            continue
        candidate_files.extend(sorted(source_dir.rglob("*.pdf")))
        candidate_files.extend(sorted(source_dir.rglob("*.xlsx")))

    seen: set[Path] = set()
    for path in candidate_files:
        resolved = path.resolve()
        if resolved in seen or _should_exclude(path, exclude_patterns):
            continue
        seen.add(resolved)
        if path.suffix.lower() == ".pdf":
            file_chunks, manifest = _pdf_chunks(path, chunk_words=chunk_words, overlap_words=overlap_words)
            chunks.extend(file_chunks)
            documents.append(manifest)
        elif path.suffix.lower() == ".xlsx":
            file_chunks, manifest, file_variables = _excel_chunks(path)
            chunks.extend(file_chunks)
            documents.append(manifest)
            variables.extend(file_variables)

    chunks_path = output_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    (output_dir / "documents_manifest.json").write_text(
        json.dumps({"documents": documents}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "variables_manifest.json").write_text(
        json.dumps({"variables": variables}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"documents": len(documents), "chunks": len(chunks), "variables": len(variables)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the CHEC chatbot lexical RAG corpus.")
    parser.add_argument(
        "--source-dir",
        action="append",
        dest="source_dirs",
        required=True,
        help="Directory containing source PDFs or Excel mapping files. Can be repeated.",
    )
    parser.add_argument("--output-dir", required=True, help="Directory where corpus artifacts will be written.")
    parser.add_argument("--chunk-words", type=int, default=700)
    parser.add_argument("--overlap-words", type=int, default=90)
    parser.add_argument(
        "--exclude-pattern",
        action="append",
        default=list(DEFAULT_EXCLUDE_PATTERNS),
        help="Case-insensitive filename substring to exclude. Can be repeated.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = build_corpus(
        source_dirs=[Path(value) for value in args.source_dirs],
        output_dir=Path(args.output_dir),
        chunk_words=max(args.chunk_words, 100),
        overlap_words=max(min(args.overlap_words, args.chunk_words - 1), 0),
        exclude_patterns=args.exclude_pattern,
    )
    print(
        "Built chatbot corpus: "
        f"{counts['documents']} documents, {counts['chunks']} chunks, {counts['variables']} variable rows."
    )


if __name__ == "__main__":
    main()
