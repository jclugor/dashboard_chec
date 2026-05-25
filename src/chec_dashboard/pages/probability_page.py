import base64
import time
from typing import Any

from dash import Dash, Input, Output, State, dcc, html
from dash import exceptions

from chec_dashboard.config import Settings
from chec_dashboard.dash_app.api_client import (
    fetch_probability_data,
    fetch_probability_metadata,
    fetch_probability_options,
)


CHEC_GREEN = "#00782b"
CHEC_BUTTON_GREEN = "#11BB52CF"
PROBABILITY_INITIAL_INTERVAL_MS = 250
_OVERLAY_HIDDEN_STYLE = {"display": "none"}
_OVERLAY_VISIBLE_STYLE = {"display": "flex"}

selection_criteria: list[Any] = [
    "",
    ["", "", "", ""],
    ["", "", "", ""],
    ["", "", "", ""],
    ["", "", "", ""],
    "",
]
last_confirm_clicks = -1


def _create_dropdown(
    dropdown_id: str,
    options: list[Any],
    z_index: int,
    value: str = "",
) -> dcc.Dropdown:
    return dcc.Dropdown(
        id=dropdown_id,
        options=options,
        value=value,
        maxHeight=160,
        style={
            "position": "relative",
            "width": "100%",
            "zIndex": z_index,
            "border": "none",
            "color": CHEC_GREEN,
            "fontFamily": "'DM Sans', sans-serif",
            "fontSize": "20px",
        },
    )


def _create_filter_components(
    filter_kind: str,
    value_options: list[str],
    z_index: int,
    component_prefix: str,
    *,
    empty_message: str | None = None,
) -> list[html.Div] | html.Div | None:
    base_text_style = {
        "color": "white",
        "textAlign": "center",
        "fontSize": "18px",
        "fontWeight": "700",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "center",
    }

    if empty_message:
        return html.Div(
            empty_message,
            className="prob-filter-empty-message",
            style={**base_text_style, "width": "100%", "fontSize": "18px"},
        )

    if filter_kind == "seleccion":
        options = [""] + value_options
        return [
            html.Div("Selección:", className="prob-filter-label", style=base_text_style),
            html.Div(
                dcc.Dropdown(
                    id=f"{component_prefix}-1",
                    options=options,
                    value="",
                    maxHeight=160,
                    style={
                        "width": "100%",
                        "zIndex": z_index,
                        "border": "none",
                        "color": CHEC_GREEN,
                        "fontSize": "20px",
                    },
                ),
                className="prob-filter-input prob-filter-input-select",
                style={
                    "backgroundColor": "white",
                    "borderRadius": "5px",
                },
            ),
        ]

    if filter_kind == "rango_num":
        return [
            html.Div(
                "Operador:",
                className="prob-filter-label",
                style={**base_text_style, "fontSize": "18px"},
            ),
            html.Div(
                dcc.Dropdown(
                    id=f"{component_prefix}-1",
                    options=["", ">", ">=", "<", "<=", "!=", "=="],
                    value="",
                    maxHeight=160,
                    style={
                        "width": "100%",
                        "zIndex": z_index,
                        "border": "none",
                        "color": CHEC_GREEN,
                        "fontSize": "20px",
                    },
                ),
                className="prob-filter-input prob-filter-input-operator",
                style={
                    "backgroundColor": "white",
                    "borderRadius": "5px",
                },
            ),
            html.Div("Valor:", className="prob-filter-label", style=base_text_style),
            html.Div(
                dcc.Input(
                    id=f"{component_prefix}-2",
                    type="number",
                    placeholder="Ingresa un valor",
                    style={
                        "width": "100%",
                        "height": "100%",
                        "border": "none",
                        "color": CHEC_GREEN,
                        "fontSize": "20px",
                        "padding": "0 10px",
                    },
                ),
                className="prob-filter-input prob-filter-input-value",
                style={"backgroundColor": "white", "borderRadius": "5px"},
            ),
        ]

    if filter_kind == "fecha":
        options = [""] + value_options
        return [
            html.Div("Desde:", className="prob-filter-label", style=base_text_style),
            html.Div(
                dcc.Dropdown(
                    id=f"{component_prefix}-1",
                    options=options,
                    value="",
                    maxHeight=160,
                    style={
                        "width": "100%",
                        "zIndex": z_index,
                        "border": "none",
                        "color": CHEC_GREEN,
                        "fontSize": "15px",
                    },
                ),
                className="prob-filter-input prob-filter-input-date",
                style={
                    "backgroundColor": "white",
                    "borderRadius": "5px",
                },
            ),
            html.Div("Hasta:", className="prob-filter-label", style=base_text_style),
            html.Div(
                dcc.Dropdown(
                    id=f"{component_prefix}-2",
                    options=options,
                    value="",
                    maxHeight=160,
                    style={
                        "width": "100%",
                        "zIndex": z_index,
                        "border": "none",
                        "color": CHEC_GREEN,
                        "fontSize": "15px",
                    },
                ),
                className="prob-filter-input prob-filter-input-date",
                style={
                    "backgroundColor": "white",
                    "borderRadius": "5px",
                },
            ),
        ]

    return None


