from __future__ import annotations

from typing import Any


def _append_unique(values: list[str], candidate: Any) -> None:
    text = str(candidate or "").strip()
    if text and text.lower() not in {item.lower() for item in values}:
        values.append(text)


def _collect_labels(points: list[dict[str, Any]], key: str, limit: int = 5) -> list[str]:
    labels: list[str] = []
    for point in points:
        for item in point.get(key) or []:
            if isinstance(item, dict):
                _append_unique(labels, item.get("label"))
            if len(labels) >= limit:
                return labels
    return labels


def build_timeseries_retrieval_query(context_package: dict[str, Any]) -> str:
    points = context_package.get("critical_points") or []
    hints = context_package.get("retrieval_hints") or {}
    selected = context_package.get("selected_context") or {}
    terms: list[str] = []

    for base in [
        "SAIDI",
        "SAIFI",
        "confiabilidad",
        "calidad del servicio",
        "interrupciones",
        "duracion",
        "usuarios afectados",
        "mantenimiento",
    ]:
        _append_unique(terms, base)

    _append_unique(terms, selected.get("metric_mode"))
    _append_unique(terms, selected.get("circuito"))

    for value in hints.get("criticality_types") or []:
        _append_unique(terms, value)
    for value in hints.get("period_types") or []:
        _append_unique(terms, value)

    for key in [
        "dominant_causes",
        "dominant_event_families",
        "dominant_equipment",
        "dominant_circuits",
    ]:
        for value in hints.get(key) or []:
            _append_unique(terms, value)

    for key in ["top_causes", "top_event_families", "top_equipment", "top_circuits"]:
        for value in _collect_labels(points, key):
            _append_unique(terms, value)

    for point in points[:5]:
        for event in point.get("top_events") or []:
            if not isinstance(event, dict):
                continue
            for key in ("causa", "event_family", "circuito", "municipio", "equipo_ope", "tipo_equi_ope"):
                _append_unique(terms, event.get(key))

    return " ".join(terms[:40])
