from dataclasses import dataclass

from dash import Dash, Input, Output, State, dcc, html
from dash import ctx
from dash.exceptions import PreventUpdate

from chec_dashboard.config import Settings
from chec_dashboard.services.map_service import (
    FilteredMapDataset,
    filter_map_dataset,
    get_map_filter_options,
    load_map_dataset,
    render_base_map,
)


CHEC_GREEN = "#00782b"
CHEC_PRIMARY_BUTTON = "#11BB52CF"


@dataclass
class MapRuntimeState:
    filtered_data: FilteredMapDataset | None = None
    current_day: int = 1
    last_confirm_clicks: int = 0
    selected_date: str | None = None
    selected_municipio: str | None = None


RUNTIME_STATE = MapRuntimeState()


def _load_initial_options(settings: Settings) -> tuple[list[str], list[str], str | None, str | None]:
    dataset = load_map_dataset(str(settings.data_dir))
    dates, municipios = get_map_filter_options(dataset)
    default_date = dates[0] if dates else None
    default_municipio = municipios[0] if municipios else None
    return dates, municipios, default_date, default_municipio


def get_layout(settings: Settings) -> html.Div:
    load_error = None
    try:
        dates, municipios, default_date, default_municipio = _load_initial_options(settings)
    except Exception as exc:
        dates, municipios, default_date, default_municipio = [], [], None, None
        load_error = str(exc)

    return html.Div(
        [
            html.Div(
                className="selector-date",
                style={
                    "width": "98%",
                    "height": "10vh",
                    "margin": "21px 0 0 0",
                    "background": "rgba(0, 120, 43, 0.76)",
                    "zIndex": "8",
                    "borderRadius": "9px",
                    "overflow": "visible",
                    "display": "flex",
                    "flexDirection": "row",
                    "alignItems": "center",
                },
                children=[
                    html.Div(
                        className="date-icon",
                        style={
                            "backgroundImage": "url('/assets/images/2529e910-74c1-45f9-acd7-0e598c74583b.png')",
                            "backgroundSize": "contain",
                            "backgroundPosition": "center",
                            "backgroundRepeat": "no-repeat",
                            "width": "6%",
                            "height": "50%",
                            "borderRadius": "14px",
                            "marginLeft": "0%",
                        },
                    ),
                    html.Div(
                        "SELECCIONAR FECHA",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontSize": "16px",
                            "fontWeight": "700",
                            "color": "white",
                            "width": "12%",
                        },
                    ),
                    html.Div(
                        style={
                            "backgroundColor": "white",
                            "width": "12%",
                            "borderColor": "white",
                            "borderRadius": "9px",
                            "height": "6vh",
                            "margin": "0 0 0 1%",
                            "display": "flex",
                            "alignItems": "center",
                        },
                        children=[
                            dcc.Dropdown(
                                id="map-select-date",
                                options=dates,
                                value=default_date,
                                style={
                                    "position": "relative",
                                    "width": "100%",
                                    "zIndex": 1000,
                                    "border": "none",
                                    "color": CHEC_GREEN,
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontSize": "20px",
                                },
                            )
                        ],
                    ),
                    html.Div(
                        "SELECCIONAR MUNICIPIO",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontSize": "16px",
                            "fontWeight": "700",
                            "color": "white",
                            "margin": "0 0 0 1%",
                            "width": "14%",
                        },
                    ),
                    html.Div(
                        style={
                            "backgroundColor": "white",
                            "width": "18%",
                            "borderColor": "white",
                            "borderRadius": "9px",
                            "height": "6vh",
                            "margin": "0 0 0 1%",
                            "display": "flex",
                            "alignItems": "center",
                        },
                        children=[
                            dcc.Dropdown(
                                id="map-select-municipio",
                                options=municipios,
                                value=default_municipio,
                                style={
                                    "position": "relative",
                                    "width": "100%",
                                    "zIndex": 1000,
                                    "border": "none",
                                    "color": CHEC_GREEN,
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontSize": "20px",
                                },
                            )
                        ],
                    ),
                    html.Div(
                        "TIPO CONDICION",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontSize": "16px",
                            "fontWeight": "700",
                            "color": "white",
                            "margin": "0 0 0 1%",
                            "width": "11%",
                        },
                    ),
                    html.Div(
                        style={
                            "backgroundColor": "white",
                            "width": "10%",
                            "borderColor": "white",
                            "borderRadius": "9px",
                            "height": "6vh",
                            "margin": "0 0 0 1%",
                            "display": "flex",
                            "alignItems": "center",
                        },
                        children=[
                            dcc.Dropdown(
                                id="map-select-condition",
                                options=[{"label": "BASE", "value": "BASE"}],
                                value="BASE",
                                disabled=True,
                                style={
                                    "position": "relative",
                                    "width": "100%",
                                    "zIndex": 1000,
                                    "border": "none",
                                    "color": CHEC_GREEN,
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontSize": "20px",
                                },
                            )
                        ],
                    ),
                    html.Button(
                        "OK",
                        id="map-confirm-button",
                        n_clicks=0,
                        style={
                            "position": "absolute",
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontSize": "16px",
                            "fontWeight": "700",
                            "color": "black",
                            "cursor": "pointer",
                            "borderRadius": "3px",
                            "borderColor": "white",
                            "right": "2.5%",
                            "width": "3.5%",
                            "height": "5vh",
                            "backgroundColor": CHEC_PRIMARY_BUTTON,
                        },
                    ),
                ],
            ),
            html.Div(
                className="map-wrapper",
                style={
                    "width": "98%",
                    "height": "70vh",
                    "margin": "18px 0 0 0",
                    "background": "rgba(45, 154, 35, 0.8)",
                    "zIndex": "1",
                    "borderRadius": "9px",
                    "display": "flex",
                    "flexDirection": "column",
                    "justifyContent": "center",
                },
                children=[
                    html.Div(
                        className="map-banner",
                        style={
                            "display": "flex",
                            "flexDirection": "row",
                            "position": "relative",
                            "height": "6vh",
                            "alignItems": "center",
                            "margin": "-1vh 0 0 0",
                        },
                        children=[
                            html.Div(
                                className="map-icon",
                                style={
                                    "backgroundImage": "url('/assets/images/6b0cfc3d-739d-432b-a281-b5f18100d3bc.png')",
                                    "backgroundSize": "contain",
                                    "backgroundPosition": "center",
                                    "backgroundRepeat": "no-repeat",
                                    "width": "6%",
                                    "height": "80%",
                                    "borderRadius": "14px",
                                    "marginLeft": "0%",
                                },
                            ),
                            html.Div(
                                "Mapa de equipos, eventos y condiciones ambientales",
                                style={
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontSize": "20px",
                                    "fontWeight": "700",
                                    "color": "white",
                                },
                            ),
                        ],
                    ),
                    html.Div(
                        style={
                            "backgroundColor": "white",
                            "width": "97.6%",
                            "borderColor": "white",
                            "borderRadius": "9px",
                            "height": "52vh",
                            "margin": "1vh 0 0 1.2%",
                        },
                        children=[
                            html.Iframe(
                                id="map-folium-frame",
                                srcDoc=(
                                    "<div style='display:flex;justify-content:center;align-items:center;"
                                    "height:100%;font-family:DM Sans,sans-serif;color:#00782b;'>"
                                    "Selecciona filtros y presiona OK para cargar el mapa."
                                    "</div>"
                                ),
                                style={"width": "100%", "height": "100%", "border": "none"},
                            ),
                        ],
                    ),
                    html.Div(
                        style={
                            "display": "flex",
                            "flexDirection": "row",
                            "alignItems": "center",
                            "width": "97%",
                            "margin": "1vh 0 0 1.5%",
                        },
                        children=[
                            html.Button(
                                id="map-decrease-btn",
                                n_clicks=0,
                                disabled=True,
                                style={
                                    "width": "5vh",
                                    "height": "5vh",
                                    "margin": "0 1% 0 0",
                                    "backgroundImage": "url('/assets/images/left-arrow-direction-svgrepo-com.svg')",
                                    "backgroundSize": "cover",
                                    "backgroundPosition": "center",
                                    "backgroundRepeat": "no-repeat",
                                    "border": "none",
                                    "backgroundColor": "transparent",
                                    "cursor": "pointer",
                                },
                            ),
                            html.Div(
                                style={"width": "100%"},
                                children=[
                                    dcc.Slider(
                                        id="map-date-slider",
                                        min=1,
                                        max=31,
                                        step=1,
                                        value=1,
                                        disabled=True,
                                        tooltip={"always_visible": True, "placement": "top"},
                                    )
                                ],
                            ),
                            html.Button(
                                id="map-increase-btn",
                                n_clicks=0,
                                disabled=True,
                                style={
                                    "width": "5vh",
                                    "height": "5vh",
                                    "margin": "0 0 0 1%",
                                    "backgroundImage": "url('/assets/images/left-arrow-direction-svgrepo-com.svg')",
                                    "backgroundSize": "cover",
                                    "backgroundPosition": "center",
                                    "backgroundRepeat": "no-repeat",
                                    "transform": "rotate(180deg)",
                                    "border": "none",
                                    "backgroundColor": "transparent",
                                    "cursor": "pointer",
                                },
                            ),
                        ],
                    ),
                ],
            ),
            html.Div(
                id="map-status-text",
                children=load_error
                or "Panel listo. Selecciona fecha y municipio, luego presiona OK.",
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
        Output("map-folium-frame", "srcDoc"),
        Output("map-date-slider", "value"),
        Output("map-date-slider", "disabled"),
        Output("map-decrease-btn", "disabled"),
        Output("map-increase-btn", "disabled"),
        Output("map-status-text", "children"),
        Input("map-confirm-button", "n_clicks"),
        Input("map-decrease-btn", "n_clicks"),
        Input("map-increase-btn", "n_clicks"),
        Input("map-date-slider", "value"),
        State("map-select-date", "value"),
        State("map-select-municipio", "value"),
        State("map-date-slider", "min"),
        State("map-date-slider", "max"),
        prevent_initial_call=True,
    )
    def handle_map_interactions(
        confirm_clicks: int | None,
        decrease_clicks: int,
        increase_clicks: int,
        slider_value: int,
        selected_date: str | None,
        selected_municipio: str | None,
        slider_min: int,
        slider_max: int,
    ) -> tuple[str, int, bool, bool, bool, str]:
        triggered_id = ctx.triggered_id
        if triggered_id is None:
            raise PreventUpdate

        if triggered_id == "map-confirm-button":
            if confirm_clicks is None or confirm_clicks <= RUNTIME_STATE.last_confirm_clicks:
                raise PreventUpdate
            if not selected_date or not selected_municipio:
                raise PreventUpdate

            RUNTIME_STATE.last_confirm_clicks = confirm_clicks
            try:
                dataset = load_map_dataset(str(settings.data_dir))
                RUNTIME_STATE.filtered_data = filter_map_dataset(
                    dataset,
                    selected_period=selected_date,
                    selected_municipio=selected_municipio,
                )
                RUNTIME_STATE.current_day = 1
                RUNTIME_STATE.selected_date = selected_date
                RUNTIME_STATE.selected_municipio = selected_municipio
                map_html = render_base_map(RUNTIME_STATE.filtered_data, day=1)
                status = (
                    f"Mapa cargado para {selected_municipio} en {selected_date}. "
                    "Usa el slider o las flechas para cambiar el dia."
                )
                return map_html, 1, False, False, False, status
            except Exception as exc:
                error_html = (
                    "<div style='display:flex;justify-content:center;align-items:center;height:100%;"
                    "font-family:DM Sans,sans-serif;color:#a10c0c;'>"
                    f"{str(exc)}"
                    "</div>"
                )
                return error_html, 1, True, True, True, str(exc)

        if RUNTIME_STATE.filtered_data is None:
            raise PreventUpdate

        if triggered_id == "map-decrease-btn" and RUNTIME_STATE.current_day > slider_min:
            RUNTIME_STATE.current_day -= 1
        elif triggered_id == "map-increase-btn" and RUNTIME_STATE.current_day < slider_max:
            RUNTIME_STATE.current_day += 1
        elif triggered_id == "map-date-slider":
            if slider_value == RUNTIME_STATE.current_day:
                raise PreventUpdate
            RUNTIME_STATE.current_day = slider_value
        else:
            raise PreventUpdate

        map_html = render_base_map(RUNTIME_STATE.filtered_data, RUNTIME_STATE.current_day)
        municipio = RUNTIME_STATE.selected_municipio or "municipio seleccionado"
        period = RUNTIME_STATE.selected_date or "periodo seleccionado"
        status = (
            f"Mapa cargado para {municipio} en {period}. "
            f"Dia actual: {RUNTIME_STATE.current_day}."
        )
        return map_html, RUNTIME_STATE.current_day, False, False, False, status
