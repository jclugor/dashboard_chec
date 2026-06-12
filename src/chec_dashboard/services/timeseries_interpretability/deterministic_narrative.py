from __future__ import annotations

from typing import Any

from chec_dashboard.services.timeseries_interpretability.contracts import (
    Confidence,
    EvidenceMatrixRow,
    PeriodFinding,
    ReferencedEvent,
    TimeseriesInterpretabilityNarrative,
)


GROUP_LABELS = {
    "top_causes": ("Evento/Impacto", "causa"),
    "top_event_families": ("Proteccion", "familia de evento"),
    "top_equipment": ("Proteccion", "equipo"),
    "top_circuits": ("Topologia", "circuito"),
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


def _metric_key(payload: dict[str, Any]) -> str:
    return str(payload.get("metric_key") or "UITI").strip().upper() or "UITI"


def _metric_value(point: dict[str, Any], metric_key: str) -> Any:
    metrics = point.get("metrics") or {}
    return metrics.get(metric_key) if metric_key in metrics else metrics.get("UITI")


def _selection_reason(point: dict[str, Any]) -> str:
    explicit = str(point.get("selection_reason") or "").strip()
    if explicit:
        return explicit
    details = [
        str(reason.get("detail")).strip()
        for reason in (point.get("reasons") or [])
        if isinstance(reason, dict) and str(reason.get("detail") or "").strip()
    ]
    if details:
        return " ".join(details[:2])
    criticality = [str(item) for item in point.get("criticality_types") or [] if str(item).strip()]
    if criticality:
        return "Seleccionado por tipos de criticidad calculados: " + ", ".join(criticality[:4]) + "."
    return "Seleccionado por el detector de puntos de interes del periodo analizado."


def _referenced_event(point: dict[str, Any], metric_key: str) -> ReferencedEvent:
    return ReferencedEvent(
        date=str(point.get("fecha_dia") or ""),
        indicator_value=_metric_value(point, metric_key),
        selection_reason=_selection_reason(point),
    )


def _event_reference(point: dict[str, Any], metric_key: str) -> str:
    return (
        f"{point.get('fecha_dia')}: {metric_key}={_round_text(_metric_value(point, metric_key))}; "
        f"{_selection_reason(point)}"
    )


def _trend_change_text(point: dict[str, Any], metric_key: str) -> str:
    metrics = point.get("metrics") or {}
    key = metric_key.lower()
    delta = metrics.get(f"{key}_delta_1d")
    robust_z = metrics.get(f"{key}_robust_z")
    contribution = metrics.get(f"{key}_contribution_pct")
    parts: list[str] = []
    try:
        numeric_delta = float(delta)
        if numeric_delta > 0:
            parts.append(f"aumento frente al evento/dia previo de {_round_text(numeric_delta)}")
        elif numeric_delta < 0:
            parts.append(f"descenso frente al evento/dia previo de {_round_text(numeric_delta)}")
    except (TypeError, ValueError):
        pass
    if robust_z is not None:
        parts.append(f"desviacion robusta {_round_text(robust_z, 2)}")
    if contribution is not None:
        parts.append(f"aporte {_round_text(float(contribution) * 100, 1)}% del periodo")
    return "; ".join(parts) if parts else "cambio relativo calculado por el detector de criticidad"


def _available_group_labels(point: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    if point.get("metrics") or point.get("daily_aggregates") or point.get("top_events") or point.get("top_causes"):
        labels.append("Evento/Impacto")
    if point.get("top_equipment") or point.get("top_event_families"):
        labels.append("Proteccion")
    if point.get("top_circuits"):
        labels.append("Topologia")
    if point.get("external_signals"):
        labels.append("Entorno/Riesgo")
    return labels


def _payload_group_labels(payload: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for point in payload.get("critical_points") or []:
        labels.extend(_available_group_labels(point))
    context = payload.get("variable_context") if isinstance(payload.get("variable_context"), dict) else {}
    for mode in context.get("matched_modes") or []:
        if not isinstance(mode, dict):
            continue
        label = str(mode.get("label") or "")
        if "Fisicas" in label or "Electricas" in label:
            labels.append("Fisicas/Electricas")
        elif "Activos" in label:
            labels.append("Activos")
        elif "Entorno" in label or "Clima" in label:
            labels.append("Entorno/Riesgo")
        elif "Topologia" in label:
            labels.append("Topologia")
        elif "Proteccion" in label:
            labels.append("Proteccion")
        elif "Evento" in label or "Indicadores" in label:
            labels.append("Evento/Impacto")
    ordered = [
        "Evento/Impacto",
        "Proteccion",
        "Topologia",
        "Fisicas/Electricas",
        "Activos",
        "Entorno/Riesgo",
    ]
    return [label for label in ordered if label in set(labels)]


def _driver_lines(point: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for group_key, (_, group_label) in GROUP_LABELS.items():
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
        lines.append(f"{label} concentra {event_count} eventos como {group_label}{contribution_text}.")
    return lines


def _impact_text(points: list[dict[str, Any]], metric_key: str) -> str:
    totals = {"events": 0, "duration": 0.0, "users": 0.0}
    for point in points:
        aggregates = point.get("daily_aggregates") or {}
        totals["events"] += int(aggregates.get("event_count") or 0)
        try:
            totals["duration"] += float(aggregates.get("duration_raw_total") or 0)
        except (TypeError, ValueError):
            pass
        try:
            totals["users"] += float(aggregates.get("users_affected_total") or 0)
        except (TypeError, ValueError):
            pass
    return (
        f"En los eventos seleccionados, {metric_key} se interpreta junto con duracion y usuarios "
        f"afectados: {totals['events']} eventos, duracion acumulada {_round_text(totals['duration'], 2)} "
        f"y usuarios afectados {_round_text(totals['users'], 0)}. Esta relacion es coherente con la "
        "logica de impacto donde mayor duracion y mayor cantidad de usuarios elevan el indicador."
    )


def _evidence_rows(points: list[dict[str, Any]], metric_key: str) -> list[EvidenceMatrixRow]:
    rows: list[EvidenceMatrixRow] = []
    for point in points:
        fecha_dia = str(point.get("fecha_dia") or "")
        aggregates = point.get("daily_aggregates") or {}
        rows.append(
            EvidenceMatrixRow(
                fecha_dia=fecha_dia,
                signal="Evento critico seleccionado",
                structured_evidence=(
                    f"{metric_key}={_round_text(_metric_value(point, metric_key))}; "
                    f"eventos={aggregates.get('event_count', 0)}; "
                    f"razon={_selection_reason(point)}"
                ),
                domain_evidence="UITI se relaciona con duracion y usuarios afectados.",
                documentary_evidence=None,
                confidence=_confidence(point.get("confidence")),
            )
        )
    return rows[:10]


def _finding(
    title: str,
    text: str,
    *,
    events: list[ReferencedEvent] | None = None,
    groups: list[str] | None = None,
) -> PeriodFinding:
    return PeriodFinding(
        title=title,
        text=text,
        referenced_events=events or [],
        variable_groups_used=groups or [],
    )


def build_deterministic_narrative(payload: dict[str, Any]) -> TimeseriesInterpretabilityNarrative:
    metric_key = _metric_key(payload)
    points = sorted(payload.get("critical_points") or [], key=lambda item: str(item.get("fecha_dia") or ""))
    periods = payload.get("critical_periods") or []
    start_date = payload.get("start_date") or "N/D"
    end_date = payload.get("end_date") or "N/D"
    circuit = payload.get("circuit_label") or "TODOS"

    if not points:
        return TimeseriesInterpretabilityNarrative(
            source="deterministic",
            headline="Analisis temporal del indicador sin puntos criticos seleccionados.",
            section_title="Hallazgos del periodo",
            executive_summary=[
                (
                    f"Para el circuito {circuit}, el periodo analizado entre {start_date} y {end_date} "
                    "no tiene eventos seleccionados como puntos de interes bajo los umbrales actuales."
                )
            ],
            key_findings=[
                _finding(
                    "Comportamiento sin eventos criticos seleccionados",
                    (
                        "El analisis se concentra en los eventos disponibles del periodo. Los intervalos "
                        "sin evento registrado no se interpretan como anomalias por si mismos."
                    ),
                    groups=["Evento/Impacto"],
                )
            ],
            period_synthesis=(
                "No se formula una hipotesis operativa especifica porque el detector no selecciono "
                "eventos criticos para sintetizar."
            ),
        )

    referenced_events = [_referenced_event(point, metric_key) for point in points]
    event_text = " ".join(_event_reference(point, metric_key) for point in points)
    group_labels = _payload_group_labels(payload) or ["Evento/Impacto"]
    strongest = max(points, key=lambda point: float(point.get("criticality_score") or 0))
    strongest_date = str(strongest.get("fecha_dia") or "")

    findings: list[PeriodFinding] = [
        _finding(
            "Comportamiento general del periodo",
            (
                f"Durante el periodo analizado para el circuito {circuit}, el indicador {metric_key} "
                f"concentra sus principales variaciones en {len(points)} eventos seleccionados. "
                f"Estos eventos se usan como evidencia del comportamiento temporal: {event_text}"
            ),
            events=referenced_events,
            groups=["Evento/Impacto"],
        ),
        _finding(
            "Cambios frente a la tendencia cercana",
            (
                "Los eventos seleccionados no se interpretan como bloques aislados: se leen por su "
                "ruptura o aporte frente al comportamiento cercano. "
                + " ".join(
                    f"El {point.get('fecha_dia')} muestra {_trend_change_text(point, metric_key)}."
                    for point in points
                )
            ),
            events=referenced_events,
            groups=["Evento/Impacto"],
        ),
        _finding(
            "Impacto operacional",
            _impact_text(points, metric_key),
            events=referenced_events,
            groups=["Evento/Impacto"],
        ),
    ]

    driver_lines = [line for point in points for line in _driver_lines(point)]
    if driver_lines:
        findings.append(
            _finding(
                "Variables que explican el comportamiento",
                (
                    "Las agrupaciones disponibles ayudan a contextualizar la evolucion del indicador: "
                    + " ".join(driver_lines[:10])
                ),
                events=referenced_events,
                groups=[label for label in group_labels if label in {"Evento/Impacto", "Proteccion", "Topologia"}],
            )
        )

    if "Entorno/Riesgo" in group_labels:
        signal_names = sorted(
            {
                str(key)
                for point in points
                for key in (point.get("external_signals") or {}).keys()
                if str(key).strip()
            }
        )
        findings.append(
            _finding(
                "Entorno y riesgo",
                (
                    "Las senales ambientales disponibles se tratan como estresores contextuales, "
                    "no como causas definitivas. "
                    + (f"Variables observadas: {', '.join(signal_names[:12])}." if signal_names else "")
                ),
                events=referenced_events,
                groups=["Entorno/Riesgo"],
            )
        )

    if any(label in group_labels for label in ("Fisicas/Electricas", "Activos")):
        used = [label for label in ("Fisicas/Electricas", "Activos") if label in group_labels]
        findings.append(
            _finding(
                "Susceptibilidad de activos",
                (
                    "Las variables fisicas, electricas y de activos se usan como contexto de "
                    "susceptibilidad y exposicion. No se convierten en causa unica salvo que los "
                    "eventos y las etiquetas operativas lo respalden."
                ),
                events=referenced_events,
                groups=used,
            )
        )

    findings.append(
        _finding(
            "Hipotesis de sintesis",
            (
                f"La lectura consolidada sugiere que el comportamiento de {metric_key} en {circuit} "
                f"esta dominado por el evento de mayor criticidad del {strongest_date}, pero su "
                "interpretacion depende del patron completo de eventos seleccionados, su duracion, "
                "usuarios afectados y contexto operativo disponible."
            ),
            events=[_referenced_event(strongest, metric_key)],
            groups=group_labels,
        )
    )

    period_narratives = [
        str(period.get("summary"))
        for period in periods
        if isinstance(period, dict) and str(period.get("summary") or "").strip()
    ]
    synthesis = (
        f"El periodo analizado contiene {len(points)} eventos de interes para {metric_key}; "
        "la explicacion se mantiene descriptiva y apoyada en datos estructurados."
    )
    return TimeseriesInterpretabilityNarrative(
        source="deterministic",
        headline=f"Analisis temporal consolidado de {metric_key} para {circuit}.",
        section_title="Hallazgos del periodo",
        executive_summary=[
            payload.get("status_text")
            or f"Analisis deterministico del periodo {start_date} a {end_date}.",
            synthesis,
        ],
        key_findings=findings[:8],
        period_synthesis=synthesis,
        period_narratives=period_narratives,
        evidence_matrix=_evidence_rows(points, metric_key),
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
        sections.append(narrative.section_title or "Hallazgos del periodo")
        for finding in narrative.key_findings:
            event_bits = [
                f"{event.date} ({event.indicator_value}; {event.selection_reason})"
                for event in finding.referenced_events
                if event.date or event.indicator_value is not None or event.selection_reason
            ]
            event_text = " Eventos: " + "; ".join(event_bits) if event_bits else ""
            sections.append(f"{finding.title}: {finding.text}{event_text}")
    elif narrative.point_narratives:
        for point in narrative.point_narratives:
            sections.append(f"{point.headline}: {' '.join(point.why_marked + point.likely_drivers)}")
    if narrative.period_synthesis:
        sections.append(narrative.period_synthesis)
    if narrative.period_narratives:
        sections.extend(narrative.period_narratives[:3])
    return "\n\n".join(str(section).strip() for section in sections if str(section).strip())
