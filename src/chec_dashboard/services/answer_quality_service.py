from __future__ import annotations

import re
import unicodedata
from typing import Any


STRUCTURED_SECTION_KEYS: tuple[str, ...] = (
    "estado_observado",
    "banderas_evidencia",
    "requisitos_posiblemente_aplicables",
    "datos_faltantes",
    "riesgo_posible",
    "recomendaciones",
    "limitaciones",
    "citas_usadas",
    "preguntas_sugeridas",
)

STRUCTURED_SECTION_TITLES: dict[str, str] = {
    "estado_observado": "Estado observado",
    "banderas_evidencia": "Banderas de evidencia",
    "requisitos_posiblemente_aplicables": "Requisitos posiblemente aplicables",
    "datos_faltantes": "Datos faltantes",
    "riesgo_posible": "Riesgo posible",
    "recomendaciones": "Recomendaciones",
    "limitaciones": "Limitaciones",
    "citas_usadas": "Citas usadas",
    "preguntas_sugeridas": "Preguntas sugeridas",
}

DEFAULT_SECTION_ITEMS: dict[str, list[str]] = {
    "estado_observado": ["No se identificó una sección específica de estado observado."],
    "banderas_evidencia": ["Sin banderas de evidencia adicionales reportadas."],
    "requisitos_posiblemente_aplicables": [
        "Sin requisitos posiblemente aplicables adicionales identificados."
    ],
    "datos_faltantes": ["No se reportaron datos faltantes adicionales."],
    "riesgo_posible": ["Sin riesgo posible adicional identificado con la evidencia disponible."],
    "recomendaciones": ["Sin recomendaciones adicionales reportadas."],
    "limitaciones": ["La respuesta debe revisarse contra la evidencia disponible."],
    "citas_usadas": ["Sin citas documentales recuperadas."],
    "preguntas_sugeridas": ["Sin preguntas sugeridas adicionales."],
}

ALLOWED_COMPLIANCE_LANGUAGE: tuple[str, ...] = (
    "posible riesgo",
    "evidencia disponible",
    "bandera de evidencia",
    "dato faltante",
    "recomendación de verificación",
    "recomendacion de verificacion",
)

BLOCKED_COMPLIANCE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("incumplimiento confirmado", r"\bincumplimiento\s+confirmado\b"),
    ("no cumple", r"\bno\s+cumple\b"),
    ("cumple", r"(?<!no )\bcumple\b"),
    ("sanción aplicable", r"\bsancion\s+aplicable\b"),
    ("responsabilidad legal demostrada", r"\bresponsabilidad\s+legal\s+demostrada\b"),
)

REGULATORY_CLAIM_TERMS: tuple[str, ...] = (
    "creg",
    "retie",
    "regulatorio",
    "regulatoria",
    "regulacion",
    "regulación",
    "norma",
    "normativo",
    "normativa",
    "requisito",
    "cumplimiento",
    "incumplimiento",
    "calidad del servicio",
    "sancion",
    "sanción",
    "responsabilidad legal",
)

_CITATION_MARKER_RE = re.compile(r"\[(\d{1,3})\]")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]+|\d+[.)])\s*")
_HEADING_PREFIX_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_EMPHASIS_RE = re.compile(r"[*_`]+")


def build_answer_quality_metadata(
    answer: str,
    citations: list[dict[str, Any]] | None = None,
    briefing_type: str | None = None,
) -> dict[str, Any]:
    structured_answer, answer_validation = normalize_structured_answer(answer)
    return {
        "structured_answer": structured_answer,
        "answer_validation": answer_validation,
        "citation_validation": validate_citations(answer, citations or [], briefing_type=briefing_type),
        "compliance_validation": validate_compliance_language(answer, briefing_type=briefing_type),
    }


def empty_answer_quality_metadata() -> dict[str, Any]:
    return {
        "structured_answer": {key: list(DEFAULT_SECTION_ITEMS[key]) for key in STRUCTURED_SECTION_KEYS},
        "answer_validation": {
            "valid": True,
            "structured": False,
            "fallback_used": False,
            "missing_sections": [],
            "section_count": 0,
            "warnings": [],
        },
        "citation_validation": _citation_validation_payload(
            valid=True,
            used_citation_numbers=[],
            available_citation_numbers=[],
            unknown_citation_numbers=[],
            uncited_regulatory_claims=[],
            warnings=[],
        ),
        "compliance_validation": _compliance_validation_payload(
            valid=True,
            flagged_phrases=[],
            allowed_language_present=[],
            warnings=[],
        ),
    }


