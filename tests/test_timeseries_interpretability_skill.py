from __future__ import annotations

from chec_dashboard.services.skill_service import resolve_skill


def test_timeseries_interpretability_skill_loads() -> None:
    resolution = resolve_skill("timeseries_interpretability")

    assert resolution.skill_id == "time_series_interpretability"
    assert "get_timeseries_interpretability_context" in resolution.skill.allowed_tools
    assert not resolution.validation_errors
