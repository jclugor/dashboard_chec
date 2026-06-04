from __future__ import annotations

import pandas as pd

from chec_dashboard.services.time_series_interpretability_service import (
    build_summary_interpretability_payload,
)


def _payload(daily, **kwargs):
    return build_summary_interpretability_payload(
        daily_frame=pd.DataFrame(daily),
        start_date=kwargs.get("start_date", "2024-01-01"),
        end_date=kwargs.get("end_date", "2024-01-10"),
        circuit_label="CIR-1",
        metric_mode=kwargs.get("metric_mode", "BOTH"),
        generated_at="2026-06-04T00:00:00Z",
        max_points=kwargs.get("max_points", 5),
        attribution_frame=kwargs.get("attribution_frame"),
        event_frame=kwargs.get("event_frame"),
    )


def test_saidi_spike_detects_expected_golden_reasons() -> None:
    payload = _payload(
        {
            "fecha_dia": ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
            "SAIDI": [0.1, 0.2, 9.5, 0.3],
            "SAIFI": [0.02, 0.03, 0.05, 0.04],
        },
        end_date="2024-01-04",
    )

    point = payload["critical_points"][0]

    assert point["fecha_dia"] == "2024-01-03"
    assert "saidi_high_outlier" in point["criticality_types"]
    assert "sharp_saidi_increase" in point["criticality_types"]
    assert "top_saidi_contributor" in point["criticality_types"]
    assert "saidi_saifi_divergence" in point["criticality_types"]
    assert "saifi_high_outlier" not in point["criticality_types"]


def test_high_saifi_spike_is_detected() -> None:
    payload = _payload(
        {
            "fecha_dia": pd.date_range("2024-01-01", periods=10, freq="D"),
            "SAIDI": [0.2] * 10,
            "SAIFI": [0.1, 0.1, 0.2, 0.1, 0.1, 5.0, 0.2, 0.1, 0.1, 0.1],
        }
    )

    point = next(point for point in payload["critical_points"] if point["fecha_dia"] == "2024-01-06")

    assert point["fecha_dia"] == "2024-01-06"
    assert "saifi_high_outlier" in point["criticality_types"]
    assert "sharp_saifi_increase" in point["criticality_types"]


def test_sharp_decrease_after_spike_is_detected() -> None:
    payload = _payload(
        {
            "fecha_dia": pd.date_range("2024-01-01", periods=10, freq="D"),
            "SAIDI": [0.2, 0.2, 0.3, 0.2, 0.2, 8.0, 0.2, 0.2, 0.2, 0.2],
            "SAIFI": [0.1] * 10,
        }
    )

    all_types = {item for point in payload["critical_points"] for item in point["criticality_types"]}

    assert "sharp_saidi_decrease" in all_types


def test_sustained_period_is_detected() -> None:
    payload = _payload(
        {
            "fecha_dia": pd.date_range("2024-01-01", periods=10, freq="D"),
            "SAIDI": [0.2, 0.2, 0.2, 3.0, 3.1, 3.2, 3.3, 0.2, 0.2, 0.2],
            "SAIFI": [0.1] * 10,
        }
    )

    assert payload["critical_periods"]
    assert payload["critical_periods"][0]["period_type"] == "sustained_saidi_elevated_period"


def test_flat_zero_window_has_no_critical_points() -> None:
    payload = _payload(
        {
            "fecha_dia": pd.date_range("2024-01-01", periods=10, freq="D"),
            "SAIDI": [0.0] * 10,
            "SAIFI": [0.0] * 10,
        }
    )

    assert payload["critical_points"] == []
    assert "No se detectaron puntos criticos" in payload["status_text"]


def test_negative_values_create_quality_flags() -> None:
    payload = _payload(
        {
            "fecha_dia": pd.date_range("2024-01-01", periods=10, freq="D"),
            "SAIDI": [0.2, -1.0, 0.2, 5.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2],
            "SAIFI": [0.1] * 10,
        }
    )

    assert "negative_saidi_values" in payload["status_text"]


def test_missing_event_attribution_lowers_confidence() -> None:
    payload = _payload(
        {
            "fecha_dia": pd.date_range("2024-01-01", periods=10, freq="D"),
            "SAIDI": [0.2, 0.2, 0.2, 5.0, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2],
            "SAIFI": [0.1] * 10,
            "event_count": [0, 0, 0, 3, 0, 0, 0, 0, 0, 0],
        },
        event_frame=pd.DataFrame(),
    )

    point = payload["critical_points"][0]

    assert point["confidence"] == "low"
    assert "missing_event_attribution" in point["data_quality_flags"]


def test_short_window_is_flagged_but_can_still_rank_contributor() -> None:
    payload = _payload(
        {
            "fecha_dia": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "SAIDI": [0.1, 0.1, 4.0],
            "SAIFI": [0.1, 0.1, 0.1],
        },
        end_date="2024-01-03",
    )

    point = payload["critical_points"][0]

    assert "short_window" in payload["status_text"]
    assert point["rank"] == 1
    assert "top_saidi_contributor" in point["criticality_types"]


def test_points_are_ranked_by_combined_criticality() -> None:
    payload = _payload(
        {
            "fecha_dia": pd.date_range("2024-01-01", periods=10, freq="D"),
            "SAIDI": [0.2, 0.2, 0.2, 6.0, 0.2, 0.2, 0.2, 2.0, 0.2, 0.2],
            "SAIFI": [0.1, 0.1, 0.1, 3.0, 0.1, 0.1, 0.1, 0.2, 0.1, 0.1],
        }
    )

    points = payload["critical_points"]

    assert len(points) >= 2
    assert points[0]["rank"] == 1
    assert points[0]["fecha_dia"] == "2024-01-04"
    assert points[0]["criticality_score"] >= points[1]["criticality_score"]
