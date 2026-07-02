from __future__ import annotations

import re
from typing import Literal

from chec_dashboard.services.agent_context_service import normalize_text


EvidenceLevel = Literal[
    "structured_observation",
    "documentary_evidence",
    "normative_evidence",
    "model_signal",
    "simulation_result",
    "llm_interpretation",
]

ClaimType = Literal[
    "definitive_causality",
    "definitive_legal_conclusion",
    "normative_claim",
    "documentary_claim",
    "model_claim",
    "field_inspection_claim",
    "structured_observation",
    "general_interpretation",
]


FORBIDDEN_CLAIM_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "definitive_causality": (
        re.compile(r"\b(causo definitivamente|causa fue|demuestra que|prueba que)\b", re.IGNORECASE),
    ),
    "definitive_legal_conclusion": (
        re.compile(r"\b(incumplimiento confirmado|responsabilidad legal|sancion aplicable|no cumple|cumple)\b", re.IGNORECASE),
    ),
    "model_as_proof": (
        re.compile(r"\b(el modelo demuestra|la prediccion prueba|la mascara prueba)\b", re.IGNORECASE),
    ),
    "unsupported_field_inspection": (
        re.compile(r"\b(se inspecciono en campo|la cuadrilla confirmo|visita de campo confirmo)\b", re.IGNORECASE),
    ),
}


def classify_claim(text: str) -> ClaimType:
    normalized = normalize_text(text)
    if _matches("definitive_causality", text):
        return "definitive_causality"
    if _matches("definitive_legal_conclusion", text):
        return "definitive_legal_conclusion"
    if any(term in normalized for term in ("creg", "retie", "norma", "normativa", "regulatorio", "requisito")):
        return "normative_claim"
    if any(term in normalized for term in ("documento", "bitacora", "mantenimiento", "registro", "evidencia documental")):
        return "documentary_claim"
    if any(term in normalized for term in ("modelo", "prediccion", "mascara", "relevancia", "feature")):
        return "model_claim"
    if any(term in normalized for term in ("inspeccion", "campo", "cuadrilla")):
        return "field_inspection_claim"
    if any(term in normalized for term in ("uiti", "saidi", "saifi", "duracion", "usuarios", "circuito")):
        return "structured_observation"
    return "general_interpretation"


def contains_forbidden_claim(text: str) -> bool:
    return any(pattern.search(text or "") for patterns in FORBIDDEN_CLAIM_PATTERNS.values() for pattern in patterns)


def required_evidence_for_claim(claim_type: str) -> list[EvidenceLevel]:
    mapping: dict[str, list[EvidenceLevel]] = {
        "definitive_causality": ["structured_observation", "documentary_evidence", "model_signal"],
        "definitive_legal_conclusion": ["normative_evidence"],
        "normative_claim": ["normative_evidence"],
        "documentary_claim": ["documentary_evidence"],
        "model_claim": ["model_signal"],
        "field_inspection_claim": ["documentary_evidence"],
        "structured_observation": ["structured_observation"],
        "general_interpretation": ["llm_interpretation"],
    }
    return mapping.get(claim_type, ["llm_interpretation"])


def safe_claim_language(claim_type: str) -> str:
    mapping = {
        "definitive_causality": "La evidencia disponible sugiere una asociacion posible, no causalidad definitiva.",
        "definitive_legal_conclusion": "Presentar como bandera de evidencia, no conclusion legal o regulatoria final.",
        "normative_claim": "Toda afirmacion normativa debe citar fragmentos recuperados.",
        "documentary_claim": "Toda afirmacion documental debe citar la fuente recuperada.",
        "model_claim": "Describir como senal del modelo, no como prueba.",
        "field_inspection_claim": "Indicar que requiere verificacion de campo salvo que exista soporte citado.",
    }
    return mapping.get(claim_type, "Usar lenguaje prudente y declarar limitaciones.")


def _matches(key: str, text: str) -> bool:
    return any(pattern.search(text or "") for pattern in FORBIDDEN_CLAIM_PATTERNS.get(key, ()))
