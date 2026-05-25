from __future__ import annotations

from datetime import date

from dash import Dash, Input, Output, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate
import pandas as pd
import plotly.graph_objects as go

from chec_dashboard.config import Settings
from chec_dashboard.dash_app.api_client import fetch_summary_data, fetch_summary_options


CHEC_GREEN = "#00782b"
CHEC_BUTTON_GREEN = "#11BB52CF"
SUMMARY_INITIAL_INTERVAL_MS = 250
SUMMARY_PLACEHOLDER_TEXT = "Cargando resumen del circuito..."
_OVERLAY_HIDDEN_STYLE = {"display": "none"}
_OVERLAY_VISIBLE_STYLE = {"display": "flex"}


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
        Output("summary-initial-load-interval", "disabled"),
        Input("summary-initial-load-interval", "n_intervals"),
        Input("summary-date-window", "start_date"),
        Input("summary-date-window", "end_date"),
        Input("summary-circuit", "value"),
        Input("summary-metric-mode", "value"),
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
                no_update,
            )

        try:
            payload = fetch_summary_data(start_date_raw, end_date_raw, circuito, metric_mode)
            saidi, saifi, events, figure, title, status = _summary_visuals_from_payload(
                payload,
                fallback_metric_mode=metric_mode,
                fallback_circuit=circuito or "TODOS",
            )
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
                no_update,
            )
