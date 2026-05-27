from __future__ import annotations

from typing import Any

from dash import Dash, Input, Output, State, dcc, html
from dash import ctx, exceptions

from chec_dashboard.config import Settings
from chec_dashboard.dash_app.api_client import (
    fetch_chatbot_assessment,
    fetch_chatbot_context_options,
    fetch_chatbot_status,
    fetch_map_circuit_options,
    fetch_map_options,
)


CHEC_GREEN = "#00782b"


def _dropdown_options(values: list[Any]) -> list[dict[str, str]]:
    return [{"label": str(value), "value": str(value)} for value in values if value is not None]


def _real_circuit_options(values: list[Any]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        circuit = str(value).strip()
        if not circuit or circuit.casefold() == "todos" or circuit in seen:
            continue
        options.append({"label": circuit, "value": circuit})
        seen.add(circuit)
    return options


def _find_context_item(items: list[dict[str, Any]], item_id: str | None) -> dict[str, Any] | None:
    if not item_id:
        return None
    for item in items or []:
        if item.get("id") == item_id:
            return item
    return None


def _status_class(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "chatbot-status chatbot-status-warning"
    if payload.get("ready"):
        return "chatbot-status chatbot-status-ready"
    return "chatbot-status chatbot-status-warning"


def _context_summary_component(item: dict[str, Any] | None):
    if not item:
        return html.Div("Selecciona un evento o elemento de red.", className="chatbot-empty-state")
    context = item.get("context") or {}
    key_values = [
        ("Tipo", "Evento" if item.get("kind") == "event" else "Elemento de red"),
        ("Resumen", item.get("summary")),
        ("Circuito", context.get("cto_equi_ope") or context.get("circuito") or context.get("FPARENT")),
        ("Municipio", context.get("MUN") or context.get("municipio")),
        ("Equipo", context.get("equipo_ope") or context.get("CODE") or context.get("display_label")),
        ("Indicadores", f"SAIDI {context.get('SAIDI') or context.get('severity_saidi') or 'N/D'} / SAIFI {context.get('SAIFI') or context.get('severity_saifi') or 'N/D'}"),
    ]
    rows = [
        html.Div(
            [html.Span(label, className="chatbot-context-key"), html.Span(str(value), className="chatbot-context-value")],
            className="chatbot-context-row",
        )
        for label, value in key_values
        if value not in {None, ""}
    ]
    return html.Div(rows, className="chatbot-context-summary")


def _citations_component(citations: list[dict[str, Any]] | None):
    if not citations:
        return html.Div("Sin citas disponibles.", className="chatbot-empty-state")
    return html.Div(
        [
            html.Div(
                [
                    html.Div(f"[{index}] {citation.get('title', 'Documento técnico')}", className="chatbot-citation-title"),
                    html.Div(citation.get("source_path") or "Fuente local", className="chatbot-citation-source"),
                    html.Div(str(citation.get("snippet") or "")[:420], className="chatbot-citation-snippet"),
                ],
                className="chatbot-citation",
            )
            for index, citation in enumerate(citations, start=1)
        ],
        className="chatbot-citations-list",
    )


def get_layout(settings: Settings) -> html.Div:
    _ = settings
    return html.Div(
        [
            dcc.Interval(id="chatbot-load-interval", interval=300, n_intervals=0, max_intervals=1),
            dcc.Store(id="chatbot-context-items-store", data=[]),
            dcc.Store(id="chatbot-selected-context-store", data={}),
            html.Div(
                [
                    html.Div(
                        [
                            html.H2("Asistente técnico", className="chatbot-title"),
                            html.Div(
                                "Selecciona un evento o elemento de red para evaluar su estado con documentos técnicos.",
                                className="chatbot-subtitle",
                            ),
                            html.Div(id="chatbot-status-banner", className="chatbot-status chatbot-status-warning"),
                        ],
                        className="chatbot-header",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("TIPO DE CONTEXTO", className="chatbot-filter-label"),
                                    dcc.Dropdown(
                                        id="chatbot-context-kind",
                                        options=[
                                            {"label": "Evento", "value": "event"},
                                            {"label": "Elemento de red", "value": "asset"},
                                        ],
                                        value="event",
                                        clearable=False,
                                        className="chatbot-dropdown",
                                    ),
                                ],
                                className="chatbot-filter-field",
                            ),
                            html.Div(
                                [
                                    html.Label("PERÍODO", className="chatbot-filter-label"),
                                    dcc.Dropdown(id="chatbot-select-period", options=[], disabled=True, className="chatbot-dropdown"),
                                ],
                                className="chatbot-filter-field",
                            ),
                            html.Div(
                                [
                                    html.Label("MUNICIPIO", className="chatbot-filter-label"),
                                    dcc.Dropdown(id="chatbot-select-municipio", options=[], disabled=True, className="chatbot-dropdown"),
                                ],
                                className="chatbot-filter-field",
                            ),
                            html.Div(
                                [
                                    html.Label("CIRCUITOS", className="chatbot-filter-label"),
                                    dcc.Dropdown(
                                        id="chatbot-select-circuits",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="Todos los circuitos",
                                        disabled=True,
                                        className="chatbot-dropdown",
                                    ),
                                ],
                                className="chatbot-filter-field chatbot-filter-field-wide",
                            ),
                            html.Div(
                                [
                                    html.Label("BÚSQUEDA", className="chatbot-filter-label"),
                                    dcc.Input(
                                        id="chatbot-search-input",
                                        type="text",
                                        placeholder="Equipo, causa, circuito...",
                                        className="chatbot-search-input",
                                    ),
                                ],
                                className="chatbot-filter-field chatbot-filter-field-wide",
                            ),
                            html.Button("BUSCAR CONTEXTO", id="chatbot-search-button", n_clicks=0, className="chatbot-primary-button"),
                        ],
                        className="chatbot-filter-panel",
                    ),
                    html.Div(id="chatbot-context-status", className="chatbot-inline-status"),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("EVENTO O ELEMENTO", className="chatbot-filter-label"),
                                    dcc.Dropdown(
                                        id="chatbot-context-select",
                                        options=[],
                                        placeholder="Busca y selecciona un contexto",
                                        disabled=True,
                                        className="chatbot-dropdown",
                                    ),
                                    html.Div(id="chatbot-context-summary", className="chatbot-context-summary-shell"),
                                ],
                                className="chatbot-left-pane",
                            ),
                            html.Div(
                                [
                                    html.Label("PREGUNTA ADICIONAL", className="chatbot-filter-label"),
                                    dcc.Textarea(
                                        id="chatbot-question",
                                        placeholder="Ej: ¿qué condiciones podrían explicar estos indicadores?",
                                        className="chatbot-question-input",
                                    ),
                                    html.Button("ANALIZAR", id="chatbot-assess-button", n_clicks=0, className="chatbot-primary-button"),
                                    html.Div(id="chatbot-assessment-status", className="chatbot-inline-status"),
                                    html.Div(
                                        [
                                            html.H3("Análisis", className="chatbot-panel-title"),
                                            html.Div(id="chatbot-answer", className="chatbot-answer"),
                                            html.H3("Citas", className="chatbot-panel-title"),
                                            html.Div(id="chatbot-citations", className="chatbot-citations"),
                                        ],
                                        className="chatbot-answer-panel",
                                    ),
                                ],
                                className="chatbot-right-pane",
                            ),
                        ],
                        className="chatbot-workspace-row",
                    ),
                ],
                className="chatbot-page-inner",
            ),
        ],
        className="chatbot-page",
    )