def normalize_structured_answer(answer: str) -> tuple[dict[str, list[str]], dict[str, Any]]:
    text = (answer or "").strip()
    if not text:
        return empty_answer_quality_metadata()["structured_answer"], {
            "valid": True,
            "structured": False,
            "fallback_used": False,
            "missing_sections": [],
            "section_count": 0,
            "warnings": [],
        }

    parsed: dict[str, list[str]] = {key: [] for key in STRUCTURED_SECTION_KEYS}
    found_sections: list[str] = []
    current_key: str | None = None

    for raw_line in text.splitlines():
        heading_key, inline_text = _section_heading(raw_line)
        if heading_key:
            current_key = heading_key
            if heading_key not in found_sections:
                found_sections.append(heading_key)
            if inline_text:
                parsed[heading_key].append(inline_text)
            continue
        if current_key:
            parsed[current_key].append(raw_line)

    fallback_used = not found_sections
    if fallback_used:
        parsed["estado_observado"] = [text]
        found_sections = ["estado_observado"]

    structured_answer: dict[str, list[str]] = {}
    missing_sections: list[str] = []
    for key in STRUCTURED_SECTION_KEYS:
        items = _content_items(parsed.get(key, []))
        if items:
            structured_answer[key] = items
        else:
            structured_answer[key] = list(DEFAULT_SECTION_ITEMS[key])
            missing_sections.append(key)

    warnings: list[str] = []
    if fallback_used:
        warnings.append("La respuesta no incluyó encabezados canónicos; se aplicó estructura segura.")
    if missing_sections:
        warnings.append("Se completaron secciones faltantes con valores seguros.")

    return structured_answer, {
        "valid": not fallback_used and not missing_sections,
        "structured": bool(found_sections) and not fallback_used,
        "fallback_used": fallback_used,
        "missing_sections": missing_sections,
        "section_count": len(found_sections),
        "warnings": warnings,
    }


def validate_citations(
    answer: str,
    citations: list[dict[str, Any]] | None = None,
    *,
    briefing_type: str | None = None,
) -> dict[str, Any]:
    _ = briefing_type
    text = answer or ""
    citation_count = len(citations or [])
    used = sorted({int(match) for match in _CITATION_MARKER_RE.findall(text)})
    available = list(range(1, citation_count + 1))
    available_set = set(available)
    unknown = [number for number in used if number not in available_set]
    uncited_claims = _uncited_regulatory_claims(text) if citation_count else []
    warnings: list[str] = []
    if unknown:
        warnings.append("La respuesta usa marcadores de cita que no existen en las citas retornadas.")
    if uncited_claims:
        warnings.append("Hay afirmaciones regulatorias o de cumplimiento sin marcador de cita.")
    return _citation_validation_payload(
        valid=not unknown and not uncited_claims,
        used_citation_numbers=used,
        available_citation_numbers=available,
        unknown_citation_numbers=unknown,
        uncited_regulatory_claims=uncited_claims,
        warnings=warnings,
    )


def validate_compliance_language(
    answer: str,
    *,
    briefing_type: str | None = None,
) -> dict[str, Any]:
    _ = briefing_type
    normalized = _normalize_text(answer or "")
    flagged: list[str] = []
    for phrase, pattern in BLOCKED_COMPLIANCE_PATTERNS:
        if re.search(pattern, normalized):
            flagged.append(phrase)
    allowed_present = [phrase for phrase in ALLOWED_COMPLIANCE_LANGUAGE if phrase in normalized]
    warnings = (
        ["La respuesta contiene lenguaje de cumplimiento que debe tratarse como bandera, no conclusión."]
        if flagged
        else []
    )
    return _compliance_validation_payload(
        valid=not flagged,
        flagged_phrases=flagged,
        allowed_language_present=allowed_present,
        warnings=warnings,
    )


