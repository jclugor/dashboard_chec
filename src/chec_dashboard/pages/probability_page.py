import time
from typing import Any

from dash import Dash, Input, Output, State, dcc, html
from dash import exceptions
import pandas as pd

from chec_dashboard.config import Settings
from chec_dashboard.services.probability_service import (
    ProbabilityDataset,
    apply_filters,
    criteria_options,
    generate_probability_graph,
    get_dataframe_by_criteria,
    infer_filter_type,
    load_probability_dataset,
)


CHEC_GREEN = "#00782b"
CHEC_BUTTON_GREEN = "#11BB52CF"

selection_criteria: list[Any] = [
    [""],
    ["", "", "", ""],
    ["", "", "", ""],
    ["", "", "", ""],
    ["", "", "", ""],
    "",
]
last_confirm_clicks = -1


def _dataset(settings: Settings) -> ProbabilityDataset:
    return load_probability_dataset(str(settings.data_dir))


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
    filter_type_name: str,
    column_data: Any,
    z_index: int,
    component_prefix: str,
) -> list[html.Div] | html.Div | None:
    base_text_style = {
        "color": "white",
        "textAlign": "center",
        "fontSize": "130%",
        "fontWeight": "700",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "center",
    }

    if column_data.empty:
        return html.Div(
            "No hay opciones con filtros previos.",
            style={**base_text_style, "width": "100%", "fontSize": "18px"},
        )

    if filter_type_name in ["object", "int64", "int32"]:
        options = sorted(list(column_data.dropna().unique()))
        return [
            html.Div("Seleccion:", style={**base_text_style, "width": "20%"}),
            html.Div(
                dcc.Dropdown(
                    id=f"{component_prefix}-1",
                    options=[""] + options,
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
                style={
                    "width": "50%",
                    "backgroundColor": "white",
                    "borderRadius": "5px",
                    "marginLeft": "9%",
                },
            ),
        ]

    if filter_type_name in ["float32", "float64"]:
        return [
            html.Div(
                "Operador:",
                style={**base_text_style, "width": "20%", "fontSize": "131%", "margin": "0 0 0 2%"},
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
                style={
                    "width": "20%",
                    "backgroundColor": "white",
                    "borderRadius": "5px",
                    "margin": "0 0 0 8%",
                },
            ),
            html.Div("Valor:", style={**base_text_style, "width": "20%"}),
            html.Div(
                dcc.Input(
                    id=f"{component_prefix}-2",
                    type="number",
                    placeholder="Ingresa un valor",
                    style={
                        "width": "91%",
                        "height": "77%",
                        "border": "none",
                        "color": CHEC_GREEN,
                        "fontSize": "20px",
                        "transform": "translate(1%, 11%)",
                    },
                ),
                style={"width": "20%", "backgroundColor": "white", "borderRadius": "5px"},
            ),
        ]

    if "datetime" in filter_type_name or "period" in filter_type_name:
        options = list(
            sorted(
                set(
                    pd.to_datetime(d, errors="coerce").strftime("%Y-%m-%d")
                    for d in column_data.dropna().unique()
                )
            )
        )
        return [
            html.Div("Desde:", style={**base_text_style, "width": "20%"}),
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
                style={
                    "width": "20%",
                    "backgroundColor": "white",
                    "borderRadius": "5px",
                    "margin": "0 0 0 3%",
                },
            ),
            html.Div("Hasta:", style={**base_text_style, "width": "20%", "margin": "0 0 0 3%"}),
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
                style={
                    "width": "20%",
                    "backgroundColor": "white",
                    "borderRadius": "5px",
                    "margin": "0 0 0 3%",
                },
            ),
        ]

    return None


