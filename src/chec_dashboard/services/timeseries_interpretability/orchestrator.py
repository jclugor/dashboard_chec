from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.core.logging import get_logger
from chec_dashboard.services.citation_service import citation_payload
from chec_dashboard.services.llm_service import generate_llm_structured_answer, llm_configured
from chec_dashboard.services.retrieval_service import retrieve_chatbot_chunks
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
    format_chunks_for_prompt,
    render_timeseries_prompt,
)
from chec_dashboard.services.timeseries_interpretability.retrieval_query import (
    build_timeseries_retrieval_query,
)
from chec_dashboard.services.timeseries_interpretability.validators import (
    validate_narrative,
)


TIMESERIES_INTERPRETABILITY_QUESTION = (
    "Explica los puntos criticos de la evolucion SAIDI/SAIFI usando solo los datos "
    "estructurados y documentos recuperados. Indica datos faltantes y evita afirmar "
    "causalidad definitiva."
)


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
            "Starting SAIDI/SAIFI interpretability run",
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
                "SAIDI/SAIFI interpretability fallback",
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
            retrieval_query = build_timeseries_retrieval_query(context_package)
            chunks = retrieve_chatbot_chunks(
                settings,
                selected_context=context_package,
                question=retrieval_query,
                skill_resolution=skill_resolution,
            )
            citations = citation_payload(chunks)
            if not chunks:
                return fallback("no_retrieved_chunks", mode="retrieval_empty", retrieval_query=retrieval_query)

            prompt, prompt_meta = render_timeseries_prompt(
                context_package=context_package,
                docs_text=format_chunks_for_prompt(chunks),
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

            narrative = TimeseriesInterpretabilityNarrative.model_validate(raw_narrative)
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
            trace = InterpretabilityTrace(
                mode="llm_structured",
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
                validation=validation.to_payload(),
                latency_ms=latency_ms,
            )
            status = InterpretabilityStatus(
                text=deterministic_payload.get("status_text") or narrative.headline,
                severity="ok",
                data_quality_flags=data_quality_flags,
                fallback_used=False,
            )
            logger.info(
                "SAIDI/SAIFI interpretability run completed",
                extra={
                    "retrieved_chunk_count": len(chunks),
                    "citation_count": len(citations),
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
