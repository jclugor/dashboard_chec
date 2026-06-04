from __future__ import annotations

from datetime import date
from typing import Any

from dash import Dash, Input, Output, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate
import pandas as pd
import plotly.graph_objects as go

from chec_dashboard.config import Settings
from chec_dashboard.dash_app.api_client import (
    fetch_summary_data,
    fetch_summary_interpretability,
    fetch_summary_options,
)


CHEC_GREEN = "#00782b"
CHEC_BUTTON_GREEN = "#11BB52CF"
SUMMARY_INITIAL_INTERVAL_MS = 250
SUMMARY_PLACEHOLDER_TEXT = "Cargando resumen del circuito..."
_OVERLAY_HIDDEN_STYLE = {"display": "none"}
_OVERLAY_VISIBLE_STYLE = {"display": "flex"}
INTERPRETABILITY_PLACEHOLDER = "Solicita el analisis para marcar y explicar puntos criticos."


def _empty_figure(message: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        showarrow=False,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        font={"size": 16, "color": "#014719"},
    )
    fig.update_layout(
        template="plotly_white",
        margin={"l": 30, "r": 20, "t": 20, "b": 30},
        xaxis={"visible": False},
        yaxis={"visible": False},
    )
    return fig


def _build_chart_title(metric_mode: str, circuito: str, start_date: date, end_date: date) -> str:
    metric_label = {
        "BOTH": "SAIDI/SAIFI",
    }.get(metric_mode, metric_mode)
    return (
        f"Tendencia diaria de {metric_label} para {circuito} "
        f"({start_date.isoformat()} a {end_date.isoformat()})"
    )


