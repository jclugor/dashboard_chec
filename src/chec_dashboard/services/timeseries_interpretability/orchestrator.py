from __future__ import annotations

from dataclasses import dataclass
import re
from time import perf_counter
from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.core.logging import get_logger
from chec_dashboard.services.llm_service import generate_llm_structured_answer, llm_configured
from chec_dashboard.services.skill_service import resolve_skill
from chec_dashboard.services.timeseries_interpretability.context_builder import (
    build_timeseries_context_package_v2,
)
from chec_dashboard.services.timeseries_interpretability.contracts import (
    InterpretabilityStatus,
    InterpretabilityTrace,
    TimeseriesInterpretabilityNarrative,
)
from chec_dashboard.services.timeseries_interpretability.deterministic_narrative import (
    build_deterministic_narrative,
)
from chec_dashboard.services.timeseries_interpretability.prompts import (
    render_timeseries_prompt,
)
from chec_dashboard.services.timeseries_interpretability.validators import (
    validate_narrative,
)


TIMESERIES_INTERPRETABILITY_QUESTION = (
    "Explica los comportamientos y puntos criticos de la evolucion del impacto UITI "
    "usando solo datos estructurados, descripciones de variables, modos e interacciones "
    "de dominio. Indica datos faltantes y evita afirmar causalidad definitiva."
)

TOP_LEVEL_TEXT_LIST_FIELDS = (
    "executive_summary",
    "key_findings",
    "period_narratives",
    "data_gaps",
    "recommended_actions",
    "limitations",
)
POINT_TEXT_LIST_FIELDS = (
    "why_marked",
    "observed_values",
    "likely_drivers",
    "domain_support",
    "documentary_support",
    "missing_evidence",
    "recommended_checks",
)
CONFIDENCE_VALUES = {"high", "medium", "low"}
NARRATIVE_SOURCE_VALUES = {"llm", "deterministic", "validated_repair"}
NO_DOCUMENTARY_SUPPORT_TEXT = "Sin soporte documental suficiente para este punto."
NO_DOCUMENTARY_EVIDENCE_TEXT = "Sin soporte documental suficiente."
NO_DOCUMENTARY_PHRASES = (
    "sin soporte documental",
    "sin evidencia documental",
    "sin documentos",
    "no se recuperaron documentos",
    "no hay documentos",
)


def _text_items(value: Any, *, limit: int | None = None) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    items = [str(item).strip() for item in raw_items if str(item or "").strip()]
    return items[:limit] if limit is not None else items