def get_layout() -> html.Div:
    main_options = criteria_options()
    dummy_divs = [
        html.Div(id=f"prob-dummy-output-{i}-{j}", style={"display": "none"})
        for i in range(1, 5)
        for j in range(1, 3)
    ]
    dummy_divs.append(html.Div(id="prob-dummy-output-target", style={"display": "none"}))

    return html.Div(
        [
            html.Div(
                className="workspace-row",
                style={
                    "width": "98%",
                    "height": "100%",
                    "display": "flex",
                    "flexDirection": "row",
                    "alignItems": "center",
                },
                children=[
                    html.Div(
                        className="criteria-container",
                        style={
                            "position": "relative",
                            "width": "30%",
                            "height": "97%",
                            "backgroundColor": "#16D622",
                            "margin": "0 0 0 1.5%",
                            "borderRadius": "10px",
                            "opacity": "0.7",
                            "display": "flex",
                            "flexDirection": "column",
                            "alignItems": "center",
                            "justifyContent": "flex-start",
                            "padding": "0.8vh 0 0.8vh 0",
                        },
                        children=[
                            html.Div(
                                "Criterio",
                                style={
                                    "width": "100%",
                                    "height": "5%",
                                    "color": "#FFFFFF",
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontSize": "22px",
                                    "fontWeight": "700",
                                    "textAlign": "center",
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "margin": "1vh 0 0 0",
                                },
                            ),
                            html.Div(
                                style={"width": "70%", "height": "4%", "borderRadius": "5px"},
                                children=[
                                    dcc.Dropdown(
                                        id="prob-select-criteria",
                                        options=main_options,
                                        value="",
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
                                style={
                                    "margin": "1% 0 0 0",
                                    "width": "100%",
                                    "height": "16%",
                                    "display": "flex",
                                    "flexDirection": "column",
                                    "alignItems": "center",
                                },
                                children=[
                                    html.Div(
                                        "Sub-criterio 1",
                                        style={
                                            "width": "100%",
                                            "height": "28%",
                                            "color": "#FFFFFF",
                                            "fontFamily": "'DM Sans', sans-serif",
                                            "fontSize": "21px",
                                            "fontWeight": "700",
                                            "textAlign": "center",
                                            "display": "flex",
                                            "alignItems": "center",
                                            "justifyContent": "center",
                                            "margin": "3% 0 0 0",
                                        },
                                    ),
                                    html.Div(id="prob-sub-criteria-1-container", style={"width": "70%", "height": "28%", "borderRadius": "5px", "backgroundColor": "white"}),
                                    html.Div(id="prob-sub-criteria-1-filters-container", style={"width": "100%", "height": "28%", "display": "flex", "flexDirection": "row", "alignItems": "center", "justifyContent": "center", "margin": "3% 0 0 0"}),
                                ],
                            ),
                            html.Div(
                                style={"margin": "1% 0 0 0", "width": "100%", "height": "16%", "display": "flex", "flexDirection": "column", "alignItems": "center"},
                                children=[
                                    html.Div("Sub-criterio 2", style={"width": "100%", "height": "28%", "color": "#FFFFFF", "fontFamily": "'DM Sans', sans-serif", "fontSize": "21px", "fontWeight": "700", "textAlign": "center", "display": "flex", "alignItems": "center", "justifyContent": "center", "margin": "3% 0 0 0"}),
                                    html.Div(id="prob-sub-criteria-2-container", style={"width": "70%", "height": "28%", "borderRadius": "5px", "backgroundColor": "white"}),
                                    html.Div(id="prob-sub-criteria-2-filters-container", style={"width": "100%", "height": "28%", "display": "flex", "flexDirection": "row", "alignItems": "center", "justifyContent": "center", "margin": "3% 0 0 0"}),
                                ],
                            ),
                            html.Div(
                                style={"margin": "1% 0 0 0", "width": "100%", "height": "16%", "display": "flex", "flexDirection": "column", "alignItems": "center"},
                                children=[
                                    html.Div("Sub-criterio 3", style={"width": "100%", "height": "28%", "color": "#FFFFFF", "fontFamily": "'DM Sans', sans-serif", "fontSize": "21px", "fontWeight": "700", "textAlign": "center", "display": "flex", "alignItems": "center", "justifyContent": "center", "margin": "3% 0 0 0"}),
                                    html.Div(id="prob-sub-criteria-3-container", style={"width": "70%", "height": "28%", "borderRadius": "5px", "backgroundColor": "white"}),
                                    html.Div(id="prob-sub-criteria-3-filters-container", style={"width": "100%", "height": "28%", "display": "flex", "flexDirection": "row", "alignItems": "center", "justifyContent": "center", "margin": "3% 0 0 0"}),
                                ],
                            ),
                            html.Div(
                                style={"margin": "1% 0 0 0", "width": "100%", "height": "16%", "display": "flex", "flexDirection": "column", "alignItems": "center"},
                                children=[
                                    html.Div("Sub-criterio 4", style={"width": "100%", "height": "28%", "color": "#FFFFFF", "fontFamily": "'DM Sans', sans-serif", "fontSize": "21px", "fontWeight": "700", "textAlign": "center", "display": "flex", "alignItems": "center", "justifyContent": "center", "margin": "3% 0 0 0"}),
                                    html.Div(id="prob-sub-criteria-4-container", style={"width": "70%", "height": "28%", "borderRadius": "5px", "backgroundColor": "white"}),
                                    html.Div(id="prob-sub-criteria-4-filters-container", style={"width": "100%", "height": "28%", "display": "flex", "flexDirection": "row", "alignItems": "center", "justifyContent": "center", "margin": "3% 0 0 0"}),
                                ],
                            ),
                            html.Div(
                                style={"width": "100%", "height": "12%", "display": "flex", "flexDirection": "column", "alignItems": "center", "margin": "1vh 0 0 0"},
                                children=[
                                    html.Div("Variable objetivo", style={"width": "100%", "height": "28%", "color": "#FFFFFF", "fontFamily": "'DM Sans', sans-serif", "fontSize": "21px", "fontWeight": "700", "textAlign": "center", "display": "flex", "alignItems": "center", "justifyContent": "center"}),
                                    html.Div(
                                        style={"display": "flex", "width": "100%", "flexDirection": "row", "alignItems": "center", "margin": "1% 0 0 0", "height": "48%"},
                                        children=[
                                            html.Div(id="prob-target-variable-container", style={"width": "70%", "height": "89%", "borderRadius": "5px", "backgroundColor": "white", "left": "6%", "position": "relative"}),
                                            html.Button(
                                                "OK",
                                                id="prob-confirm-button-ok",
                                                n_clicks=0,
                                                style={
                                                    "fontFamily": "'DM Sans', sans-serif",
                                                    "fontSize": "16px",
                                                    "fontWeight": "700",
                                                    "color": "black",
                                                    "cursor": "pointer",
                                                    "borderRadius": "3px",
                                                    "borderColor": "white",
                                                    "width": "12%",
                                                    "height": "100%",
                                                    "backgroundColor": CHEC_BUTTON_GREEN,
                                                    "position": "relative",
                                                    "right": "-12%",
                                                    "top": "9%",
                                                },
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                    html.Div(
                        className="graph-container",
                        style={
                            "position": "relative",
                            "width": "65.5%",
                            "height": "97%",
                            "backgroundColor": "#28DB7F",
                            "margin": "0 0 0 1.5%",
                            "borderRadius": "10px",
                            "display": "flex",
                            "flexDirection": "column",
                            "alignItems": "center",
                        },
                        children=[
                            html.Div(
                                "P(X|Y1,Y2,Y3,...,YN)",
                                id="probability-text",
                                style={
                                    "width": "100%",
                                    "height": "10%",
                                    "color": "#000000",
                                    "fontFamily": "'Poppins', sans-serif",
                                    "fontSize": "3vh",
                                    "fontWeight": "700",
                                    "textAlign": "center",
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                },
                            ),
                            html.Div(
                                id="prob-graph-fig-container",
                                style={
                                    "position": "relative",
                                    "width": "90%",
                                    "height": "85%",
                                    "backgroundColor": "#FFFFFF",
                                    "borderRadius": "10px",
                                    "display": "flex",
                                    "alignItems": "center",
                                    "justifyContent": "center",
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "color": CHEC_GREEN,
                                    "fontWeight": "700",
                                },
                                children="Selecciona criterios y presiona OK para generar la distribucion.",
                            ),
                        ],
                    ),
                ],
            ),
            dcc.Store(id="prob-last-graph-file"),
            dcc.Download(id="prob-download-file"),
            *dummy_divs,
        ],
        style={"width": "100%", "height": "100%", "display": "flex", "flexDirection": "column"},
    )


def register_callbacks(app: Dash, settings: Settings) -> None:
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
        try:
            dataset = _dataset(settings)
        except Exception as exc:
            selection_criteria = [[""], ["", "", "", ""], ["", "", "", ""], ["", "", "", ""], ["", "", "", ""], ""]
            error_msg = html.Div(
                str(exc),
                style={
                    "padding": "6px",
                    "fontFamily": "'DM Sans', sans-serif",
                    "fontWeight": "700",
                    "color": "#a10c0c",
                    "fontSize": "14px",
                },
            )
            return None, None, None, None, error_msg, None, None, None, None
        selected_df = get_dataframe_by_criteria(dataset, select_criteria_value)
        if selected_df is None:
            selection_criteria = [[""], ["", "", "", ""], ["", "", "", ""], ["", "", "", ""], ["", "", "", ""], ""]
            return [None] * 9

        selection_criteria[0] = select_criteria_value
        selection_criteria[1:5] = [["", "", "", ""] for _ in range(4)]
        selection_criteria[5] = ""

        columns = selected_df.columns.to_list()
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
                dataset = _dataset(settings)
            except Exception as exc:
                return html.Div(
                    str(exc),
                    style={
                        "padding": "4px",
                        "fontFamily": "'DM Sans', sans-serif",
                        "fontWeight": "700",
                        "color": "#a10c0c",
                        "fontSize": "13px",
                    },
                )
            source_df = get_dataframe_by_criteria(dataset, main_criteria)
            if source_df is None:
                return None

            previous_filters = selection_criteria[1:index]
            filtered_data = apply_filters(source_df, previous_filters)
            if selected_column not in filtered_data.columns:
                return None

            column_data = filtered_data[selected_column]
            filter_type_name = column_data.dtype.name
            crit_type = infer_filter_type(filter_type_name)
            selection_criteria[index] = [crit_type, selected_column, "", ""]
            z_index = 850 - (index - 1) * 100
            return _create_filter_components(
                filter_type_name, column_data, z_index, f"prob-select-subcriteria-{index}"
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
                    dataset = _dataset(settings)
                except Exception:
                    dataset = None
                source_df = (
                    get_dataframe_by_criteria(dataset, main_criteria)
                    if dataset is not None
                    else None
                )
                columns = source_df.columns.to_list() if source_df is not None else []

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
    )
    def confirm_and_generate_graph(n_clicks: int | None):
        global last_confirm_clicks
        if n_clicks is None or n_clicks <= last_confirm_clicks:
            raise exceptions.PreventUpdate
        last_confirm_clicks = n_clicks

        if not selection_criteria[0] or not selection_criteria[5]:
            return (
                "Selecciona criterio principal y variable objetivo.",
                "Completa los campos requeridos para generar la grafica.",
                None,
            )

        try:
            dataset = _dataset(settings)
        except Exception as exc:
            return "Error cargando datos.", str(exc), None
        source_df = get_dataframe_by_criteria(dataset, selection_criteria[0])
        if source_df is None:
            return "Criterio no valido.", "No se pudo cargar el dataset seleccionado.", None

        filtered_df = apply_filters(source_df, selection_criteria[1:5])
        if filtered_df.empty:
            return (
                "Sin datos tras aplicar filtros.",
                "No hay registros para la combinacion seleccionada.",
                None,
            )

        parts = [f"P({selection_criteria[5]} | {selection_criteria[0]}"]
        for filter_type, name, value_1, value_2 in selection_criteria[1:5]:
            if not all([filter_type, name, value_1]):
                continue
            if filter_type == "seleccion":
                parts.append(f"{name} = {value_1}")
            elif filter_type == "rango_num" and value_2 is not None:
                parts.append(f"{name} {value_1} {value_2}")
            elif filter_type == "fecha" and value_2:
                parts.append(f"{name} {value_1} - {value_2}")
        probability_text = ", ".join(parts) + ")"

        try:
            graph_path = generate_probability_graph(
                filtered_df,
                target_column=selection_criteria[5],
                probability_text=probability_text,
                output_dir=settings.output_dir,
            )
        except Exception as exc:
            return (
                "Error al generar grafica.",
                f"No fue posible crear la distribucion: {str(exc)}",
                None,
            )

        timestamp = int(time.time())
        graph_src = f"/outputs/{graph_path.name}?v={timestamp}"
        graph_component = html.Div(
            [
                html.Img(src=graph_src, style={"width": "100%", "borderRadius": "10px"}),
                html.Button(
                    id="probability-save-button",
                    n_clicks=0,
                    style={
                        "width": "5vh",
                        "position": "absolute",
                        "height": "5vh",
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
            style={"position": "relative", "width": "100%", "height": "100%"},
        )
        return probability_text, graph_component, graph_path.name

    @app.callback(
        Output("prob-download-file", "data"),
        Input("probability-save-button", "n_clicks"),
        State("prob-last-graph-file", "data"),
        prevent_initial_call=True,
    )
    def download_graph(n_clicks: int | None, graph_name: str | None):
        if n_clicks is None or n_clicks <= 0 or not graph_name:
            raise exceptions.PreventUpdate
        file_path = settings.output_dir / graph_name
        if not file_path.exists():
            raise exceptions.PreventUpdate
        return dcc.send_file(file_path)
