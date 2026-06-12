from __future__ import annotations

from typing import Any

from chec_dashboard.services.timeseries_interpretability.contracts import (
    Confidence,
    EvidenceMatrixRow,
    PointNarrative,
    TimeseriesInterpretabilityNarrative,
)


GROUP_LABELS = {
    "top_causes": "causa",
    "top_event_families": "familia de evento",
    "top_equipment": "equipo",
    "top_circuits": "circuito",
}


def _round_text(value: Any, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "0.000"


def _confidence(value: Any) -> Confidence:
    text = str(value or "medium").strip().lower()
    if text in {"high", "medium", "low"}:
        return text  # type: ignore[return-value]
    return "medium"


def _reason_details(point: dict[str, Any]) -> list[str]:
    details = [
        str(reason.get("detail")).strip()
        for reason in (point.get("reasons") or [])
        if isinstance(reason, dict) and str(reason.get("detail") or "").strip()
    ]
    if details:
        return details[:5]
    criticality = point.get("criticality_types") or []
    return [f"Tipo de criticidad calculado: {item}." for item in criticality[:5]]


def _driver_lines(point: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for group_key, group_label in GROUP_LABELS.items():
        values = point.get(group_key) or []
        if not values:
            continue
        first = values[0]
        if not isinstance(first, dict):
            continue
        label = str(first.get("label") or "Sin dato").strip()
        event_count = first.get("event_count", 0)
        contribution = first.get("contribution_pct")
        contribution_text = (
            f", aporte {_round_text(float(contribution) * 100, 1)}%"
            if contribution is not None
            else ""
        )
        lines.append(f"{label} domina como {group_label} con {event_count} eventos{contribution_text}.")
    return lines or ["No hay agrupacion dominante disponible en la atribucion estructurada."]


def _observed_values(point: dict[str, Any]) -> list[str]:
    metrics = point.get("metrics") or {}
    aggregates = point.get("daily_aggregates") or {}
    return [
        f"UITI={_round_text(metrics.get('UITI'))}",
        f"UITI_VANO={_round_text(metrics.get('UITI_VANO'))}",
        f"Eventos={aggregates.get('event_count', 0)}",
        f"Duracion_fuente={_round_text(aggregates.get('duration_raw_total'), 2)}",
        f"Usuarios_afectados={_round_text(aggregates.get('users_affected_total'), 0)}",
    ]


def _missing_evidence(point: dict[str, Any]) -> list[str]:
    flags = [str(flag) for flag in (point.get("data_quality_flags") or []) if str(flag).strip()]
    if point.get("confidence") == "low" and not flags:
        flags.append("low_confidence_without_explicit_quality_flag")
    return flags


def _recommended_checks(point: dict[str, Any]) -> list[str]:
    checks = [
        "Validar en campo la causa y el equipo dominante antes de cerrar una conclusion operativa.",
        "Cruzar el punto critico con bitacoras de interrupciones, normalizacion y cuadrillas.",
    ]
    if point.get("external_signals"):
        checks.append("Revisar si las senales ambientales coinciden temporalmente con los eventos principales.")
    if point.get("data_quality_flags"):
        checks.append("Resolver las banderas de datos antes de formular una explicacion mas fuerte.")
    return checks


def _evidence_rows(point: dict[str, Any]) -> list[EvidenceMatrixRow]:
    rows: list[EvidenceMatrixRow] = []
    fecha_dia = str(point.get("fecha_dia") or "")
    metrics = point.get("metrics") or {}
    aggregates = point.get("daily_aggregates") or {}
    rows.append(
        EvidenceMatrixRow(
            fecha_dia=fecha_dia,
            signal="Indicadores diarios",
            structured_evidence=(
                f"UITI={_round_text(metrics.get('UITI'))}; "
                f"UITI_VANO={_round_text(metrics.get('UITI_VANO'))}; "
                f"eventos={aggregates.get('event_count', 0)}."
            ),
            documentary_evidence="Sin soporte documental suficiente en narrativa deterministica.",
            confidence=_confidence(point.get("confidence")),
        )
    )
    for group_key, group_label in GROUP_LABELS.items():
        values = point.get(group_key) or []
        if not values:
            continue
        first = values[0]
        if isinstance(first, dict):
            rows.append(
                EvidenceMatrixRow(
                    fecha_dia=fecha_dia,
                    signal=f"Agrupacion por {group_label}",
                    structured_evidence=(
                        f"{first.get('label', 'Sin dato')} concentra "
                        f"{first.get('event_count', 0)} eventos."
                    ),
                    documentary_evidence="Sin soporte documental suficiente en narrativa deterministica.",
                    confidence=_confidence(point.get("confidence")),
                )
            )
    return rows


def build_deterministic_narrative(payload: dict[str, Any]) -> TimeseriesInterpretabilityNarrative:
    points = payload.get("critical_points") or []
    periods = payload.get("critical_periods") or []
    start_date = payload.get("start_date") or "N/D"
    end_date = payload.get("end_date") or "N/D"

    if not points:
        return TimeseriesInterpretabilityNarrative(
            source="deterministic",
            headline="No se detectaron puntos criticos bajo los umbrales actuales.",
            executive_summary=[
                (
                    f"La ventana {start_date} a {end_date} no presenta picos, cambios bruscos "
                    "o aportes concentrados bajo la configuracion actual."
                )
            ],
            limitations=[
                "La conclusion depende de los umbrales configurados y de la cobertura de datos disponible.",
                "No se incorporo interpretacion documental adicional.",
            ],
        )

    point_narratives: list[PointNarrative] = []
    evidence_matrix: list[EvidenceMatrixRow] = []
    for point in points:
        fecha_dia = str(point.get("fecha_dia") or "")
        point_narrative = PointNarrative(
            fecha_dia=fecha_dia,
            rank=int(point.get("rank") or 0),
            headline=f"Punto #{point.get('rank')} en {fecha_dia}",
            confidence=_confidence(point.get("confidence")),
            why_marked=_reason_details(point),
            observed_values=_observed_values(point),
            likely_drivers=_driver_lines(point),
            documentary_support=["Sin soporte documental suficiente en narrativa deterministica."],
            missing_evidence=_missing_evidence(point),
            recommended_checks=_recommended_checks(point),
        )
        point_narratives.append(point_narrative)
        evidence_matrix.extend(_evidence_rows(point))

    data_gaps = sorted(
        {
            str(flag)
            for point in points
            for flag in (point.get("data_quality_flags") or [])
            if str(flag).strip()
        }
    )
    first = point_narratives[0]
    return TimeseriesInterpretabilityNarrative(
        source="deterministic",
        headline=f"Se detectaron {len(points)} puntos criticos en la ventana seleccionada.",
        executive_summary=[
            payload.get("status_text")
            or f"Analisis deterministico de {start_date} a {end_date}.",
            f"El punto principal es {first.fecha_dia} con confianza {first.confidence}.",
        ],
        key_findings=[first.headline],
        point_narratives=point_narratives,
        period_narratives=[
            str(period.get("summary"))
            for period in periods
            if isinstance(period, dict) and str(period.get("summary") or "").strip()
        ],
        evidence_matrix=evidence_matrix[:10],
        data_gaps=data_gaps,
        recommended_actions=[
            "Priorizar la revision de los eventos y agrupaciones dominantes de los puntos de mayor rango.",
            "Confirmar causa, equipo y circuito con registros operativos antes de afirmar causalidad.",
        ],
        limitations=[
            "Narrativa generada sin interpretacion documental adicional.",
            "El LLM no es fuente de verdad para fechas, valores, criticidad ni atribucion.",
        ],
    )


def flatten_narrative_to_text(narrative: TimeseriesInterpretabilityNarrative | dict[str, Any] | None) -> str:
    if narrative is None:
        return ""
    if isinstance(narrative, dict):
        try:
            narrative = TimeseriesInterpretabilityNarrative.model_validate(narrative)
        except Exception:
            return str(narrative.get("headline") or "")

    sections: list[str] = [narrative.headline]
    sections.extend(narrative.executive_summary[:3])
    if narrative.key_findings:
        sections.append("Hallazgos: " + " ".join(narrative.key_findings[:3]))
    for point in narrative.point_narratives[:3]:
        parts = [point.headline]
        if point.observed_values:
            parts.append("; ".join(point.observed_values[:5]))
        if point.likely_drivers:
            parts.append("Drivers: " + " ".join(point.likely_drivers[:2]))
        if point.missing_evidence:
            parts.append("Datos faltantes: " + ", ".join(point.missing_evidence[:3]))
        sections.append(". ".join(parts))
    if narrative.data_gaps:
        sections.append("Datos faltantes: " + ", ".join(narrative.data_gaps[:5]))
    if narrative.recommended_actions:
        sections.append("Recomendaciones: " + " ".join(narrative.recommended_actions[:3]))
    if narrative.limitations:
        sections.append("Limitaciones: " + " ".join(narrative.limitations[:2]))
    return "\n\n".join(str(section).strip() for section in sections if str(section).strip())
