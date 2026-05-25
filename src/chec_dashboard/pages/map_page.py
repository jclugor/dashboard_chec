from __future__ import annotations

import html as std_html
import time
from typing import Any

from dash import Dash, Input, Output, State, dcc, html, no_update
from dash import ctx
from dash.exceptions import PreventUpdate

from chec_dashboard.config import Settings
from chec_dashboard.dash_app.api_client import (
    fetch_map_circuit_options,
    fetch_map_options,
    fetch_map_render,
)


CHEC_GREEN = "#00782b"
CHEC_PRIMARY_BUTTON = "#11BB52CF"


DEFAULT_MAP_PLACEHOLDER_TEXT = "Selecciona filtros y presiona OK para cargar el mapa."
DEFAULT_MAP_STATUS_TEXT = "Cargando opciones del mapa..."
DEFAULT_MAP_CIRCUIT = "Todos"
DEFAULT_MAP_OUTPUT = "BASE"
MAP_MAX_TRANSIENT_RETRIES = 3
MAP_RETRY_BACKOFF_SECONDS = 0.6
_UNSET: Any = object()
_OVERLAY_HIDDEN_STYLE = {"display": "none"}
_OVERLAY_VISIBLE_STYLE = {"display": "flex"}


def _output_options(values: list[str]) -> list[dict[str, str]]:
    return [{"label": "Base" if value == DEFAULT_MAP_OUTPUT else value, "value": value} for value in values]


def _build_inline_message_html(message: str, color: str = CHEC_GREEN) -> str:
    safe_message = std_html.escape(message, quote=False)
    return (
        "<div style='display:flex;justify-content:center;align-items:center;height:100%;"
        f"font-family:DM Sans,sans-serif;color:{color};'>"
        f"{safe_message}"
        "</div>"
    )


def _initial_map_session_state() -> dict[str, Any]:
    return {
        "current_day": 1,
        "selected_date": None,
        "selected_municipio": None,
        "selected_circuit": DEFAULT_MAP_CIRCUIT,
        "selected_output": DEFAULT_MAP_OUTPUT,
        "in_flight": False,
        "has_successful_render": False,
        "last_successful_render": None,
        "last_status_text": DEFAULT_MAP_STATUS_TEXT,
    }


def _normalize_map_session_state(raw_state: dict[str, Any] | None) -> dict[str, Any]:
    state = _initial_map_session_state()
    if not isinstance(raw_state, dict):
        return state

    state["selected_date"] = raw_state.get("selected_date")
    state["selected_municipio"] = raw_state.get("selected_municipio")
    state["selected_circuit"] = raw_state.get("selected_circuit", DEFAULT_MAP_CIRCUIT)
    state["selected_output"] = raw_state.get("selected_output", DEFAULT_MAP_OUTPUT)
    state["in_flight"] = bool(raw_state.get("in_flight", False))
    state["has_successful_render"] = bool(raw_state.get("has_successful_render", False))
    state["last_successful_render"] = raw_state.get("last_successful_render")
    state["last_status_text"] = str(raw_state.get("last_status_text", DEFAULT_MAP_STATUS_TEXT))

    try:
        current_day = int(raw_state.get("current_day", 1))
    except (TypeError, ValueError):
        current_day = 1
    state["current_day"] = max(current_day, 1)
    return state