def _citation_validation_payload(
    *,
    valid: bool,
    used_citation_numbers: list[int],
    available_citation_numbers: list[int],
    unknown_citation_numbers: list[int],
    uncited_regulatory_claims: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "valid": valid,
        "used_citation_numbers": used_citation_numbers,
        "available_citation_numbers": available_citation_numbers,
        "unknown_citation_numbers": unknown_citation_numbers,
        "uncited_regulatory_claims": uncited_regulatory_claims,
        "warnings": warnings,
    }


def _compliance_validation_payload(
    *,
    valid: bool,
    flagged_phrases: list[str],
    allowed_language_present: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "valid": valid,
        "flagged_phrases": flagged_phrases,
        "allowed_language_present": allowed_language_present,
        "warnings": warnings,
    }


def _uncited_regulatory_claims(answer: str) -> list[str]:
    claims: list[str] = []
    for sentence in _candidate_sentences(answer):
        if sentence.rstrip().endswith("?"):
            continue
        if _CITATION_MARKER_RE.search(sentence):
            continue
        normalized = _normalize_text(sentence)
        if any(_normalize_text(term) in normalized for term in REGULATORY_CLAIM_TERMS):
            claims.append(_compact(sentence, limit=240))
        if len(claims) >= 5:
            break
    return claims


def _candidate_sentences(answer: str) -> list[str]:
    rows: list[str] = []
    for line in (answer or "").splitlines():
        if _section_heading(line)[0]:
            continue
        compact = " ".join(line.split())
        if not compact:
            continue
        rows.extend(sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", compact) if sentence.strip())
    return rows


def _content_items(lines: list[str]) -> list[str]:
    items: list[str] = []
    paragraph: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if paragraph:
                items.append(_compact(" ".join(paragraph)))
                paragraph = []
            continue
        bullet = _BULLET_RE.sub("", stripped).strip()
        if _BULLET_RE.match(stripped):
            if paragraph:
                items.append(_compact(" ".join(paragraph)))
                paragraph = []
            if bullet:
                items.append(_compact(bullet))
        else:
            paragraph.append(stripped)
    if paragraph:
        items.append(_compact(" ".join(paragraph)))
    return [item for item in items if item]


def _section_heading(line: str) -> tuple[str | None, str]:
    stripped = (line or "").strip()
    if not stripped:
        return None, ""
    candidate = _HEADING_PREFIX_RE.sub("", stripped).strip()
    candidate = _EMPHASIS_RE.sub("", candidate).strip()
    candidate = _BULLET_RE.sub("", candidate).strip()
    if not candidate:
        return None, ""

    label = candidate.rstrip(":").strip()
    inline_text = ""
    if ":" in candidate:
        label, inline_text = candidate.split(":", 1)
        label = label.strip()
        inline_text = inline_text.strip()

    normalized_label = _normalize_text(label)
    aliases = _section_aliases()
    if normalized_label in aliases:
        return aliases[normalized_label], inline_text

    normalized_candidate = _normalize_text(candidate)
    if normalized_candidate in aliases:
        return aliases[normalized_candidate], ""
    return None, ""


def _section_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key, title in STRUCTURED_SECTION_TITLES.items():
        aliases[_normalize_text(title)] = key
        aliases[_normalize_text(key.replace("_", " "))] = key
    aliases.update(
        {
            "citas": "citas_usadas",
            "fuentes usadas": "citas_usadas",
            "preguntas de seguimiento": "preguntas_sugeridas",
            "preguntas sugeridas de seguimiento": "preguntas_sugeridas",
            "riesgos posibles": "riesgo_posible",
            "recomendaciones de verificacion": "recomendaciones",
        }
    )
    return aliases


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    lowered = without_accents.casefold()
    return re.sub(r"\s+", " ", lowered).strip()


def _compact(value: str, *, limit: int = 900) -> str:
    compact = " ".join((value or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3].rstrip()}..."


_build_answer_quality_metadata = build_answer_quality_metadata
_normalize_structured_answer = normalize_structured_answer
_validate_citations = validate_citations
_validate_compliance_language = validate_compliance_language
