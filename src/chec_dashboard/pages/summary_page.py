from datetime import date

from dash import Dash, Input, Output, dcc, html
import plotly.graph_objects as go

from chec_dashboard.config import Settings
from chec_dashboard.services.summary_service import (
    aggregate_daily,
    coerce_window,
    compute_kpis,
    filter_summary_data,
    get_circuit_options,
    get_default_window,
    load_summary_dataset,
)


CHEC_GREEN = "#00782b"
CHEC_BUTTON_GREEN = "#11BB52CF"


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


def _build_line_figure(
    daily_data,
    metric_mode: str,
    circuito: str,
    start_date: date,
    end_date: date,
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
        title=(
            f"Tendencia diaria de {metric_mode} para {circuito} "
            f"({start_date.isoformat()} a {end_date.isoformat()})"
        ),
        margin={"l": 40, "r": 20, "t": 52, "b": 40},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        hovermode="x unified",
    )
    fig.update_xaxes(title_text="Fecha")
    fig.update_yaxes(title_text="Valor diario (suma)")
    return fig


def _kpi_card(card_id: str, title: str, initial_value: str = "--") -> html.Div:
    return html.Div(
        style={
            "width": "32%",
            "height": "100%",
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
                style={
                    "fontFamily": "'DM Sans', sans-serif",
                    "fontSize": "16px",
                    "fontWeight": "700",
                    "color": CHEC_GREEN,
                    "marginBottom": "4px",
                },
            ),
            html.Div(
                id=card_id,
                style={
                    "fontFamily": "'Poppins', sans-serif",
                    "fontSize": "28px",
                    "fontWeight": "700",
                    "color": "#014719",
                },
                children=initial_value,
            ),
        ],
    )