def register_callbacks(app: Dash, settings: Settings) -> None:
    _ = settings

    @app.callback(
        Output("chatbot-status-banner", "children"),
        Output("chatbot-status-banner", "className"),
        Output("chatbot-select-period", "options"),
        Output("chatbot-select-period", "value"),
        Output("chatbot-select-period", "disabled"),
        Output("chatbot-select-municipio", "options"),
        Output("chatbot-select-municipio", "value"),
        Output("chatbot-select-municipio", "disabled"),
        Output("chatbot-load-interval", "disabled"),
        Input("chatbot-load-interval", "n_intervals"),
        prevent_initial_call=True,
    )
    def load_chatbot_options(n_intervals: int | None):
        _ = n_intervals
        status = fetch_chatbot_status()
        options = fetch_map_options()
        dates = options.get("dates", [])
        municipios = options.get("municipios", [])
        return (
            status.get("message", "Estado del asistente no disponible."),
            _status_class(status),
            _dropdown_options(dates),
            options.get("default_date"),
            not bool(dates),
            _dropdown_options(municipios),
            options.get("default_municipio"),
            not bool(municipios),
            True,
        )

    @app.callback(
        Output("chatbot-select-circuits", "options"),
        Output("chatbot-select-circuits", "value"),
        Output("chatbot-select-circuits", "disabled"),
        Input("chatbot-select-period", "value"),
        Input("chatbot-select-municipio", "value"),
        prevent_initial_call=True,
    )
    def load_chatbot_circuits(selected_period: str | None, selected_municipio: str | None):
        if not selected_period or not selected_municipio:
            return [], [], True
        payload = fetch_map_circuit_options(selected_period, selected_municipio)
        options = _real_circuit_options(payload.get("circuits", []))
        return options, [], not bool(options)

    @app.callback(
        Output("chatbot-context-select", "options"),
        Output("chatbot-context-select", "value"),
        Output("chatbot-context-select", "disabled"),
        Output("chatbot-context-items-store", "data"),
        Output("chatbot-context-status", "children"),
        Input("chatbot-search-button", "n_clicks"),
        State("chatbot-context-kind", "value"),
        State("chatbot-select-period", "value"),
        State("chatbot-select-municipio", "value"),
        State("chatbot-select-circuits", "value"),
        State("chatbot-search-input", "value"),
        prevent_initial_call=True,
    )
    def search_contexts(
        n_clicks: int | None,
        context_kind: str | None,
        selected_period: str | None,
        selected_municipio: str | None,
        selected_circuits: list[str] | None,
        search: str | None,
    ):
        if not n_clicks:
            raise exceptions.PreventUpdate
        if not selected_period or not selected_municipio:
            return [], None, True, [], "Selecciona período y municipio antes de buscar."
        payload = fetch_chatbot_context_options(
            context_kind=context_kind or "event",
            selected_period=selected_period,
            selected_municipio=selected_municipio,
            selected_circuits=selected_circuits or None,
            search=search,
            limit=50,
        )
        items = payload.get("items", [])
        options = [{"label": item["label"], "value": item["id"]} for item in items]
        value = items[0]["id"] if items else None
        return options, value, not bool(items), items, payload.get("status_text", "")

    @app.callback(
        Output("chatbot-context-summary", "children"),
        Output("chatbot-selected-context-store", "data"),
        Input("chatbot-context-select", "value"),
        State("chatbot-context-items-store", "data"),
        prevent_initial_call=True,
    )
    def select_context(selected_context_id: str | None, context_items: list[dict[str, Any]] | None):
        item = _find_context_item(context_items or [], selected_context_id)
        if not item:
            return _context_summary_component(None), {}
        return _context_summary_component(item), item.get("context") or {}

    @app.callback(
        Output("chatbot-answer", "children"),
        Output("chatbot-citations", "children"),
        Output("chatbot-assessment-status", "children"),
        Input("chatbot-assess-button", "n_clicks"),
        State("chatbot-selected-context-store", "data"),
        State("chatbot-question", "value"),
        prevent_initial_call=True,
    )
    def assess_context(n_clicks: int | None, selected_context: dict[str, Any] | None, question: str | None):
        if not n_clicks:
            raise exceptions.PreventUpdate
        if not selected_context:
            return (
                "Selecciona un evento o elemento de red antes de analizar.",
                _citations_component([]),
                "Falta contexto seleccionado.",
            )
        payload = fetch_chatbot_assessment(selected_context=selected_context, question=question)
        answer = dcc.Markdown(payload.get("answer") or "Sin respuesta.", className="chatbot-answer-markdown")
        citations = _citations_component(payload.get("citations", []))
        status_text = payload.get("status_text", "")
        return answer, citations, status_text
