from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from chec_dashboard.core.config import settings as base_settings
from chec_dashboard.services.agent_routing_service import (
    _execute_structured_tool,
    route_agent_tools,
)


def _settings(tmp_path: Path):
    return replace(base_settings, cache_enabled=False, chatbot_corpus_dir=tmp_path)


def test_route_agent_tools_includes_timeseries_context_for_peak_question() -> None:
    candidates = route_agent_tools(
        selected_context={},
        context_package={"context_kind": "timeseries_criticality"},
        question="Explica el pico critico de SAIDI",
        briefing_type="reliability",
        question_id=None,
    )

    assert "get_timeseries_interpretability_context" in [candidate.tool_name for candidate in candidates]


def test_timeseries_context_tool_executes_read_only(tmp_path: Path) -> None:
    payload, skip_reason = _execute_structured_tool(
        _settings(tmp_path),
        tool_name="get_timeseries_interpretability_context",
        selected_context={},
        context_package={
            "context_kind": "timeseries_criticality",
            "critical_points": [
                {
                    "fecha_dia": "2024-01-03",
                    "rank": 1,
                    "criticality_types": ["saidi_high_outlier"],
                    "metrics": {"SAIDI": 9.5, "SAIFI": 0.1},
                    "daily_aggregates": {"event_count": 2},
                    "confidence": "medium",
                }
            ],
            "critical_periods": [],
            "status_text": "ok",
        },
    )

    assert skip_reason is None
    assert payload["tool_name"] == "get_timeseries_interpretability_context"
    assert payload["traceability"]["read_only"] is True