def _api_error_block(message: str, font_size: str = "14px") -> html.Div:
    return html.Div(
        message,
        style={
            "padding": "6px",
            "fontFamily": "'DM Sans', sans-serif",
            "fontWeight": "700",
            "color": "#a10c0c",
            "fontSize": font_size,
        },
    )


def _columns_for_criteria(criteria_value: str) -> list[str]:
    if not criteria_value:
        return []
    payload = fetch_probability_metadata(action="columns", criteria=criteria_value)
    return payload.get("columns", [])


def _build_probability_graph_component(
    graph_name: str,
    graph_data_uri: str | None,
) -> html.Div:
    if graph_data_uri:
        graph_src = graph_data_uri
    else:
        timestamp = int(time.time())
        graph_src = f"/outputs/{graph_name}?v={timestamp}"

    return html.Div(
        [
            html.Img(src=graph_src, className="probability-graph-image", style={"width": "100%", "borderRadius": "10px"}),
            html.Button(
                id="probability-save-button",
                className="probability-save-button",
                n_clicks=0,
                style={
                    "position": "absolute",
                    "right": "1%",
                    "top": "2%",
                    "backgroundImage": "url('/assets/images/download-svgrepo-com.svg')",
                    "backgroundSize": "cover",
                    "border": "none",
                    "backgroundColor": "transparent",
                    "cursor": "pointer",
                },
            ),
        ],
        className="probability-graph-wrapper",
        style={"position": "relative", "width": "100%", "height": "100%"},
    )