def _build_line_figure(
    daily_data: pd.DataFrame,
    metric_mode: str,
) -> go.Figure:
    fig = go.Figure()
    if metric_mode in ("SAIDI", "BOTH"):
        fig.add_trace(
            go.Scatter(
                x=daily_data["fecha_dia"],
                y=daily_data["SAIDI"],
                mode="lines",
                name="SAIDI",
                line={"color": "#00782b", "width": 2},
            )
        )
    if metric_mode in ("SAIFI", "BOTH"):
        fig.add_trace(
            go.Scatter(
                x=daily_data["fecha_dia"],
                y=daily_data["SAIFI"],
                mode="lines",
                name="SAIFI",
                line={"color": "#16D622", "width": 2},
            )
        )

    fig.update_layout(
        template="plotly_white",
        margin={"l": 40, "r": 20, "t": 14, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        hovermode="x unified",
    )
    fig.update_xaxes(title_text="Fecha")
    fig.update_yaxes(title_text="Valor diario (suma)")
    return fig


def _reason_label(reason_type: str) -> str:
    labels = {
        "saidi_high_outlier": "Pico SAIDI",
        "saifi_high_outlier": "Pico SAIFI",
        "saidi_low_outlier": "Bajo SAIDI",
        "saifi_low_outlier": "Bajo SAIFI",
        "sharp_saidi_increase": "Subida SAIDI",
        "sharp_saifi_increase": "Subida SAIFI",
        "sharp_saidi_decrease": "Bajada SAIDI",
        "sharp_saifi_decrease": "Bajada SAIFI",
        "top_saidi_contributor": "Alto aporte SAIDI",
        "top_saifi_contributor": "Alto aporte SAIFI",
        "local_saidi_peak": "Pico local SAIDI",
        "local_saifi_peak": "Pico local SAIFI",
        "saidi_saifi_divergence": "Divergencia",
    }
    return labels.get(reason_type, reason_type.replace("_", " "))


def _format_number(value: Any, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "0.000"


def _apply_interpretability_markers(
    figure: go.Figure,
    interpretability_payload: dict[str, Any] | None,
    metric_mode: str,
) -> go.Figure:
    if not interpretability_payload:
        return figure
    points = interpretability_payload.get("critical_points") or []
    if not points:
        return figure
    active_metrics = ("SAIDI", "SAIFI") if metric_mode == "BOTH" else (metric_mode,)
    marker_styles = {
        "SAIDI": {"color": "#d9471a", "symbol": "diamond"},
        "SAIFI": {"color": "#2f5fb3", "symbol": "circle"},
    }
    for metric in active_metrics:
        x_values: list[str] = []
        y_values: list[float] = []
        hover_values: list[str] = []
        for point in points:
            metrics = point.get("metrics") or {}
            value = metrics.get(metric)
            if value is None:
                continue
            x_values.append(str(point.get("fecha_dia")))
            y_values.append(float(value))
            reason_text = ", ".join(_reason_label(item) for item in point.get("criticality_types", [])[:4])
            hover_values.append(
                f"Rango {point.get('rank')}<br>{reason_text}<br>"
                f"Confianza: {point.get('confidence', 'medium')}"
            )
        if not x_values:
            continue
        style = marker_styles.get(metric, marker_styles["SAIDI"])
        figure.add_trace(
            go.Scatter(
                x=x_values,
                y=y_values,
                mode="markers",
                name=f"Puntos criticos {metric}",
                marker={
                    "color": style["color"],
                    "symbol": style["symbol"],
                    "size": 11,
                    "line": {"color": "white", "width": 1.5},
                },
                hovertemplate="%{x}<br>%{y:.4f}<br>%{text}<extra></extra>",
                text=hover_values,
            )
        )
    return figure


def _interpretability_empty_panel(message: str = INTERPRETABILITY_PLACEHOLDER) -> html.Div:
    return html.Div(
        className="summary-interpretability-panel summary-interpretability-empty",
        children=[
            html.Div("Interpretabilidad de la evolucion", className="summary-interpretability-title"),
            html.Div(message, className="summary-interpretability-text"),
        ],
    )


def _interpretability_error_panel(message: str) -> html.Div:
    return html.Div(
        className="summary-interpretability-panel summary-interpretability-error",
        children=[
            html.Div("No fue posible analizar la evolucion", className="summary-interpretability-title"),
            html.Div(message, className="summary-interpretability-text"),
        ],
    )


def _attribution_line(point: dict[str, Any]) -> str:
    for key in ("top_causes", "top_event_families", "top_equipment", "top_circuits"):
        values = point.get(key) or []
        if values:
            first = values[0]
            return f"{first.get('label')} | eventos: {first.get('event_count', 0)}"
    return "Sin agrupacion dominante disponible"


def _critical_point_card(point: dict[str, Any]) -> html.Div:
    metrics = point.get("metrics") or {}
    aggregates = point.get("daily_aggregates") or {}
    reason_text = ", ".join(_reason_label(item) for item in point.get("criticality_types", [])[:4])
    return html.Div(
        className="summary-critical-point-card",
        children=[
            html.Div(
                [
                    html.Span(f"#{point.get('rank')}"),
                    html.Span(str(point.get("fecha_dia"))),
                    html.Span(str(point.get("confidence", "medium")).upper()),
                ],
                className="summary-critical-point-header",
            ),
            html.Div(
                f"SAIDI {_format_number(metrics.get('SAIDI'))} | SAIFI {_format_number(metrics.get('SAIFI'))}",
                className="summary-critical-point-metrics",
            ),
            html.Div(reason_text or "Punto critico", className="summary-critical-point-reasons"),
            html.Div(
                (
                    f"Eventos {aggregates.get('event_count', 0)} | "
                    f"Duracion {aggregates.get('duration_total_h', 0)} h | "
                    f"Usuarios {aggregates.get('users_affected_total', 0)}"
                ),
                className="summary-critical-point-aggregates",
            ),
            html.Div(_attribution_line(point), className="summary-critical-point-attribution"),
        ],
    )


def _interpretability_panel_from_payload(payload: dict[str, Any] | None) -> html.Div:
    if not payload:
        return _interpretability_empty_panel()
    points = payload.get("critical_points") or []
    if not points:
        return _interpretability_empty_panel(str(payload.get("status_text") or "No se detectaron puntos criticos."))
    return html.Div(
        className="summary-interpretability-panel",
        children=[
            html.Div(
                [
                    html.Div("Interpretabilidad de la evolucion", className="summary-interpretability-title"),
                    html.Div(str(payload.get("status_text") or ""), className="summary-interpretability-status"),
                ],
                className="summary-interpretability-header",
            ),
            html.Div(str(payload.get("insight_text") or ""), className="summary-interpretability-text"),
            html.Div(
                [_critical_point_card(point) for point in points],
                className="summary-critical-point-grid",
            ),
        ],
    )


def _kpi_card(card_id: str, title: str, initial_value: str = "--") -> html.Div:
    return html.Div(
        className="summary-kpi-card",
        style={
            "backgroundColor": "white",
            "borderRadius": "10px",
            "display": "flex",
            "flexDirection": "column",
            "justifyContent": "center",
            "alignItems": "center",
        },
        children=[
            html.Div(
                title,
                className="summary-kpi-title",
                style={
                    "fontFamily": "'DM Sans', sans-serif",
                    "fontWeight": "700",
                    "color": CHEC_GREEN,
                    "marginBottom": "4px",
                },
            ),
            html.Div(
                id=card_id,
                className="summary-kpi-value",
                style={
                    "fontFamily": "'DM Sans', sans-serif",
                    "fontWeight": "700",
                    "color": "#014719",
                },
                children=initial_value,
            ),
        ],
    )


def _to_date(value: str | None) -> date | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _normalize_daily_data(payload: dict[str, object]) -> pd.DataFrame:
    daily_data = pd.DataFrame(payload.get("daily_data", []))
    if daily_data.empty:
        return pd.DataFrame(columns=["fecha_dia", "SAIDI", "SAIFI"])

    daily_data["fecha_dia"] = pd.to_datetime(daily_data["fecha_dia"], errors="coerce")
    daily_data["SAIDI"] = pd.to_numeric(daily_data["SAIDI"], errors="coerce").fillna(0.0)
    daily_data["SAIFI"] = pd.to_numeric(daily_data["SAIFI"], errors="coerce").fillna(0.0)
    return daily_data


def _summary_visuals_from_payload(
    payload: dict[str, object],
    *,
    fallback_metric_mode: str,
    fallback_circuit: str,
) -> tuple[str, str, str, go.Figure, str, str]:
    daily_data = _normalize_daily_data(payload)
    metric_mode = str(payload.get("metric_mode", fallback_metric_mode or "BOTH"))
    circuit_label = str(payload.get("circuit_label", fallback_circuit or "TODOS"))
    start_date = _to_date(payload.get("start_date")) or date.today()
    end_date = _to_date(payload.get("end_date")) or start_date
    figure = _build_line_figure(daily_data=daily_data, metric_mode=metric_mode)
    title = _build_chart_title(metric_mode, circuit_label, start_date, end_date)
    status_text = str(payload.get("status_text", "Sin información disponible."))
    event_count = int(payload.get("event_count", 0))
    saidi_total = float(payload.get("saidi_total", 0.0))
    saifi_total = float(payload.get("saifi_total", 0.0))
    return (
        f"{saidi_total:.4f}",
        f"{saifi_total:.4f}",
        f"{event_count}",
        figure,
        title,
        status_text,
    )


def get_layout(settings: Settings) -> html.Div:
    _ = settings
    initial_figure = _empty_figure(SUMMARY_PLACEHOLDER_TEXT)

    return html.Div(
        [
            dcc.Interval(
                id="summary-initial-load-interval",
                interval=SUMMARY_INITIAL_INTERVAL_MS,
                n_intervals=0,
                max_intervals=1,
                disabled=False,
            ),
            dcc.Store(id="summary-interpretability-store"),
            html.Div(
                className="summary-filter-panel",
                style={
                    "background": "rgba(0, 120, 43, 0.76)",
                },
                children=[
                    html.Div(
                        "VENTANA DE TIEMPO",
                        className="summary-filter-label",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontWeight": "700",
                            "color": "white",
                        },
                    ),
                    html.Div(
                        className="summary-filter-input summary-filter-date",
                        style={
                            "backgroundColor": "white",
                            "padding": "4px 8px",
                        },
                        children=[
                            dcc.DatePickerRange(
                                id="summary-date-window",
                                min_date_allowed=None,
                                max_date_allowed=None,
                                start_date=None,
                                end_date=None,
                                display_format="YYYY-MM-DD",
                                disabled=True,
                            )
                        ],
                    ),
                    html.Div(
                        "CIRCUITO",
                        className="summary-filter-label",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontWeight": "700",
                            "color": "white",
                        },
                    ),
                    html.Div(
                        className="summary-filter-input summary-filter-circuit",
                        style={"backgroundColor": "white"},
                        children=[
                            dcc.Dropdown(
                                id="summary-circuit",
                                className="summary-select-dropdown",
                                options=[],
                                value=None,
                                placeholder="Selecciona circuito",
                                searchable=True,
                                disabled=True,
                                maxHeight=180,
                                style={
                                    "border": "none",
                                    "color": CHEC_GREEN,
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontSize": "18px",
                                },
                            )
                        ],
                    ),
                    html.Div(
                        "MÉTRICA",
                        className="summary-filter-label",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontWeight": "700",
                            "color": "white",
                        },
                    ),
                    html.Div(
                        className="summary-filter-input summary-filter-metric",
                        style={"backgroundColor": "white"},
                        children=[
                            dcc.Dropdown(
                                id="summary-metric-mode",
                                className="summary-select-dropdown",
                                options=[
                                    {"label": "SAIDI", "value": "SAIDI"},
                                    {"label": "SAIFI", "value": "SAIFI"},
                                    {"label": "Ambos", "value": "BOTH"},
                                ],
                                value="BOTH",
                                clearable=False,
                                style={
                                    "border": "none",
                                    "color": CHEC_GREEN,
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontSize": "18px",
                                },
                            )
                        ],
                    ),
                ],
            ),
            html.Div(
                className="summary-main-card",
                style={
                    "background": "rgba(45, 154, 35, 0.8)",
                    "position": "relative",
                },
                children=[
                    html.Div(
                        id="summary-panel-overlay",
                        className="panel-loading-overlay",
                        style=_OVERLAY_HIDDEN_STYLE,
                        children=[
                            html.Div(
                                "Actualizando resumen...",
                                className="panel-loading-overlay-text",
                            )
                        ],
                    ),
                    html.Div(
                        "Resumen rápido SAIDI/SAIFI por circuito",
                        className="summary-main-title",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontWeight": "700",
                            "color": "white",
                        },
                    ),
                    html.Div(
                        className="summary-kpi-row",
                        children=[
                            _kpi_card("summary-kpi-saidi", "Total SAIDI"),
                            _kpi_card("summary-kpi-saifi", "Total SAIFI"),
                            _kpi_card("summary-kpi-events", "Eventos"),
                        ],
                    ),
                    html.Div(
                        id="summary-chart-title",
                        className="summary-chart-title",
                        children="Tendencia diaria del indicador seleccionado.",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontWeight": "700",
                            "color": "white",
                        },
                    ),
                    html.Div(
                        className="summary-chart-actions",
                        children=[
                            html.Button(
                                "Analizar evolución",
                                id="summary-interpretability-button",
                                n_clicks=0,
                                className="summary-interpretability-button",
                                style={
                                    "backgroundColor": "white",
                                    "color": CHEC_GREEN,
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontWeight": "700",
                                },
                            )
                        ],
                    ),
                    html.Div(
                        className="summary-chart-container",
                        style={
                            "backgroundColor": "white",
                            "padding": "8px",
                        },
                        children=[
                            dcc.Graph(
                                id="summary-line-chart",
                                figure=initial_figure,
                                style={"height": "100%"},
                                config={"displayModeBar": True, "responsive": True},
                            )
                        ],
                    ),
                    html.Div(
                        id="summary-interpretability-panel",
                        children=_interpretability_empty_panel(),
                    ),
                ],
            ),
            html.Div(
                id="summary-status-text",
                className="summary-status-text",
                children="Preparando filtros y resumen...",
                style={
                    "color": "#014719",
                    "fontFamily": "'DM Sans', sans-serif",
                    "fontWeight": "700",
                    "fontSize": "14px",
                },
            ),
        ],
        className="summary-page",
        style={"width": "100%", "display": "flex", "flexDirection": "column", "alignItems": "center"},
    )


