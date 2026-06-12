from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from chec_dashboard.services.agent_context_service import normalize_text
from chec_dashboard.services.timeseries_interpretability.contracts import (
    TimeseriesInterpretabilityNarrative,
)


FORBIDDEN_PHRASES = (
    "causa definitiva comprobada",
    "esto demuestra que",
    "incumplimiento confirmado",
    "no cumple",
)

NO_DOCUMENTARY_EVIDENCE_PHRASES = (
    "sin soporte documental",
    "sin evidencia documental",
    "sin documentos",
    "no se recuperaron documentos",
    "no hay documentos",
    "documentos no disponibles",
    "evidencia documental no disponible",
)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {"valid": self.valid, "errors": self.errors, "warnings": self.warnings}


def _all_text(narrative: TimeseriesInterpretabilityNarrative) -> str:
    rows: list[str] = [
        narrative.headline,
        *narrative.executive_summary,
        *narrative.key_findings,
        *narrative.period_narratives,
        *narrative.data_gaps,
        *narrative.recommended_actions,
        *narrative.limitations,
    ]
    for point in narrative.point_narratives:
        rows.extend(
            [
                point.headline,
                *point.why_marked,
                *point.observed_values,
                *point.likely_drivers,
                *point.domain_support,
                *point.documentary_support,
                *point.missing_evidence,
                *point.recommended_checks,
            ]
        )
    for row in narrative.evidence_matrix:
        rows.extend([row.signal, row.structured_evidence, row.domain_evidence or "", row.documentary_evidence or ""])
    return "\n".join(rows)


def _allowed_entity_tokens(deterministic_payload: dict[str, Any], citations: list[dict[str, Any]]) -> set[str]:
    labels: list[str] = []
    for point in deterministic_payload.get("critical_points") or []:
        for key in ("top_causes", "top_event_families", "top_equipment", "top_circuits"):
            for item in point.get(key) or []:
                if isinstance(item, dict) and item.get("label"):
                    labels.append(str(item["label"]))
        for event in point.get("top_events") or []:
            if not isinstance(event, dict):
                continue
            for key in ("causa", "event_family", "circuito", "municipio", "equipo_ope", "tipo_equi_ope"):
                if event.get(key):
                    labels.append(str(event[key]))
    for citation in citations:
        for key in ("title", "document_title", "source_path", "source_uri"):
            if citation.get(key):
                labels.append(str(citation[key]))
    tokens: set[str] = set()
    for label in labels:
        tokens.update(normalize_text(label).split())
    return {token for token in tokens if len(token) >= 3}


def _citation_indexes(narrative: TimeseriesInterpretabilityNarrative) -> list[int]:
    indexes = list(narrative.citations_used)
    for point in narrative.point_narratives:
        indexes.extend(point.citations_used)
    for row in narrative.evidence_matrix:
        indexes.extend(row.citations_used)
    return indexes


def _is_documentary_placeholder(text: str | None) -> bool:
    normalized = normalize_text(text or "")
    if not normalized or normalized in {"n d", "na", "no aplica"}:
        return True
    return any(phrase in normalized for phrase in NO_DOCUMENTARY_EVIDENCE_PHRASES)


def validate_narrative(
    *,
    narrative: TimeseriesInterpretabilityNarrative,
    deterministic_payload: dict[str, Any],
    citations: list[dict[str, Any]],
) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    points = deterministic_payload.get("critical_points") or []
    allowed_dates = {str(point.get("fecha_dia")) for point in points}
    ranks_by_date = {str(point.get("fecha_dia")): int(point.get("rank", 0)) for point in points}
    confidence_by_date = {str(point.get("fecha_dia")): str(point.get("confidence", "medium")) for point in points}
    max_citation = len(citations)

    for point in narrative.point_narratives:
        if point.fecha_dia not in allowed_dates:
            errors.append(f"point_narrative_date_not_grounded:{point.fecha_dia}")
        elif point.rank != ranks_by_date.get(point.fecha_dia):
            errors.append(f"point_rank_mismatch:{point.fecha_dia}")
        if confidence_by_date.get(point.fecha_dia) == "low" and not point.missing_evidence:
            errors.append(f"low_confidence_without_missing_evidence:{point.fecha_dia}")

    for idx in _citation_indexes(narrative):
        if idx < 1 or idx > max_citation:
            errors.append(f"invalid_citation:{idx}")

    for point in narrative.point_narratives:
        for text in point.documentary_support:
            if _is_documentary_placeholder(text):
                continue
            if not point.citations_used:
                errors.append(f"uncited_documentary_claim:{point.fecha_dia}")
    for row in narrative.evidence_matrix:
        if row.documentary_evidence and not _is_documentary_placeholder(row.documentary_evidence):
            if not row.citations_used:
                errors.append(f"uncited_documentary_claim:{row.fecha_dia or 'evidence_matrix'}")

    flattened = _all_text(narrative).lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in flattened:
            errors.append(f"forbidden_phrase:{phrase}")

    allowed_entity_tokens = _allowed_entity_tokens(deterministic_payload, citations)
    for point in narrative.point_narratives:
        for driver in point.likely_drivers:
            normalized = normalize_text(driver)
            driver_tokens = set(normalized.split())
            mentions_grounded_entity = bool(driver_tokens & allowed_entity_tokens)
            high_risk_claim = bool(re.search(r"\b(causa|equipo|circuito|domina|explica|provoca)\b", normalized))
            if high_risk_claim and not mentions_grounded_entity and not point.citations_used:
                errors.append(f"ungrounded_driver_claim:{point.fecha_dia}")

    if not narrative.executive_summary:
        warnings.append("empty_executive_summary")
    if points and not narrative.point_narratives:
        errors.append("missing_point_narratives")

    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
