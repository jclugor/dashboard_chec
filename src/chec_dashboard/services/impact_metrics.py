from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ImpactMetric:
    key: str
    label: str
    daily_column: str
    total_column: str
    description: str


IMPACT_METRICS: tuple[ImpactMetric, ...] = (
    ImpactMetric("UITI", "UITI", "UITI", "uiti_total", "Impacto UITI agregado desde UITI_VANO."),
    ImpactMetric("UITI_VANO", "UITI vano", "UITI_VANO", "uiti_vano_total", "Impacto asignado al vano."),
    ImpactMetric("EVENT_COUNT", "Eventos", "EVENT_COUNT", "event_count", "Conteo de eventos."),
    ImpactMetric("USERS", "Usuarios", "USERS", "users_affected_total", "Usuarios afectados."),
    ImpactMetric("DURATION_RAW", "Duración fuente", "DURATION_RAW", "duration_raw_total", "Duración en la unidad original."),
)

DEFAULT_IMPACT_METRIC_KEY = "UITI"


def metric_options() -> list[dict[str, str]]:
    return [{"label": metric.label, "value": metric.key} for metric in IMPACT_METRICS]


def metric_keys() -> tuple[str, ...]:
    return tuple(metric.key for metric in IMPACT_METRICS)


def normalize_metric_key(value: str | None) -> str:
    candidate = (value or DEFAULT_IMPACT_METRIC_KEY).strip().upper()
    valid = set(metric_keys())
    return candidate if candidate in valid else DEFAULT_IMPACT_METRIC_KEY


def metric_definition(value: str | None) -> ImpactMetric:
    key = normalize_metric_key(value)
    for metric in IMPACT_METRICS:
        if metric.key == key:
            return metric
    return IMPACT_METRICS[0]


def empty_metric_totals() -> dict[str, float]:
    return {metric.key: 0.0 for metric in IMPACT_METRICS}


def coerce_metric_totals(values: dict[str, Any] | None) -> dict[str, float]:
    totals = empty_metric_totals()
    for key, value in (values or {}).items():
        normalized_key = normalize_metric_key(str(key))
        try:
            totals[normalized_key] = float(value or 0.0)
        except (TypeError, ValueError):
            totals[normalized_key] = 0.0
    return totals
