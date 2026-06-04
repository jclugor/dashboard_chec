from __future__ import annotations

from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.citation_service import citation_payload
from chec_dashboard.services.llm_service import generate_llm_answer, llm_configured
from chec_dashboard.services.prompt_service import build_prompt
from chec_dashboard.services.retrieval_service import retrieve_chatbot_chunks
from chec_dashboard.services.skill_service import resolve_skill
from chec_dashboard.services.time_series_interpretability_service import (
    build_timeseries_context_package,
    deterministic_insight_text,
)


TIMESERIES_INTERPRETABILITY_QUESTION = (
    "Explica los puntos criticos de la evolucion SAIDI/SAIFI usando solo los datos "
    "estructurados y documentos recuperados. Indica datos faltantes y evita afirmar "
    "causalidad definitiva."
)


def attach_interpretability_agent_text(
    settings: Settings,
    payload: dict[str, Any],
    *,
    include_agent_text: bool,
) -> dict[str, Any]:
    updated = dict(payload)
    fallback_text = deterministic_insight_text(updated)
    updated["insight_text"] = fallback_text
    updated["corpus_citations"] = []

    if not include_agent_text or not settings.chatbot_enabled or not llm_configured(settings):
        return updated

    try:
        skill_resolution = resolve_skill("reliability", settings)
        context_package = build_timeseries_context_package(updated)
        chunks = retrieve_chatbot_chunks(
            settings,
            selected_context=context_package,
            question=TIMESERIES_INTERPRETABILITY_QUESTION,
            skill_resolution=skill_resolution,
        )
        if not chunks:
            return updated
        citations = citation_payload(chunks)
        prompt = build_prompt(
            context_package=context_package,
            question=TIMESERIES_INTERPRETABILITY_QUESTION,
            briefing_type="reliability",
            chunks=chunks,
            skill_resolution=skill_resolution,
            settings=settings,
        )
        answer = generate_llm_answer(
            settings,
            prompt=prompt,
            context_package=context_package,
            question=TIMESERIES_INTERPRETABILITY_QUESTION,
            citations=citations,
            skill_resolution=skill_resolution,
        )
    except Exception:
        return updated

    if answer:
        updated["insight_text"] = answer
        updated["corpus_citations"] = citations
    return updated