def register_callbacks(app: Dash, settings: Settings) -> None:
    _ = settings

    @app.callback(
        Output("summary-date-window", "min_date_allowed"),
        Output("summary-date-window", "max_date_allowed"),
        Output("summary-date-window", "start_date"),
        Output("summary-date-window", "end_date"),
        Output("summary-date-window", "disabled"),
        Output("summary-circuit", "options"),
        Output("summary-circuit", "value"),
        Output("summary-circuit", "disabled"),
        Output("summary-kpi-saidi", "children"),
        Output("summary-kpi-saifi", "children"),
        Output("summary-kpi-events", "children"),
        Output("summary-line-chart", "figure"),
        Output("summary-chart-title", "children"),
        Output("summary-status-text", "children"),
        Output("summary-interpretability-store", "data"),
        Output("summary-interpretability-panel", "children"),
        Output("summary-initial-load-interval", "disabled"),
        Input("summary-initial-load-interval", "n_intervals"),
        Input("summary-date-window", "start_date"),
        Input("summary-date-window", "end_date"),
        Input("summary-circuit", "value"),
        Input("summary-metric-mode", "value"),
        Input("summary-interpretability-button", "n_clicks"),
        prevent_initial_call=True,
        running=[
            (Output("summary-panel-overlay", "style"), _OVERLAY_VISIBLE_STYLE, _OVERLAY_HIDDEN_STYLE),
        ],
    )
    def update_summary(
        n_intervals: int | None,
        start_date_raw: str | None,
        end_date_raw: str | None,
        circuito: str | None,
        metric_mode: str | None,
        interpretability_clicks: int | None,
    ):
        triggered_id = ctx.triggered_id
        metric_mode = metric_mode or "BOTH"

        if triggered_id == "summary-initial-load-interval":
            if n_intervals is None:
                raise PreventUpdate
            try:
                options_payload = fetch_summary_options()
                circuits = options_payload.get("circuits", [])
                default_circuit = options_payload.get("default_circuit") or (circuits[0] if circuits else None)
                min_date = options_payload.get("min_date")
                max_date = options_payload.get("max_date")
                default_start = options_payload.get("default_start")
                default_end = options_payload.get("default_end")
                summary_payload = fetch_summary_data(
                    start_date_raw=default_start,
                    end_date_raw=default_end,
                    circuito=default_circuit,
                    metric_mode=metric_mode,
                )
                saidi, saifi, events, figure, title, status = _summary_visuals_from_payload(
                    summary_payload,
                    fallback_metric_mode=metric_mode,
                    fallback_circuit=default_circuit or "TODOS",
                )
                return (
                    min_date,
                    max_date,
                    default_start,
                    default_end,
                    False,
                    circuits,
                    default_circuit,
                    False,
                    saidi,
                    saifi,
                    events,
                    figure,
                    title,
                    status,
                    None,
                    _interpretability_empty_panel(),
                    True,
                )
            except Exception as exc:
                message = str(exc)
                return (
                    None,
                    None,
                    None,
                    None,
                    True,
                    [],
                    None,
                    True,
                    "--",
                    "--",
                    "--",
                    _empty_figure(message),
                    "Tendencia diaria del indicador seleccionado.",
                    message,
                    None,
                    _interpretability_error_panel(message),
                    True,
                )

        if not start_date_raw or not end_date_raw:
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                "--",
                "--",
                "--",
                _empty_figure("Selecciona una ventana de tiempo válida."),
                "Tendencia diaria del indicador seleccionado.",
                "Selecciona una ventana de tiempo válida.",
                None,
                _interpretability_empty_panel("Selecciona una ventana de tiempo valida."),
                no_update,
            )

        try:
            payload = fetch_summary_data(start_date_raw, end_date_raw, circuito, metric_mode)
            saidi, saifi, events, figure, title, status = _summary_visuals_from_payload(
                payload,
                fallback_metric_mode=metric_mode,
                fallback_circuit=circuito or "TODOS",
            )
            interpretability_payload = None
            interpretability_panel = _interpretability_empty_panel()
            if triggered_id == "summary-interpretability-button" and interpretability_clicks:
                try:
                    interpretability_payload = fetch_summary_interpretability(
                        start_date_raw=start_date_raw,
                        end_date_raw=end_date_raw,
                        circuito=circuito,
                        metric_mode=metric_mode,
                        max_points=settings.summary_interpretability_max_points,
                        include_agent_text=None,
                    )
                    figure = _apply_interpretability_markers(
                        figure,
                        interpretability_payload,
                        str(interpretability_payload.get("metric_mode", metric_mode)),
                    )
                    interpretability_panel = _interpretability_panel_from_payload(interpretability_payload)
                except Exception as exc:
                    interpretability_panel = _interpretability_error_panel(str(exc))
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                saidi,
                saifi,
                events,
                figure,
                title,
                status,
                interpretability_payload,
                interpretability_panel,
                no_update,
            )
        except Exception as exc:
            message = str(exc)
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                "--",
                "--",
                "--",
                _empty_figure(message),
                "Tendencia diaria del indicador seleccionado.",
                message,
                None,
                _interpretability_error_panel(message),
                no_update,
            )