def get_layout() -> html.Div:
    initial_probability_text = "P(X|Y1,Y2,Y3,...,YN)"
    initial_graph_children: str | html.Div = "Preparando criterios y filtros de probabilidad..."
    main_options: list[Any] = []
    dummy_divs = [
        html.Div(id=f"prob-dummy-output-{i}-{j}", style={"display": "none"})
        for i in range(1, 5)
        for j in range(1, 3)
    ]
    dummy_divs.append(html.Div(id="prob-dummy-output-target", style={"display": "none"}))

    return html.Div(
        [
            dcc.Interval(
                id="prob-options-load-interval",
                interval=PROBABILITY_INITIAL_INTERVAL_MS,
                n_intervals=0,
                max_intervals=1,
                disabled=False,
            ),
            html.Div(
                className="workspace-row probability-workspace-row",
                children=[
                    html.Div(
                        className="criteria-container probability-criteria-container",
                        style={
                            "position": "relative",
                            "backgroundColor": "#16D622",
                            "opacity": "0.7",
                        },
                        children=[
                            html.Div(
                                "Criterio",
                                className="probability-section-title",
                                style={
                                    "color": "#FFFFFF",
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontWeight": "700",
                                },
                            ),
                            html.Div(
                                className="probability-main-dropdown",
                                children=[
                                    dcc.Dropdown(
                                        id="prob-select-criteria",
                                        options=main_options,
                                        value="",
                                        disabled=True,
                                        maxHeight=160,
                                        style={
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
                                className="probability-subcriteria-block",
                                children=[
                                    html.Div(
                                        "Sub-criterio 1",
                                        className="probability-subcriteria-title",
                                        style={
                                            "color": "#FFFFFF",
                                            "fontFamily": "'DM Sans', sans-serif",
                                            "fontWeight": "700",
                                        },
                                    ),
                                    html.Div(
                                        id="prob-sub-criteria-1-container",
                                        className="probability-subcriteria-dropdown",
                                        style={"borderRadius": "5px", "backgroundColor": "white"},
                                    ),
                                    html.Div(
                                        id="prob-sub-criteria-1-filters-container",
                                        className="probability-subcriteria-filters",
                                    ),
                                ],
                            ),
                            html.Div(
                                className="probability-subcriteria-block",
                                children=[
                                    html.Div(
                                        "Sub-criterio 2",
                                        className="probability-subcriteria-title",
                                        style={
                                            "color": "#FFFFFF",
                                            "fontFamily": "'DM Sans', sans-serif",
                                            "fontWeight": "700",
                                        },
                                    ),
                                    html.Div(
                                        id="prob-sub-criteria-2-container",
                                        className="probability-subcriteria-dropdown",
                                        style={"borderRadius": "5px", "backgroundColor": "white"},
                                    ),
                                    html.Div(
                                        id="prob-sub-criteria-2-filters-container",
                                        className="probability-subcriteria-filters",
                                    ),
                                ],
                            ),
                            html.Div(
                                className="probability-subcriteria-block",
                                children=[
                                    html.Div(
                                        "Sub-criterio 3",
                                        className="probability-subcriteria-title",
                                        style={
                                            "color": "#FFFFFF",
                                            "fontFamily": "'DM Sans', sans-serif",
                                            "fontWeight": "700",
                                        },
                                    ),
                                    html.Div(
                                        id="prob-sub-criteria-3-container",
                                        className="probability-subcriteria-dropdown",
                                        style={"borderRadius": "5px", "backgroundColor": "white"},
                                    ),
                                    html.Div(
                                        id="prob-sub-criteria-3-filters-container",
                                        className="probability-subcriteria-filters",
                                    ),
                                ],
                            ),
                            html.Div(
                                className="probability-subcriteria-block",
                                children=[
                                    html.Div(
                                        "Sub-criterio 4",
                                        className="probability-subcriteria-title",
                                        style={
                                            "color": "#FFFFFF",
                                            "fontFamily": "'DM Sans', sans-serif",
                                            "fontWeight": "700",
                                        },
                                    ),
                                    html.Div(
                                        id="prob-sub-criteria-4-container",
                                        className="probability-subcriteria-dropdown",
                                        style={"borderRadius": "5px", "backgroundColor": "white"},
                                    ),
                                    html.Div(
                                        id="prob-sub-criteria-4-filters-container",
                                        className="probability-subcriteria-filters",
                                    ),
                                ],
                            ),
                            html.Div(
                                className="probability-target-block",
                                children=[
                                    html.Div(
                                        "Variable objetivo",
                                        className="probability-subcriteria-title",
                                        style={
                                            "color": "#FFFFFF",
                                            "fontFamily": "'DM Sans', sans-serif",
                                            "fontWeight": "700",
                                        },
                                    ),
                                    html.Div(
                                        className="probability-target-row",
                                        children=[
                                            html.Div(
                                                id="prob-target-variable-container",
                                                className="probability-target-dropdown",
                                                style={"borderRadius": "5px", "backgroundColor": "white"},
                                            ),
                                            html.Button(
                                                "OK",
                                                id="prob-confirm-button-ok",
                                                className="probability-confirm-button",
                                                n_clicks=0,
                                                style={
                                                    "fontFamily": "'DM Sans', sans-serif",
                                                    "fontSize": "16px",
                                                    "fontWeight": "700",
                                                    "color": "black",
                                                    "cursor": "pointer",
                                                    "borderRadius": "4px",
                                                    "borderColor": "white",
                                                    "backgroundColor": CHEC_BUTTON_GREEN,
                                                },
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        className="graph-container probability-graph-container",
                        style={"position": "relative", "backgroundColor": "#28DB7F"},
                        children=[
                            html.Div(
                                id="prob-graph-overlay",
                                className="panel-loading-overlay",
                                style=_OVERLAY_HIDDEN_STYLE,
                                children=[
                                    html.Div(
                                        "Generando gráfica...",
                                        className="panel-loading-overlay-text",
                                    )
                                ],
                            ),
                            html.Div(
                                initial_probability_text,
                                id="probability-text",
                                className="probability-title",
                                style={
                                    "color": "#000000",
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontWeight": "700",
                                },
                            ),
                            html.Div(
                                id="prob-graph-fig-container",
                                className="probability-figure-container",
                                style={
                                    "position": "relative",
                                    "backgroundColor": "#FFFFFF",
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "color": CHEC_GREEN,
                                    "fontWeight": "700",
                                },
                                children=initial_graph_children,
                            ),
                        ],
                    ),
                ],
            ),
            dcc.Store(id="prob-last-graph-file"),
            dcc.Download(id="prob-download-file"),
            *dummy_divs,
        ],
        className="probability-page",
        style={"width": "100%", "display": "flex", "flexDirection": "column"},
    )


def register_callbacks(app: Dash, settings: Settings) -> None:
    @app.callback(
        Output("prob-select-criteria", "options"),
        Output("prob-select-criteria", "disabled"),
        Output("probability-text", "children", allow_duplicate=True),
        Output("prob-graph-fig-container", "children", allow_duplicate=True),
        Output("prob-options-load-interval", "disabled"),
        Input("prob-options-load-interval", "n_intervals"),
        prevent_initial_call=True,
    )
    def load_probability_options_after_render(n_intervals: int | None):
        global selection_criteria
        global last_confirm_clicks
        if n_intervals is None:
            raise exceptions.PreventUpdate

        try:
            options_payload = fetch_probability_options()
            main_options = options_payload.get("criteria_options", [])
            selection_criteria = [
                "",
                ["", "", "", ""],
                ["", "", "", ""],
                ["", "", "", ""],
                ["", "", "", ""],
                "",
            ]
            last_confirm_clicks = -1
            return (
                main_options,
                False,
                "P(X|Y1,Y2,Y3,...,YN)",
                "Selecciona criterios y presiona OK para generar la distribución.",
                True,
            )
        except Exception as exc:
            return (
                [],
                True,
                "Datos no disponibles",
                _api_error_block(
                    f"No fue posible cargar los datos requeridos: {exc}",
                    font_size="16px",
                ),
                True,
            )

    @app.callback(
        Output("prob-sub-criteria-1-container", "children"),
        Output("prob-sub-criteria-2-container", "children"),
        Output("prob-sub-criteria-3-container", "children"),
        Output("prob-sub-criteria-4-container", "children"),
        Output("prob-target-variable-container", "children"),
        Output("prob-sub-criteria-1-filters-container", "children", allow_duplicate=True),
        Output("prob-sub-criteria-2-filters-container", "children", allow_duplicate=True),
        Output("prob-sub-criteria-3-filters-container", "children", allow_duplicate=True),
        Output("prob-sub-criteria-4-filters-container", "children", allow_duplicate=True),
        Input("prob-select-criteria", "value"),
        prevent_initial_call=True,
    )
    def select_main_criteria(select_criteria_value: str):
        global selection_criteria
        if not select_criteria_value:
            selection_criteria = ["", ["", "", "", ""], ["", "", "", ""], ["", "", "", ""], ["", "", "", ""], ""]
            return [None] * 9

        try:
            columns = _columns_for_criteria(select_criteria_value)
        except Exception as exc:
            selection_criteria = ["", ["", "", "", ""], ["", "", "", ""], ["", "", "", ""], ["", "", "", ""], ""]
            return None, None, None, None, _api_error_block(str(exc)), None, None, None, None

        selection_criteria[0] = select_criteria_value
        selection_criteria[1:5] = [["", "", "", ""] for _ in range(4)]
        selection_criteria[5] = ""

        outputs = [
            _create_dropdown(f"prob-select-subcriteria-{i}", columns, 900 - (i - 1) * 100, "")
            for i in range(1, 5)
        ]
        outputs.append(_create_dropdown("prob-select-target", columns, 500, ""))
        outputs.extend([None] * 4)
        return outputs

    def create_subcriteria_callback_factory(index: int) -> None:
        @app.callback(
            Output(f"prob-sub-criteria-{index}-filters-container", "children"),
            Input(f"prob-select-subcriteria-{index}", "value"),
            State("prob-select-criteria", "value"),
            prevent_initial_call=True,
        )
        def generate_filter_ui(selected_column: str, main_criteria: str):
            if not selected_column:
                selection_criteria[index] = ["", "", "", ""]
                return None

            try:
                previous_filters = selection_criteria[1:index]
                payload = fetch_probability_metadata(
                    action="filter_options",
                    criteria=main_criteria,
                    selected_column=selected_column,
                    previous_filters=previous_filters,
                )
            except Exception as exc:
                return _api_error_block(str(exc), font_size="13px")

            filter_kind = payload.get("filter_kind", "")
            selection_criteria[index] = [filter_kind, selected_column, "", ""]
            z_index = 850 - (index - 1) * 100
            return _create_filter_components(
                filter_kind=filter_kind,
                value_options=payload.get("value_options", []),
                z_index=z_index,
                component_prefix=f"prob-select-subcriteria-{index}",
                empty_message=payload.get("message") if payload.get("is_empty", False) else None,
            )

        if index < 4:
            outputs_to_reset: list[Output] = []
            for next_index in range(index + 1, 5):
                outputs_to_reset.append(
                    Output(f"prob-sub-criteria-{next_index}-container", "children", allow_duplicate=True)
                )
                outputs_to_reset.append(
                    Output(
                        f"prob-sub-criteria-{next_index}-filters-container",
                        "children",
                        allow_duplicate=True,
                    )
                )
            outputs_to_reset.append(
                Output("prob-target-variable-container", "children", allow_duplicate=True)
            )

            def get_reset_values(main_criteria: str):
                for reset_idx in range(index + 1, 5):
                    selection_criteria[reset_idx] = ["", "", "", ""]
                selection_criteria[5] = ""

                try:
                    columns = _columns_for_criteria(main_criteria)
                except Exception:
                    columns = []

                return_values = []
                for next_index in range(index + 1, 5):
                    return_values.append(
                        _create_dropdown(
                            f"prob-select-subcriteria-{next_index}",
                            columns,
                            900 - (next_index - 1) * 100,
                            "",
                        )
                    )
                    return_values.append(None)
                return_values.append(_create_dropdown("prob-select-target", columns, 500, ""))
                return return_values

            @app.callback(
                outputs_to_reset,
                Input(f"prob-select-subcriteria-{index}-1", "value"),
                State("prob-select-criteria", "value"),
                prevent_initial_call=True,
            )
            def reset_cascade_from_val1(value, main_criteria):
                if value in ("", None):
                    raise exceptions.PreventUpdate
                return get_reset_values(main_criteria)

            @app.callback(
                outputs_to_reset,
                Input(f"prob-select-subcriteria-{index}-2", "value"),
                State("prob-select-criteria", "value"),
                prevent_initial_call=True,
            )
            def reset_cascade_from_val2(value, main_criteria):
                if value in ("", None):
                    raise exceptions.PreventUpdate
                return get_reset_values(main_criteria)

        @app.callback(
            Output(f"prob-dummy-output-{index}-1", "children"),
            Input(f"prob-select-subcriteria-{index}-1", "value"),
            prevent_initial_call=True,
        )
        def update_value1(value):
            selection_criteria[index][2] = value if value is not None else ""
            return f"updated-{time.time()}"

        @app.callback(
            Output(f"prob-dummy-output-{index}-2", "children"),
            Input(f"prob-select-subcriteria-{index}-2", "value"),
            prevent_initial_call=True,
        )
        def update_value2(value):
            selection_criteria[index][3] = value if value is not None else ""
            return f"updated-{time.time()}"

    for idx in range(1, 5):
        create_subcriteria_callback_factory(idx)

    @app.callback(
        Output("prob-dummy-output-target", "children"),
        Input("prob-select-target", "value"),
        prevent_initial_call=True,
    )
    def update_target_variable(value):
        selection_criteria[5] = value or ""
        return f"updated-{time.time()}"

    @app.callback(
        Output("probability-text", "children"),
        Output("prob-graph-fig-container", "children"),
        Output("prob-last-graph-file", "data"),
        Input("prob-confirm-button-ok", "n_clicks"),
        running=[
            (Output("prob-graph-overlay", "style"), _OVERLAY_VISIBLE_STYLE, _OVERLAY_HIDDEN_STYLE),
            (Output("prob-confirm-button-ok", "disabled"), True, False),
        ],
    )
    def confirm_and_generate_graph(n_clicks: int | None):
        global last_confirm_clicks
        if n_clicks is None or n_clicks <= last_confirm_clicks:
            raise exceptions.PreventUpdate
        last_confirm_clicks = n_clicks

        if not selection_criteria[0] or not selection_criteria[5]:
            return (
                "Selecciona criterio principal y variable objetivo.",
                "Completa los campos requeridos para generar la gráfica.",
                None,
            )

        try:
            payload = fetch_probability_data(
                criteria=selection_criteria[0],
                target_column=selection_criteria[5],
                filters=selection_criteria[1:5],
            )
        except Exception as exc:
            return (
                "Error de API.",
                str(exc),
                None,
        )

        probability_text = payload.get("probability_text", "P(X|Y)")
        status_text = payload.get("status_text", "Sin información disponible.")
        graph_name = payload.get("graph_name")
        graph_data_uri = payload.get("graph_data_uri")
        if not graph_name and not graph_data_uri:
            return probability_text, status_text, None

        graph_component = _build_probability_graph_component(
            graph_name=graph_name or "probability_graph.png",
            graph_data_uri=graph_data_uri,
        )
        return probability_text, graph_component, {
            "graph_name": graph_name,
            "graph_data_uri": graph_data_uri,
        }

    @app.callback(
        Output("prob-download-file", "data"),
        Input("probability-save-button", "n_clicks"),
        State("prob-last-graph-file", "data"),
        prevent_initial_call=True,
    )
    def download_graph(n_clicks: int | None, graph_state: dict[str, Any] | None):
        if n_clicks is None or n_clicks <= 0 or not graph_state:
            raise exceptions.PreventUpdate
        graph_name = graph_state.get("graph_name")
        graph_data_uri = graph_state.get("graph_data_uri")
        if graph_data_uri:
            if "," in graph_data_uri:
                _, encoded_image = graph_data_uri.split(",", 1)
            else:
                encoded_image = graph_data_uri

            def _write_image(buffer):
                buffer.write(base64.b64decode(encoded_image))

            return dcc.send_bytes(_write_image, filename=graph_name or "probability_graph.png")
        if not graph_name:
            raise exceptions.PreventUpdate
        file_path = settings.output_dir / graph_name
        if not file_path.exists():
            raise exceptions.PreventUpdate
        return dcc.send_file(file_path)