def _unique_text(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _int_items(value: Any) -> list[int]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    items: list[int] = []
    for item in raw_items:
        try:
            items.append(int(item))
        except (TypeError, ValueError):
            continue
    return items


def _normalize_raw_narrative_shape(raw_narrative: Any) -> tuple[Any, bool]:
    if not isinstance(raw_narrative, dict):
        return raw_narrative, False
    changed = False
    normalized = dict(raw_narrative)

    source = str(normalized.get("source") or "llm").strip()
    if source not in NARRATIVE_SOURCE_VALUES:
        normalized["source"] = "llm"
        changed = True

    for field in TOP_LEVEL_TEXT_LIST_FIELDS:
        if field in normalized and not isinstance(normalized[field], list):
            normalized[field] = _text_items(normalized[field])
            changed = True
    if "citations_used" in normalized and (
        not isinstance(normalized.get("citations_used"), list)
        or not all(isinstance(item, int) for item in normalized.get("citations_used") or [])
    ):
        normalized["citations_used"] = _int_items(normalized.get("citations_used"))
        changed = True

    for collection_key in ("point_narratives", "evidence_matrix"):
        if collection_key not in normalized:
            continue
        collection = normalized[collection_key]
        if isinstance(collection, dict):
            collection = [collection]
            changed = True
        elif not isinstance(collection, list):
            collection = []
            changed = True

        cleaned_collection: list[Any] = []
        for item in collection:
            if not isinstance(item, dict):
                changed = True
                continue
            cleaned = dict(item)
            if collection_key == "point_narratives":
                for field in POINT_TEXT_LIST_FIELDS:
                    if field in cleaned and not isinstance(cleaned[field], list):
                        cleaned[field] = _text_items(cleaned[field])
                        changed = True
            if "citations_used" in cleaned and (
                not isinstance(cleaned.get("citations_used"), list)
                or not all(isinstance(ref, int) for ref in cleaned.get("citations_used") or [])
            ):
                cleaned["citations_used"] = _int_items(cleaned.get("citations_used"))
                changed = True
            confidence = str(cleaned.get("confidence") or "medium").strip().lower()
            if confidence not in CONFIDENCE_VALUES:
                cleaned["confidence"] = "medium"
                changed = True
            cleaned_collection.append(cleaned)
        normalized[collection_key] = cleaned_collection

    return normalized, changed


def _is_documentary_placeholder(text: str | None) -> bool:
    normalized = str(text or "").strip().casefold()
    if not normalized or normalized in {"n/d", "n d", "na", "no aplica"}:
        return True
    return any(phrase in normalized for phrase in NO_DOCUMENTARY_PHRASES)


def _citation_refs_from_text(items: list[str], *, max_citation: int) -> list[int]:
    refs: list[int] = []
    for item in items:
        for match in re.findall(r"\[(\d+)\]", item):
            try:
                ref = int(match)
            except ValueError:
                continue
            if 1 <= ref <= max_citation and ref not in refs:
                refs.append(ref)
    return refs


def _valid_citation_refs(items: list[int], *, max_citation: int) -> list[int]:
    return _unique_ints([item for item in items if 1 <= item <= max_citation])


def _sanitize_uncited_documentary_claims(
    narrative: TimeseriesInterpretabilityNarrative,
    *,
    max_citation: int,
) -> tuple[TimeseriesInterpretabilityNarrative, bool]:
    changed = False
    payload = narrative.model_dump(mode="json")

    top_level_refs = _valid_citation_refs(_int_items(payload.get("citations_used")), max_citation=max_citation)
    if top_level_refs != _int_items(payload.get("citations_used")):
        payload["citations_used"] = top_level_refs
        changed = True

    for point in payload.get("point_narratives") or []:
        if not isinstance(point, dict):
            continue
        support = _text_items(point.get("documentary_support"))
        existing_refs = _valid_citation_refs(_int_items(point.get("citations_used")), max_citation=max_citation)
        refs = _valid_citation_refs(
            [*existing_refs, *_citation_refs_from_text(support, max_citation=max_citation)],
            max_citation=max_citation,
        )
        if refs != _int_items(point.get("citations_used")):
            point["citations_used"] = refs
            changed = True
        if support and not all(_is_documentary_placeholder(item) for item in support):
            if refs:
                point["citations_used"] = refs
            else:
                point["documentary_support"] = [NO_DOCUMENTARY_SUPPORT_TEXT]
                point["missing_evidence"] = _unique_text(
                    [*_text_items(point.get("missing_evidence")), "documentary_support_not_cited"]
                )
                point["citations_used"] = []
                changed = True

    for row in payload.get("evidence_matrix") or []:
        if not isinstance(row, dict):
            continue
        documentary_evidence = str(row.get("documentary_evidence") or "").strip()
        existing_refs = _valid_citation_refs(_int_items(row.get("citations_used")), max_citation=max_citation)
        refs = _valid_citation_refs(
            [*existing_refs, *_citation_refs_from_text([documentary_evidence], max_citation=max_citation)],
            max_citation=max_citation,
        )
        if refs != _int_items(row.get("citations_used")):
            row["citations_used"] = refs
            changed = True
        if documentary_evidence and not _is_documentary_placeholder(documentary_evidence):
            if refs:
                row["citations_used"] = refs
            else:
                row["documentary_evidence"] = NO_DOCUMENTARY_EVIDENCE_TEXT
                row["citations_used"] = []
                changed = True

    if not changed:
        return narrative, False
    return TimeseriesInterpretabilityNarrative.model_validate(payload), True


def _unique_ints(items: list[int]) -> list[int]:
    unique: list[int] = []
    for item in items:
        if item not in unique:
            unique.append(item)
    return unique


def _schema_error_payload(exc: Exception) -> dict[str, Any]:
    if hasattr(exc, "errors"):
        try:
            errors = [
                ".".join(str(part) for part in error.get("loc", [])) or str(error.get("type") or "schema_error")
                for error in exc.errors()
            ]
            return {"valid": False, "errors": errors[:10], "warnings": []}
        except Exception:
            pass
    return {"valid": False, "errors": [str(exc)], "warnings": []}


def _repair_tool_payload_narrative(
    raw_narrative: dict[str, Any] | None,
    deterministic: TimeseriesInterpretabilityNarrative,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw_narrative, dict) or raw_narrative.get("headline"):
        return raw_narrative, None
    if not any(key in raw_narrative for key in ("analysis", "observations", "operational_hypotheses")):
        return raw_narrative, None

    repaired = deterministic.model_dump(mode="json")
    analysis = _text_items(raw_narrative.get("analysis"), limit=8)
    observations = _text_items(raw_narrative.get("observations"), limit=4)
    hypotheses = _text_items(raw_narrative.get("operational_hypotheses"), limit=4)
    missing = _text_items(raw_narrative.get("missing_evidence"), limit=6)
    quality_flags = _text_items(raw_narrative.get("data_quality_flags"), limit=6)
    supporting_docs = _text_items(raw_narrative.get("supporting_documents"), limit=4)

    repaired["source"] = "validated_repair"
    if analysis:
        repaired["headline"] = analysis[0][:240]
        repaired["executive_summary"] = analysis[:3]
        repaired["key_findings"] = analysis[3:] or observations[:3]
    if observations:
        repaired["period_narratives"] = observations
    repaired["data_gaps"] = _unique_text([*repaired.get("data_gaps", []), *missing, *quality_flags])
    repaired["recommended_actions"] = _unique_text(
        [
            *repaired.get("recommended_actions", []),
            "Contrastar las hipotesis operativas del LLM con registros de campo y bitacoras antes de priorizar intervenciones.",
            *hypotheses[:2],
        ]
    )
    repaired["limitations"] = _unique_text(
        [
            *repaired.get("limitations", []),
            "La salida LLM fue normalizada desde un objeto de herramienta al esquema narrativo requerido.",
            *[f"Documento recuperado mencionado por el LLM: {item}" for item in supporting_docs],
        ]
    )
    repaired["citations_used"] = []
    return repaired, "tool_payload_shape"


@dataclass
class TimeseriesInterpretabilityRun:
    payload: dict[str, Any]
    deterministic_narrative: TimeseriesInterpretabilityNarrative
    narrative: TimeseriesInterpretabilityNarrative
    citations: list[dict[str, Any]]
    status: InterpretabilityStatus
    trace: InterpretabilityTrace


class TimeseriesInterpretabilityOrchestrator:
    def run(
        self,
        settings: Settings,
        *,
        deterministic_payload: dict[str, Any],
        include_agent_text: bool,
    ) -> TimeseriesInterpretabilityRun:
        started = perf_counter()
        logger = get_logger(__name__, settings.log_level)
        deterministic = build_deterministic_narrative(deterministic_payload)
        data_quality_flags = sorted(
            {
                str(flag)
                for point in (deterministic_payload.get("critical_points") or [])
                for flag in (point.get("data_quality_flags") or [])
                if str(flag).strip()
            }
        )

        logger.info(
            "Starting UITI impact interpretability run",
            extra={
                "critical_point_count": len(deterministic_payload.get("critical_points") or []),
                "include_agent_text": include_agent_text,
            },
        )

        def fallback(
            reason: str,
            *,
            mode: str = "deterministic",
            validation: dict[str, Any] | None = None,
            retrieval_query: str | None = None,
            chunks: list[dict[str, Any]] | None = None,
        ) -> TimeseriesInterpretabilityRun:
            latency_ms = int((perf_counter() - started) * 1000)
            severity = "ok" if reason in {"disabled", "not_configured"} else "warning"
            trace = InterpretabilityTrace(
                mode=mode,
                fallback_used=True,
                fallback_reason=reason,
                retrieval_query=retrieval_query,
                retrieved_chunk_ids=[
                    str(chunk.get("chunk_id") or chunk.get("id"))
                    for chunk in (chunks or [])
                    if chunk.get("chunk_id") or chunk.get("id")
                ],
                citation_count=0,
                validation=validation or {},
                latency_ms=latency_ms,
            )
            status = InterpretabilityStatus(
                text=deterministic_payload.get("status_text") or deterministic.headline,
                severity=severity,
                data_quality_flags=data_quality_flags,
                fallback_used=True,
                fallback_reason=reason,
            )
            logger.info(
                "UITI impact interpretability fallback",
                extra={
                    "fallback_reason": reason,
                    "mode": mode,
                    "latency_ms": latency_ms,
                    "validation_errors": (validation or {}).get("errors", []),
                },
            )
            return TimeseriesInterpretabilityRun(
                payload=deterministic_payload,
                deterministic_narrative=deterministic,
                narrative=deterministic,
                citations=[],
                status=status,
                trace=trace,
            )

        if not include_agent_text or not settings.chatbot_enabled:
            return fallback("disabled")
        if not llm_configured(settings):
            return fallback("not_configured")

        chunks: list[dict[str, Any]] = []
        retrieval_query: str | None = None
        try:
            skill_resolution = resolve_skill("timeseries_interpretability", settings)
            context_package = build_timeseries_context_package_v2(deterministic_payload)
            citations: list[dict[str, Any]] = []

            prompt, prompt_meta = render_timeseries_prompt(
                context_package=context_package,
                docs_text="No aplica: el flujo de pasos 1-3 no usa documentos ni RAG.",
                question_text=TIMESERIES_INTERPRETABILITY_QUESTION,
            )
            raw_narrative = generate_llm_structured_answer(
                settings,
                prompt=prompt,
                schema_name="TimeseriesInterpretabilityNarrative",
                json_schema=TimeseriesInterpretabilityNarrative.model_json_schema(),
                context_package=context_package,
                question=TIMESERIES_INTERPRETABILITY_QUESTION,
                citations=citations,
                skill_resolution=skill_resolution,
            )
            if raw_narrative is None:
                return fallback(
                    "structured_generation_failed",
                    mode="llm_failed",
                    retrieval_query=retrieval_query,
                    chunks=chunks,
                )

            repair_reasons: list[str] = []
            raw_narrative, repair_reason = _repair_tool_payload_narrative(raw_narrative, deterministic)
            if repair_reason:
                repair_reasons.append(repair_reason)
            raw_narrative, normalized_shape = _normalize_raw_narrative_shape(raw_narrative)
            if normalized_shape:
                repair_reasons.append("schema_shape_coercion")
            try:
                narrative = TimeseriesInterpretabilityNarrative.model_validate(raw_narrative)
            except Exception as exc:
                return fallback(
                    "schema_validation_failed",
                    mode="llm_schema_validation_failed",
                    validation=_schema_error_payload(exc),
                    retrieval_query=retrieval_query,
                    chunks=chunks,
                )
            narrative, sanitized_documentary_claims = _sanitize_uncited_documentary_claims(
                narrative,
                max_citation=len(citations),
            )
            if sanitized_documentary_claims:
                repair_reasons.append("uncited_documentary_claim_sanitized")
            validation = validate_narrative(
                narrative=narrative,
                deterministic_payload=deterministic_payload,
                citations=citations,
            )
            if not validation.valid:
                return fallback(
                    "validation_failed",
                    mode="llm_validation_failed",
                    validation=validation.to_payload(),
                    retrieval_query=retrieval_query,
                    chunks=chunks,
                )

            latency_ms = int((perf_counter() - started) * 1000)
            validation_payload = validation.to_payload()
            if repair_reasons:
                validation_payload = {**validation_payload, "repair_applied": "+".join(repair_reasons)}
            status_flags = sorted(
                {
                    *data_quality_flags,
                }
            )
            trace = InterpretabilityTrace(
                mode="llm_structured_semantic",
                fallback_used=False,
                skill_id=skill_resolution.skill_id,
                skill_version=skill_resolution.skill_version,
                skill_hash=skill_resolution.skill_hash,
                prompt_name=prompt_meta["prompt_name"],
                prompt_version=prompt_meta["prompt_version"],
                prompt_hash=prompt_meta["prompt_hash"],
                retrieval_query=retrieval_query,
                retrieved_chunk_ids=[
                    str(chunk.get("chunk_id") or chunk.get("id"))
                    for chunk in chunks
                    if chunk.get("chunk_id") or chunk.get("id")
                ],
                citation_count=len(citations),
                validation=validation_payload,
                latency_ms=latency_ms,
            )
            status = InterpretabilityStatus(
                text=deterministic_payload.get("status_text") or narrative.headline,
                severity="ok",
                data_quality_flags=status_flags,
                fallback_used=False,
            )
            logger.info(
                "UITI impact interpretability run completed",
                extra={
                    "retrieved_chunk_count": len(chunks),
                    "citation_count": len(citations),
                    "semantic_only": True,
                    "latency_ms": latency_ms,
                },
            )
            return TimeseriesInterpretabilityRun(
                payload=deterministic_payload,
                deterministic_narrative=deterministic,
                narrative=narrative,
                citations=citations,
                status=status,
                trace=trace,
            )
        except Exception as exc:
            return fallback(
                f"exception:{exc.__class__.__name__}",
                mode="exception_fallback",
                retrieval_query=retrieval_query,
                chunks=chunks,
            )
