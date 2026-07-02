from __future__ import annotations

import re
from typing import Any

from chec_dashboard.services.agent_context_service import normalize_text


_CITATION_RE = re.compile(r"\[(\d{1,3}|x|xx|citation|cita|pendiente)\]", re.IGNORECASE)
_NUMBERED_CITATION_RE = re.compile(r"\[(\d{1,3})\]")

NORMATIVE_TERMS = (
    "creg",
    "retie",
    "norma",
    "normativa",
    "regulatorio",
    "regulatoria",
    "requisito",
    "cumplimiento",
)
DOCUMENTARY_TERMS = (
    "documento",
    "bitacora",
    "bitácora",
    "registro",
    "mantenimiento",
    "evidencia documental",
)


def validate_output_citations(
    output_text: str,
    chunks: list[dict[str, Any]] | None = None,
    *,
    require_documentary_claim_citations: bool = True,
) -> dict[str, Any]:
    text = output_text or ""
    chunks = chunks or []
    placeholder_citations = sorted(
        {
            match.group(0)
            for match in _CITATION_RE.finditer(text)
            if not match.group(1).isdigit()
        }
    )
    used = sorted({int(match) for match in _NUMBERED_CITATION_RE.findall(text)})
    available = list(range(1, len(chunks) + 1))
    unknown = [number for number in used if number not in set(available)]
    uncited_normative = _uncited_claims(text, NORMATIVE_TERMS)
    uncited_documentary = _uncited_claims(text, DOCUMENTARY_TERMS) if require_documentary_claim_citations else []
    errors: list[str] = []
    if placeholder_citations:
        errors.append("placeholder_citations")
    if unknown:
        errors.append("citation_index_out_of_range")
    if uncited_normative:
        errors.append("uncited_normative_claim")
    if uncited_documentary:
        errors.append("uncited_documentary_claim")
    return {
        "valid": not errors,
        "used_citation_numbers": used,
        "available_citation_numbers": available,
        "unknown_citation_numbers": unknown,
        "placeholder_citations": placeholder_citations,
        "uncited_normative_claims": uncited_normative,
        "uncited_documentary_claims": uncited_documentary,
        "errors": errors,
        "warnings": _warnings(errors),
    }


def validate_citation_indexes(citation_indexes: list[int], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    available = set(range(1, len(chunks) + 1))
    invalid = [index for index in citation_indexes if index not in available]
    return {
        "valid": not invalid,
        "available_citation_numbers": sorted(available),
        "invalid_citation_numbers": invalid,
        "errors": ["citation_index_out_of_range"] if invalid else [],
        "warnings": _warnings(["citation_index_out_of_range"] if invalid else []),
    }


def _uncited_claims(text: str, terms: tuple[str, ...]) -> list[str]:
    claims: list[str] = []
    for sentence in _sentences(text):
        if _NUMBERED_CITATION_RE.search(sentence):
            continue
        normalized = normalize_text(sentence)
        if any(normalize_text(term) in normalized for term in terms):
            claims.append(sentence[:260])
        if len(claims) >= 5:
            break
    return claims


def _sentences(text: str) -> list[str]:
    rows: list[str] = []
    for line in (text or "").splitlines():
        compact = " ".join(line.split())
        if not compact or compact.lstrip().startswith("#"):
            continue
        rows.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+", compact) if part.strip())
    return rows


def _warnings(errors: list[str]) -> list[str]:
    messages = {
        "placeholder_citations": "La salida usa marcadores de cita de relleno.",
        "citation_index_out_of_range": "La salida referencia citas que no existen en los fragmentos recuperados.",
        "uncited_normative_claim": "Hay afirmaciones normativas o regulatorias sin cita.",
        "uncited_documentary_claim": "Hay afirmaciones documentales o de bitacora sin cita.",
    }
    return [messages[error] for error in errors if error in messages]
