from __future__ import annotations

from typing import Any

from chec_dashboard.core.config import Settings
from chec_dashboard.services.domain_rules_service import (
    variable_context_payload,
    variable_interactions_payload,
)


def _external_signals(payload: dict[str, Any]) -> dict[str, Any]:
    signals: dict[str, Any] = {}
    for point in payload.get("critical_points") or []:
        for key, value in (point.get("external_signals") or {}).items():
            if value not in (None, ""):
                signals[str(key)] = value
    return signals


def _workflow_step(step_id: str, label: str, status: str, summary: str) -> dict[str, str]:
    return {
        "step_id": step_id,
        "label": label,
        "status": status,
        "summary": summary,
    }


def _history_summary(payload: dict[str, Any]) -> str:
    history = payload.get("circuit_history_12m")
    if isinstance(history, dict) and history.get("available"):
        return (
            f"Historial 12 meses: {history.get('event_count', 0)} eventos, "
            f"UITI {history.get('aggregate_totals', {}).get('UITI', 0)}."
        )
    return "Historial anual insuficiente o no disponible; se usa la ventana seleccionada."


def build_agent_workflow(payload: dict[str, Any]) -> list[dict[str, str]]:
    has_selection = bool(payload.get("start_date") and payload.get("end_date") and payload.get("circuit_label"))
    has_points = bool(payload.get("critical_points"))
    variable_context = payload.get("variable_context") if isinstance(payload.get("variable_context"), dict) else {}
    interactions = payload.get("variable_interactions") if isinstance(payload.get("variable_interactions"), dict) else {}
    has_semantic_context = bool(variable_context.get("matched_variables") or interactions.get("matched_rules"))

    return [
        _workflow_step(
            "seleccion_circuito_periodo",
            "Paso 1: Seleccion de circuito y periodo",
            "completed" if has_selection else "partial",
            (
                f"Circuito {payload.get('circuit_label') or 'TODOS'} entre "
                f"{payload.get('start_date') or 'N/D'} y {payload.get('end_date') or 'N/D'}."
            ),
        ),
        _workflow_step(
            "identificacion_puntos_interes",
            "Paso 2: Identificacion de puntos de interes",
            "completed" if has_points else "partial",
            (
                f"Se detectaron {len(payload.get('critical_points') or [])} puntos criticos. "
                f"{_history_summary(payload)}"
            ),
        ),
        _workflow_step(
            "diagnostico_semantico",
            "Paso 3: Diagnostico semantico preliminar",
            "completed" if has_semantic_context else "partial",
            (
                "Analisis basado en descripciones de variables, modos e interacciones del contexto CHEC."
                if has_semantic_context
                else "No hubo coincidencias suficientes con el contexto de variables."
            ),
        ),
    ]


def attach_circuit_period_context(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    updated["analysis_focus"] = "circuit_period"
    updated["selected_event"] = None
    updated["corpus_citations"] = []
    signals = _external_signals(updated)
    updated["variable_context"] = variable_context_payload(
        settings,
        context_payload=updated,
        external_signals=signals,
    )
    updated["variable_interactions"] = variable_interactions_payload(
        settings,
        context_payload=updated,
        external_signals=signals,
    )
    updated["agent_workflow"] = build_agent_workflow(updated)
    return updated


def attach_event_centered_context(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    return attach_circuit_period_context(settings, payload)
