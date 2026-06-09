from __future__ import annotations

from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.timeseries_interpretability.deterministic_narrative import (
    flatten_narrative_to_text,
)
from chec_dashboard.services.timeseries_interpretability.orchestrator import (
    TIMESERIES_INTERPRETABILITY_QUESTION,
    TimeseriesInterpretabilityOrchestrator,
)


def attach_interpretability_narrative(
    settings: Settings,
    payload: dict[str, Any],
    *,
    include_agent_text: bool,
) -> dict[str, Any]:
    updated = dict(payload)
    run = TimeseriesInterpretabilityOrchestrator().run(
        settings,
        deterministic_payload=updated,
        include_agent_text=include_agent_text,
    )
    deterministic_payload = run.deterministic_narrative.model_dump(mode="json")
    narrative_payload = run.narrative.model_dump(mode="json")
    updated["deterministic_narrative"] = deterministic_payload
    updated["narrative"] = narrative_payload
    updated["status"] = run.status.model_dump(mode="json")
    updated["interpretability_trace"] = run.trace.model_dump(mode="json")
    updated["corpus_citations"] = run.citations
    updated["insight_text"] = flatten_narrative_to_text(run.narrative)
    updated["status_text"] = run.status.text or str(updated.get("status_text") or "")
    return updated


def attach_interpretability_agent_text(
    settings: Settings,
    payload: dict[str, Any],
    *,
    include_agent_text: bool,
) -> dict[str, Any]:
    return attach_interpretability_narrative(
        settings,
        payload,
        include_agent_text=include_agent_text,
    )