def get_layout(settings: Settings) -> html.Div:
    circuits: list[str] = []
    min_date = None
    max_date = None
    default_start = None
    default_end = None
    initial_saidi = "--"
    initial_saifi = "--"
    initial_events = "--"
    initial_status = "Selecciona filtros para visualizar la tendencia."
    initial_figure = _empty_figure("Selecciona filtros para visualizar la tendencia.")

    try:
        dataset = load_summary_dataset(str(settings.data_dir))
        circuits = get_circuit_options(dataset)
        min_date = dataset.min_date
        max_date = dataset.max_date
        default_start, default_end = get_default_window(dataset, days=180)

        default_circuit = circuits[0] if circuits else None
        filtered = filter_summary_data(dataset, default_circuit, default_start, default_end)
        daily_data = aggregate_daily(filtered, default_start, default_end)
        kpis = compute_kpis(filtered)
        circuit_label = default_circuit or "TODOS"
        initial_figure = _build_line_figure(
            daily_data=daily_data,
            metric_mode="BOTH",
            circuito=circuit_label,
            start_date=default_start,
            end_date=default_end,
        )
        initial_saidi = f"{kpis['saidi_total']:.4f}"
        initial_saifi = f"{kpis['saifi_total']:.4f}"
        initial_events = f"{kpis['event_count']}"
        if filtered.empty:
            initial_status = (
                f"No se encontraron eventos para el circuito {circuit_label} "
                f"entre {default_start.isoformat()} y {default_end.isoformat()}. "
                "Se muestran series en cero."
            )
        else:
            initial_status = (
                f"Circuito: {circuit_label}. "
                f"Ventana: {default_start.isoformat()} a {default_end.isoformat()}. "
                f"Eventos: {kpis['event_count']}."
            )
    except Exception as exc:
        load_error = str(exc)
        initial_status = load_error
        initial_figure = _empty_figure(load_error)

    default_circuit = circuits[0] if circuits else None

    return html.Div(
        [
            html.Div(
                style={
                    "width": "98%",
                    "height": "11vh",
                    "margin": "18px 0 0 0",
                    "background": "rgba(0, 120, 43, 0.76)",
                    "borderRadius": "9px",
                    "display": "flex",
                    "flexDirection": "row",
                    "alignItems": "center",
                    "padding": "0 1.2%",
                    "gap": "1.2%",
                },
                children=[
                    html.Div(
                        "VENTANA DE TIEMPO",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontSize": "16px",
                            "fontWeight": "700",
                            "color": "white",
                            "width": "14%",
                        },
                    ),
                    html.Div(
                        style={
                            "width": "28%",
                            "backgroundColor": "white",
                            "borderRadius": "8px",
                            "padding": "4px 8px",
                        },
                        children=[
                            dcc.DatePickerRange(
                                id="summary-date-window",
                                min_date_allowed=min_date,
                                max_date_allowed=max_date,
                                start_date=default_start,
                                end_date=default_end,
                                display_format="YYYY-MM-DD",
                            )
                        ],
                    ),
                    html.Div(
                        "CIRCUITO",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontSize": "16px",
                            "fontWeight": "700",
                            "color": "white",
                            "width": "8%",
                            "textAlign": "center",
                        },
                    ),
                    html.Div(
                        style={"width": "26%", "backgroundColor": "white", "borderRadius": "8px"},
                        children=[
                            dcc.Dropdown(
                                id="summary-circuit",
                                options=circuits,
                                value=default_circuit,
                                placeholder="Selecciona circuito",
                                searchable=True,
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
                        "METRICA",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontSize": "16px",
                            "fontWeight": "700",
                            "color": "white",
                            "width": "7%",
                            "textAlign": "center",
                        },
                    ),
                    html.Div(
                        style={"width": "13%", "backgroundColor": "white", "borderRadius": "8px"},
                        children=[
                            dcc.Dropdown(
                                id="summary-metric-mode",
                                options=[
                                    {"label": "SAIDI", "value": "SAIDI"},
                                    {"label": "SAIFI", "value": "SAIFI"},
                                    {"label": "BOTH", "value": "BOTH"},
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
                style={
                    "width": "98%",
                    "height": "69vh",
                    "margin": "16px 0 0 0",
                    "background": "rgba(45, 154, 35, 0.8)",
                    "borderRadius": "9px",
                    "display": "flex",
                    "flexDirection": "column",
                    "alignItems": "center",
                },
                children=[
                    html.Div(
                        "Resumen rapido SAIDI/SAIFI por circuito",
                        style={
                            "width": "100%",
                            "height": "8%",
                            "display": "flex",
                            "alignItems": "center",
                            "justifyContent": "center",
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontSize": "26px",
                            "fontWeight": "700",
                            "color": "white",
                        },
                    ),
                    html.Div(
                        style={
                            "width": "97%",
                            "height": "16%",
                            "display": "flex",
                            "flexDirection": "row",
                            "justifyContent": "space-between",
                            "alignItems": "center",
                        },
                        children=[
                            _kpi_card("summary-kpi-saidi", "Total SAIDI", initial_saidi),
                            _kpi_card("summary-kpi-saifi", "Total SAIFI", initial_saifi),
                            _kpi_card("summary-kpi-events", "Eventos", initial_events),
                        ],
                    ),
                    html.Div(
                        style={
                            "width": "97%",
                            "height": "71%",
                            "backgroundColor": "white",
                            "borderRadius": "10px",
                            "marginTop": "8px",
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
                children=initial_status,
                style={
                    "width": "98%",
                    "marginTop": "6px",
                    "color": "#014719",
                    "fontFamily": "'DM Sans', sans-serif",
                    "fontWeight": "700",
                    "fontSize": "14px",
                },
            ),
        ],
        style={"width": "100%", "height": "100%", "display": "flex", "flexDirection": "column", "alignItems": "center"},
    )


def register_callbacks(app: Dash, settings: Settings) -> None:
    @app.callback(
        Output("summary-kpi-saidi", "children"),
        Output("summary-kpi-saifi", "children"),
        Output("summary-kpi-events", "children"),
        Output("summary-line-chart", "figure"),
        Output("summary-status-text", "children"),
        Input("summary-date-window", "start_date"),
        Input("summary-date-window", "end_date"),
        Input("summary-circuit", "value"),
        Input("summary-metric-mode", "value"),
        prevent_initial_call=True,
    )
    def update_summary(
        start_date_raw: str | None,
        end_date_raw: str | None,
        circuito: str | None,
        metric_mode: str | None,
    ):
        try:
            dataset = load_summary_dataset(str(settings.data_dir))
        except Exception as exc:
            return "--", "--", "--", _empty_figure(str(exc)), str(exc)

        metric_mode = metric_mode or "BOTH"
        start_date, end_date = coerce_window(dataset, start_date_raw, end_date_raw)
        filtered = filter_summary_data(dataset, circuito, start_date, end_date)
        daily_data = aggregate_daily(filtered, start_date, end_date)
        kpis = compute_kpis(filtered)

        circuit_label = circuito or "TODOS"
        figure = _build_line_figure(
            daily_data=daily_data,
            metric_mode=metric_mode,
            circuito=circuit_label,
            start_date=start_date,
            end_date=end_date,
        )

        if filtered.empty:
            status_text = (
                f"No se encontraron eventos para el circuito {circuit_label} "
                f"entre {start_date.isoformat()} y {end_date.isoformat()}. "
                "Se muestran series en cero."
            )
        else:
            status_text = (
                f"Circuito: {circuit_label}. "
                f"Ventana: {start_date.isoformat()} a {end_date.isoformat()}. "
                f"Eventos: {kpis['event_count']}."
            )

        return (
            f"{kpis['saidi_total']:.4f}",
            f"{kpis['saifi_total']:.4f}",
            f"{kpis['event_count']}",
            figure,
            status_text,
        )
