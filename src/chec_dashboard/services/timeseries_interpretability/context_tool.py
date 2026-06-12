from __future__ import annotations

from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.timeseries_interpretability.context_builder import (
    build_timeseries_context_package_v2,
)


def _payload_from_context(*contexts: dict[str, Any] | None) -> dict[str, Any]:
    for context in contexts:
        if not isinstance(context, dict):
            continue
        if context.get("critical_points") is not None or context.get("critical_periods") is not None:
            return dict(context)
        if isinstance(context.get("summary_interpretability"), dict):
            return dict(context["summary_interpretability"])
    return {}


def get_timeseries_interpretability_context_tool(
    settings: Settings,
    *,
    selected_context: dict[str, Any] | None = None,
    context_package: dict[str, Any] | None = None,
    selected_date: str | None = None,
) -> dict[str, Any]:
    _ = settings
    payload = _payload_from_context(context_package, selected_context)
    if not payload:
        payload = {
            "start_date": None,
            "end_date": None,
            "circuit_label": None,
            "metric_key": "UITI",
            "critical_points": [],
            "critical_periods": [],
            "status_text": "No hay contexto de interpretabilidad de serie disponible en esta conversacion.",
        }
    if selected_date:
        payload = {
            **payload,
            "selected_date": selected_date,
            "critical_points": [
                point
                for point in (payload.get("critical_points") or [])
                if str(point.get("fecha_dia")) == str(selected_date)
            ],
        }
    return build_timeseries_context_package_v2(payload)