def _build_map_state(
    base_state: dict[str, Any],
    *,
    current_day: int | Any = _UNSET,
    selected_date: str | None | Any = _UNSET,
    selected_municipio: str | None | Any = _UNSET,
    selected_circuit: str | None | Any = _UNSET,
    selected_output: str | None | Any = _UNSET,
    in_flight: bool | Any = _UNSET,
    has_successful_render: bool | Any = _UNSET,
    last_successful_render: dict[str, Any] | None | Any = _UNSET,
    last_status_text: str | Any = _UNSET,
) -> dict[str, Any]:
    state = dict(base_state)
    if current_day is not _UNSET:
        state["current_day"] = max(int(current_day), 1)
    if selected_date is not _UNSET:
        state["selected_date"] = selected_date
    if selected_municipio is not _UNSET:
        state["selected_municipio"] = selected_municipio
    if selected_circuit is not _UNSET:
        state["selected_circuit"] = selected_circuit or DEFAULT_MAP_CIRCUIT
    if selected_output is not _UNSET:
        state["selected_output"] = selected_output or DEFAULT_MAP_OUTPUT
    if in_flight is not _UNSET:
        state["in_flight"] = in_flight
    if has_successful_render is not _UNSET:
        state["has_successful_render"] = has_successful_render
    if last_successful_render is not _UNSET:
        state["last_successful_render"] = last_successful_render
    if last_status_text is not _UNSET:
        state["last_status_text"] = last_status_text
    return state


def _is_transient_map_error(exc: Exception) -> bool:
    message = str(exc).lower()
    transient_tokens = (
        "status 502",
        "status 503",
        "status 504",
        "transient api status",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "connection failed",
        "timed out",
    )
    return any(token in message for token in transient_tokens)


def _fetch_map_render_with_retry(
    *,
    selected_date: str,
    selected_municipio: str,
    selected_circuit: str | None,
    selected_output: str | None,
    day: int,
    max_attempts: int = MAP_MAX_TRANSIENT_RETRIES,
) -> tuple[dict[str, Any], int]:
    last_error: Exception | None = None
    attempts = max(max_attempts, 1)
    for attempt in range(1, attempts + 1):
        try:
            payload = fetch_map_render(
                selected_period=selected_date,
                selected_municipio=selected_municipio,
                day=day,
                selected_circuit=selected_circuit,
                selected_output=selected_output,
            )
            return payload, attempt
        except Exception as exc:
            last_error = exc
            if _is_transient_map_error(exc) and attempt < attempts:
                time.sleep(MAP_RETRY_BACKOFF_SECONDS * attempt)
                continue
            break
    assert last_error is not None  # pragma: no cover
    raise last_error


def _load_initial_options(settings: Settings) -> tuple[list[str], list[str], str | None, str | None]:
    _ = settings
    payload = fetch_map_options()
    dates = payload.get("dates", [])
    municipios = payload.get("municipios", [])
    default_date = payload.get("default_date")
    default_municipio = payload.get("default_municipio")
    return dates, municipios, default_date, default_municipio


def get_layout(settings: Settings) -> html.Div:
    # Options are loaded by a callback after the page renders. This keeps page
    # construction lightweight during Azure Container Apps scale-to-zero startup.
    dates, municipios, default_date, default_municipio = [], [], None, None

    return html.Div(
        [
            dcc.Interval(
                id="map-options-load-interval",
                interval=250,
                n_intervals=0,
                max_intervals=5,
                disabled=False,
            ),
            dcc.Store(
                id="map-session-state",
                storage_type="session",
                data=_initial_map_session_state(),
            ),
            html.Div(
                className="map-filter-panel selector-date",
                style={"background": "rgba(0, 120, 43, 0.76)", "zIndex": "8"},
                children=[
                    html.Div(
                        className="map-filter-icon date-icon",
                        style={
                            "backgroundImage": "url('/assets/images/2529e910-74c1-45f9-acd7-0e598c74583b.png')",
                            "backgroundSize": "contain",
                            "backgroundPosition": "center",
                            "backgroundRepeat": "no-repeat",
                        },
                    ),
                    html.Div(
                        "SELECCIONAR FECHA",
                        className="map-filter-label",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontWeight": "700",
                            "color": "white",
                        },
                    ),
                    html.Div(
                        className="map-filter-input",
                        style={"backgroundColor": "white", "borderColor": "white"},
                        children=[
                            dcc.Dropdown(
                                id="map-select-date",
                                options=dates,
                                value=default_date,
                                clearable=False,
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
                        className="map-filter-label",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontWeight": "700",
                            "color": "white",
                        },
                    ),
                    html.Div(
                        className="map-filter-input map-filter-input-wide",
                        style={"backgroundColor": "white", "borderColor": "white"},
                        children=[
                            dcc.Dropdown(
                                id="map-select-municipio",
                                options=municipios,
                                value=default_municipio,
                                clearable=False,
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
                        "CIRCUITO",
                        className="map-filter-label",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontWeight": "700",
                            "color": "white",
                        },
                    ),
                    html.Div(
                        className="map-filter-input",
                        style={"backgroundColor": "white", "borderColor": "white"},
                        children=[
                            dcc.Dropdown(
                                id="map-select-circuit",
                                options=[DEFAULT_MAP_CIRCUIT],
                                value=DEFAULT_MAP_CIRCUIT,
                                disabled=True,
                                clearable=False,
                                placeholder="Todos",
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
                        "SALIDA",
                        className="map-filter-label",
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontWeight": "700",
                            "color": "white",
                        },
                    ),
                    html.Div(
                        className="map-filter-input",
                        style={"backgroundColor": "white", "borderColor": "white"},
                        children=[
                            dcc.Dropdown(
                                id="map-select-output",
                                options=_output_options([DEFAULT_MAP_OUTPUT]),
                                value=DEFAULT_MAP_OUTPUT,
                                disabled=True,
                                clearable=False,
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
                        className="map-filter-button",
                        n_clicks=0,
                        style={
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontSize": "16px",
                            "fontWeight": "700",
                            "color": "black",
                            "cursor": "pointer",
                            "borderRadius": "4px",
                            "borderColor": "white",
                            "backgroundColor": CHEC_PRIMARY_BUTTON,
                        },
                    ),
                ],
            ),
            html.Div(
                className="map-wrapper map-card",
                style={
                    "background": "rgba(45, 154, 35, 0.8)",
                    "zIndex": "1",
                },
                children=[
                    html.Div(
                        className="map-banner",
                        children=[
                            html.Div(
                                className="map-icon",
                                style={
                                    "backgroundImage": "url('/assets/images/6b0cfc3d-739d-432b-a281-b5f18100d3bc.png')",
                                    "backgroundSize": "contain",
                                    "backgroundPosition": "center",
                                    "backgroundRepeat": "no-repeat",
                                },
                            ),
                            html.Div(
                                "Mapa de equipos, eventos y condiciones ambientales",
                                className="map-banner-title",
                                style={
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontWeight": "700",
                                    "color": "white",
                                },
                            ),
                        ],
                    ),
                    html.Div(
                        className="map-frame-container",
                        style={"backgroundColor": "white", "borderColor": "white"},
                        children=[
                            html.Div(
                                id="map-panel-overlay",
                                className="panel-loading-overlay",
                                style=_OVERLAY_HIDDEN_STYLE,
                                children=[
                                    html.Div(
                                        "Cargando mapa...",
                                        className="panel-loading-overlay-text",
                                    )
                                ],
                            ),
                            html.Iframe(
                                id="map-folium-frame",
                                srcDoc=_build_inline_message_html(DEFAULT_MAP_PLACEHOLDER_TEXT),
                                style={"width": "100%", "height": "100%", "border": "none"},
                            ),
                        ],
                    ),
                    html.Div(
                        className="map-slider-row",
                        children=[
                            html.Button(
                                id="map-decrease-btn",
                                className="map-slider-arrow",
                                n_clicks=0,
                                disabled=True,
                                style={
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
                                className="map-slider-container",
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
                                className="map-slider-arrow",
                                n_clicks=0,
                                disabled=True,
                                style={
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
                className="map-status-text",
                children=DEFAULT_MAP_STATUS_TEXT,
                style={
                    "color": "#014719",
                    "fontFamily": "'DM Sans', sans-serif",
                    "fontWeight": "700",
                    "fontSize": "14px",
                },
            ),
        ],
        className="map-page",
        style={
            "width": "100%",
            "display": "flex",
            "flexDirection": "column",
            "alignItems": "center",
            "gap": "10px",
            "padding": "14px 0 10px",
        },
    )


def register_callbacks(app: Dash, settings: Settings) -> None:
    def _control_states(session_state: dict[str, Any]) -> tuple[bool, bool, bool, bool]:
        in_flight = bool(session_state.get("in_flight", False))
        has_successful_render = bool(session_state.get("has_successful_render", False))
        if in_flight:
            return True, True, True, True
        slider_disabled = not has_successful_render
        arrows_disabled = slider_disabled
        return False, slider_disabled, arrows_disabled, arrows_disabled

    @app.callback(
        Output("map-select-date", "options"),
        Output("map-select-date", "value"),
        Output("map-select-municipio", "options"),
        Output("map-select-municipio", "value"),
        Output("map-status-text", "children", allow_duplicate=True),
        Output("map-options-load-interval", "disabled"),
        Output("map-session-state", "data", allow_duplicate=True),
        Input("map-options-load-interval", "n_intervals"),
        prevent_initial_call=True,
    )
    def load_map_options_after_render(
        n_intervals: int | None,
    ) -> tuple[list[str], str | None, list[str], str | None, str, bool, dict[str, Any]]:
        if n_intervals is None:
            raise PreventUpdate

        state = _initial_map_session_state()
        try:
            dates, municipios, default_date, default_municipio = _load_initial_options(settings)
            updated_state = _build_map_state(
                state,
                selected_date=default_date,
                selected_municipio=default_municipio,
                selected_circuit=DEFAULT_MAP_CIRCUIT,
                selected_output=DEFAULT_MAP_OUTPUT,
                last_status_text="Panel listo. Selecciona fecha y municipio, luego presiona OK.",
            )
            return (
                dates,
                default_date,
                municipios,
                default_municipio,
                "Panel listo. Selecciona fecha y municipio, luego presiona OK.",
                True,
                updated_state,
            )
        except Exception as exc:
            final_attempt = n_intervals >= 4
            prefix = (
                "No fue posible cargar las opciones del mapa."
                if final_attempt
                else "Preparando opciones del mapa..."
            )
            status_message = f"{prefix} {str(exc)}"
            updated_state = _build_map_state(
                state,
                selected_date=None,
                selected_municipio=None,
                selected_circuit=DEFAULT_MAP_CIRCUIT,
                selected_output=DEFAULT_MAP_OUTPUT,
                last_status_text=status_message,
            )
            return [], None, [], None, status_message, final_attempt, updated_state

    @app.callback(
        Output("map-select-circuit", "options"),
        Output("map-select-circuit", "value"),
        Output("map-select-circuit", "disabled"),
        Output("map-select-output", "options"),
        Output("map-select-output", "value"),
        Output("map-status-text", "children", allow_duplicate=True),
        Input("map-select-date", "value"),
        Input("map-select-municipio", "value"),
        prevent_initial_call=True,
    )
    def load_map_circuit_options(
        selected_date: str | None,
        selected_municipio: str | None,
    ) -> tuple[list[str], str, bool, list[dict[str, str]], str, str]:
        output_options = _output_options([DEFAULT_MAP_OUTPUT])
        if not selected_date or not selected_municipio:
            return (
                [DEFAULT_MAP_CIRCUIT],
                DEFAULT_MAP_CIRCUIT,
                True,
                output_options,
                DEFAULT_MAP_OUTPUT,
                "Selecciona fecha y municipio para cargar circuitos.",
            )

        try:
            payload = fetch_map_circuit_options(
                selected_period=selected_date,
                selected_municipio=selected_municipio,
            )
            circuits = payload.get("circuits") or [DEFAULT_MAP_CIRCUIT]
            outputs = payload.get("outputs") or [DEFAULT_MAP_OUTPUT]
            default_circuit = payload.get("default_circuit") or circuits[0]
            default_output = payload.get("default_output") or outputs[0]
            output_options = _output_options(outputs)
            return (
                circuits,
                default_circuit,
                False,
                output_options,
                default_output,
                f"Filtros listos para {selected_municipio} en {selected_date}. Presiona OK para renderizar.",
            )
        except Exception as exc:
            return (
                [DEFAULT_MAP_CIRCUIT],
                DEFAULT_MAP_CIRCUIT,
                True,
                output_options,
                DEFAULT_MAP_OUTPUT,
                f"No fue posible cargar los circuitos disponibles: {exc}",
            )

    @app.callback(
        Output("map-folium-frame", "srcDoc"),
        Output("map-date-slider", "value"),
        Output("map-status-text", "children"),
        Output("map-session-state", "data"),
        Output("map-confirm-button", "disabled"),
        Output("map-date-slider", "disabled"),
        Output("map-decrease-btn", "disabled"),
        Output("map-increase-btn", "disabled"),
        Output("map-panel-overlay", "style"),
        Input("map-confirm-button", "n_clicks"),
        Input("map-decrease-btn", "n_clicks"),
        Input("map-increase-btn", "n_clicks"),
        Input("map-date-slider", "value"),
        State("map-select-date", "value"),
        State("map-select-municipio", "value"),
        State("map-select-circuit", "value"),
        State("map-select-output", "value"),
        State("map-date-slider", "min"),
        State("map-date-slider", "max"),
        State("map-session-state", "data"),
        prevent_initial_call=True,
        running=[
            (Output("map-confirm-button", "disabled"), True, no_update),
            (Output("map-date-slider", "disabled"), True, no_update),
            (Output("map-decrease-btn", "disabled"), True, no_update),
            (Output("map-increase-btn", "disabled"), True, no_update),
            (Output("map-status-text", "children"), "Procesando solicitud de mapa...", no_update),
            (Output("map-panel-overlay", "style"), _OVERLAY_VISIBLE_STYLE, _OVERLAY_HIDDEN_STYLE),
        ],
    )
    def handle_map_interactions(
        confirm_clicks: int | None,
        decrease_clicks: int,
        increase_clicks: int,
        slider_value: int | None,
        selected_date: str | None,
        selected_municipio: str | None,
        selected_circuit: str | None,
        selected_output: str | None,
        slider_min: int,
        slider_max: int,
        session_state_raw: dict[str, Any] | None,
    ) -> tuple[str | Any, int, str, dict[str, Any], bool, bool, bool, bool, dict[str, str]]:
        _ = confirm_clicks
        _ = decrease_clicks
        _ = increase_clicks
        triggered_id = ctx.triggered_id
        if triggered_id is None:
            raise PreventUpdate

        state = _normalize_map_session_state(session_state_raw)
        current_day = int(state.get("current_day", 1))

        if triggered_id == "map-confirm-button":
            if not selected_date or not selected_municipio:
                status_message = "Selecciona una fecha y un municipio antes de presionar OK."
                updated_state = _build_map_state(
                    state,
                    selected_date=selected_date,
                    selected_municipio=selected_municipio,
                    selected_circuit=selected_circuit or DEFAULT_MAP_CIRCUIT,
                    selected_output=selected_output or DEFAULT_MAP_OUTPUT,
                    in_flight=False,
                    last_status_text=status_message,
                )
                controls = _control_states(updated_state)
                return no_update, current_day, status_message, updated_state, *controls, _OVERLAY_HIDDEN_STYLE
            requested_day = 1
            selected_period = selected_date
            selected_city = selected_municipio
            requested_circuit = selected_circuit or DEFAULT_MAP_CIRCUIT
            requested_output = selected_output or DEFAULT_MAP_OUTPUT
        elif triggered_id in {"map-decrease-btn", "map-increase-btn", "map-date-slider"}:
            selected_period = state.get("selected_date")
            selected_city = state.get("selected_municipio")
            requested_circuit = state.get("selected_circuit", DEFAULT_MAP_CIRCUIT)
            requested_output = state.get("selected_output", DEFAULT_MAP_OUTPUT)
            if not selected_period or not selected_city:
                status_message = "Primero carga un mapa con OK para habilitar la navegación por día."
                updated_state = _build_map_state(
                    state,
                    in_flight=False,
                    last_status_text=status_message,
                )
                controls = _control_states(updated_state)
                return no_update, current_day, status_message, updated_state, *controls, _OVERLAY_HIDDEN_STYLE

            requested_day = current_day
            if triggered_id == "map-decrease-btn":
                requested_day = max(current_day - 1, int(slider_min))
            elif triggered_id == "map-increase-btn":
                requested_day = min(current_day + 1, int(slider_max))
            elif slider_value is not None:
                requested_day = min(max(int(slider_value), int(slider_min)), int(slider_max))

            if requested_day == current_day:
                status_message = (
                    f"Día actual: {current_day}. Ya estás en el límite del rango disponible."
                )
                updated_state = _build_map_state(
                    state,
                    current_day=current_day,
                    in_flight=False,
                    last_status_text=status_message,
                )
                controls = _control_states(updated_state)
                return no_update, current_day, status_message, updated_state, *controls, _OVERLAY_HIDDEN_STYLE
        else:
            raise PreventUpdate

        processing_state = _build_map_state(
            state,
            selected_date=selected_period,
            selected_municipio=selected_city,
            selected_circuit=requested_circuit,
            selected_output=requested_output,
            current_day=requested_day,
            in_flight=True,
            last_status_text=(
                f"Cargando mapa para {selected_city} ({selected_period}), circuito {requested_circuit}, "
                f"salida {requested_output}, día {requested_day}. "
                f"Intento 1/{MAP_MAX_TRANSIENT_RETRIES}..."
            ),
        )

        try:
            payload, used_attempt = _fetch_map_render_with_retry(
                selected_date=str(selected_period),
                selected_municipio=str(selected_city),
                selected_circuit=str(requested_circuit),
                selected_output=str(requested_output),
                day=requested_day,
                max_attempts=MAP_MAX_TRANSIENT_RETRIES,
            )
            resolved_day = int(payload.get("current_day", requested_day))
            map_html = payload.get("map_html") or ""
            if used_attempt > 1:
                status_message = (
                    f"Mapa cargado tras reintento ({used_attempt}/{MAP_MAX_TRANSIENT_RETRIES}) "
                    f"para {selected_city}, circuito {requested_circuit}, salida {requested_output}, "
                    f"período {selected_period}. Día actual: {resolved_day}."
                )
            else:
                status_message = payload.get(
                    "status_text",
                    (
                        f"Mapa cargado para municipio {selected_city}, circuito {requested_circuit}, "
                        f"salida {requested_output}, período {selected_period}. Día actual: {resolved_day}."
                    ),
                )

            updated_state = _build_map_state(
                processing_state,
                current_day=resolved_day,
                selected_date=str(selected_period),
                selected_municipio=str(selected_city),
                selected_circuit=str(requested_circuit),
                selected_output=str(requested_output),
                in_flight=False,
                has_successful_render=True,
                last_successful_render={
                    "selected_date": str(selected_period),
                    "selected_municipio": str(selected_city),
                    "selected_circuit": str(requested_circuit),
                    "selected_output": str(requested_output),
                    "current_day": resolved_day,
                },
                last_status_text=status_message,
            )
            controls = _control_states(updated_state)
            return map_html, resolved_day, status_message, updated_state, *controls, _OVERLAY_HIDDEN_STYLE
        except Exception as exc:
            error_message = str(exc)
            if _is_transient_map_error(exc):
                error_message = (
                    "No se pudo renderizar el mapa tras "
                    f"{MAP_MAX_TRANSIENT_RETRIES} intentos (502/503/504). "
                    "Intenta nuevamente en unos segundos."
                )
            else:
                error_message = f"No se pudo renderizar el mapa: {error_message}"

            updated_state = _build_map_state(
                processing_state,
                current_day=requested_day,
                selected_date=str(selected_period),
                selected_municipio=str(selected_city),
                selected_circuit=str(requested_circuit),
                selected_output=str(requested_output),
                in_flight=False,
                last_status_text=error_message,
            )
            controls = _control_states(updated_state)
            return no_update, current_day, error_message, updated_state, *controls, _OVERLAY_HIDDEN_STYLE
