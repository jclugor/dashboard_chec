from __future__ import annotations

from typing import Any

from dash import Dash, Input, Output, State, dcc, html
from dash import ctx, exceptions

from chec_dashboard.config import Settings
from chec_dashboard.dash_app.api_client import (
    fetch_chatbot_assessment,
    fetch_chatbot_conversation,
    fetch_chatbot_create_conversation,
    fetch_chatbot_context_options,
    fetch_chatbot_feedback,
    fetch_chatbot_message,
    fetch_chatbot_status,
    fetch_map_circuit_options,
    fetch_map_options,
)
from chec_dashboard.services.chatbot_service import BRIEFING_LABELS, GUIDED_QUESTIONS


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
        return html.Div("Selecciona una vista, evento o elemento de red.", className="chatbot-empty-state")
    context = item.get("context") or {}
    if item.get("kind") == "view":
        kpis = context.get("kpi_summary") or {}
        date_bounds = context.get("date_bounds") or {}
        top_circuits = ", ".join(entry.get("label", "") for entry in (context.get("top_circuits") or [])[:3])
        top_causes = ", ".join(entry.get("label", "") for entry in (context.get("top_causes") or [])[:3])
        key_values = [
            ("Tipo", "Vista filtrada"),
            ("Resumen", item.get("summary")),
            ("Período", context.get("selected_period")),
            ("Municipio", context.get("selected_municipio")),
            ("Circuitos", context.get("scope_label")),
            ("Fechas", f"{date_bounds.get('start') or 'N/D'} a {date_bounds.get('end') or 'N/D'}"),
            ("Indicadores", f"Eventos {kpis.get('event_count', 0)} / SAIDI {kpis.get('saidi_total', 0)} / SAIFI {kpis.get('saifi_total', 0)}"),
            ("Circuitos críticos", top_circuits),
            ("Causas", top_causes),
        ]
    else:
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


def _conversation_messages_component(messages: list[dict[str, Any]] | None):
    if not messages:
        return html.Div("Sin seguimiento todavía.", className="chatbot-empty-state")
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        "Usuario" if message.get("role") == "user" else "Asistente",
                        className="chatbot-message-role",
                    ),
                    dcc.Markdown(str(message.get("content") or ""), className="chatbot-message-text")
                    if message.get("role") == "assistant"
                    else html.Div(str(message.get("content") or ""), className="chatbot-message-text"),
                ],
                className=f"chatbot-message chatbot-message-{message.get('role') or 'assistant'}",
            )
            for message in messages
            if str(message.get("content") or "").strip()
        ],
        className="chatbot-conversation-thread",
    )


def _last_assistant_turn(messages: list[dict[str, Any]] | None) -> dict[str, Any]:
    for message in reversed(messages or []):
        if message.get("role") == "assistant" and message.get("turn_id"):
            return {
                "conversation_id": message.get("conversation_id"),
                "turn_id": message.get("turn_id"),
                "skill_id": message.get("skill_id"),
                "skill_version": message.get("skill_version"),
                "skill_hash": message.get("skill_hash"),
                "trace_id": message.get("trace_id"),
            }
    return {}


def _guided_question_options(briefing_type: str | None) -> list[dict[str, str]]:
    questions = GUIDED_QUESTIONS.get(briefing_type or "reliability", GUIDED_QUESTIONS["reliability"])
    return [{"label": question["question"], "value": question["id"]} for question in questions]


def get_layout(settings: Settings) -> html.Div:
    _ = settings
    return html.Div(
        [
            dcc.Interval(id="chatbot-load-interval", interval=300, n_intervals=0, max_intervals=1),
            dcc.Store(id="chatbot-context-items-store", data=[]),
            dcc.Store(id="chatbot-selected-context-store", data={}),
            dcc.Store(id="chatbot-conversation-id-store", data=None),
            dcc.Store(id="chatbot-conversation-store", data={}),
            dcc.Store(id="chatbot-last-turn-store", data={}),
            html.Div(
                [
                    html.Div(
                        [
                            html.H2("Asistente técnico", className="chatbot-title"),
                            html.Div(
                                "Análisis guiados para confiabilidad, cumplimiento y mantenimiento con datos CHEC y documentos técnicos.",
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
                                            {"label": "Vista filtrada", "value": "view"},
                                            {"label": "Evento", "value": "event"},
                                            {"label": "Elemento de red", "value": "asset"},
                                        ],
                                        value="view",
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
                            dcc.Tabs(
                                id="chatbot-analysis-type",
                                value="reliability",
                                children=[
                                    dcc.Tab(label=BRIEFING_LABELS["reliability"], value="reliability", className="chatbot-analysis-tab", selected_className="chatbot-analysis-tab-selected"),
                                    dcc.Tab(label=BRIEFING_LABELS["compliance"], value="compliance", className="chatbot-analysis-tab", selected_className="chatbot-analysis-tab-selected"),
                                    dcc.Tab(label=BRIEFING_LABELS["maintenance"], value="maintenance", className="chatbot-analysis-tab", selected_className="chatbot-analysis-tab-selected"),
                                ],
                                className="chatbot-analysis-tabs",
                            ),
                            dcc.RadioItems(
                                id="chatbot-question-id",
                                options=_guided_question_options("reliability"),
                                value=GUIDED_QUESTIONS["reliability"][0]["id"],
                                className="chatbot-question-cards",
                                inputClassName="chatbot-question-card-input",
                                labelClassName="chatbot-question-card",
                            ),
                        ],
                        className="chatbot-analysis-panel",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("VISTA O CONTEXTO", className="chatbot-filter-label"),
                                    dcc.Dropdown(
                                        id="chatbot-context-select",
                                        options=[],
                                        placeholder="Busca y selecciona una vista o contexto",
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
                                        placeholder="Matiza el análisis o pide un ángulo específico.",
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
                                            html.H3("Seguimiento", className="chatbot-panel-title"),
                                            html.Div(id="chatbot-conversation-thread", className="chatbot-conversation-thread-shell"),
                                            dcc.Textarea(
                                                id="chatbot-followup-input",
                                                placeholder="Pregunta de seguimiento...",
                                                className="chatbot-question-input chatbot-followup-input",
                                            ),
                                            html.Div(
                                                [
                                                    html.Button(
                                                        "ENVIAR",
                                                        id="chatbot-followup-button",
                                                        n_clicks=0,
                                                        className="chatbot-primary-button",
                                                    ),
                                                    html.Button(
                                                        "ÚTIL",
                                                        id="chatbot-feedback-helpful",
                                                        n_clicks=0,
                                                        className="chatbot-secondary-button",
                                                    ),
                                                    html.Button(
                                                        "NO ÚTIL",
                                                        id="chatbot-feedback-not-helpful",
                                                        n_clicks=0,
                                                        className="chatbot-secondary-button",
                                                    ),
                                                ],
                                                className="chatbot-followup-actions",
                                            ),
                                            html.Div(id="chatbot-followup-status", className="chatbot-inline-status"),
                                            html.Div(id="chatbot-feedback-status", className="chatbot-inline-status"),
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
        Output("chatbot-question-id", "options"),
        Output("chatbot-question-id", "value"),
        Input("chatbot-analysis-type", "value"),
    )
    def load_guided_questions(briefing_type: str | None):
        questions = GUIDED_QUESTIONS.get(briefing_type or "reliability", GUIDED_QUESTIONS["reliability"])
        options = [{"label": question["question"], "value": question["id"]} for question in questions]
        return options, questions[0]["id"] if questions else None

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
        Output("chatbot-conversation-id-store", "data"),
        Output("chatbot-conversation-store", "data"),
        Output("chatbot-conversation-thread", "children"),
        Output("chatbot-last-turn-store", "data"),
        Output("chatbot-followup-status", "children"),
        Input("chatbot-assess-button", "n_clicks"),
        State("chatbot-selected-context-store", "data"),
        State("chatbot-question", "value"),
        State("chatbot-analysis-type", "value"),
        State("chatbot-question-id", "value"),
        prevent_initial_call=True,
    )
    def assess_context(
        n_clicks: int | None,
        selected_context: dict[str, Any] | None,
        question: str | None,
        briefing_type: str | None = None,
        question_id: str | None = None,
    ):
        if not n_clicks:
            raise exceptions.PreventUpdate
        if not selected_context:
            return (
                "Selecciona una vista, evento o elemento de red antes de analizar.",
                _citations_component([]),
                "Falta contexto seleccionado.",
                None,
                {},
                _conversation_messages_component([]),
                {},
                "",
            )
        payload = fetch_chatbot_assessment(
            selected_context=selected_context,
            question=question,
            briefing_type=briefing_type or "reliability",
            question_id=question_id,
        )
        answer = dcc.Markdown(payload.get("answer") or "Sin respuesta.", className="chatbot-answer-markdown")
        citations = _citations_component(payload.get("citations", []))
        status_text = payload.get("status_text", "")
        conversation_id = payload.get("conversation_id")
        conversation = fetch_chatbot_conversation(conversation_id) if conversation_id else {}
        messages = conversation.get("messages") or []
        return (
            answer,
            citations,
            status_text,
            conversation_id,
            conversation,
            _conversation_messages_component(messages),
            _last_assistant_turn(messages),
            "",
        )

    @app.callback(
        Output("chatbot-conversation-store", "data", allow_duplicate=True),
        Output("chatbot-conversation-thread", "children", allow_duplicate=True),
        Output("chatbot-followup-status", "children", allow_duplicate=True),
        Output("chatbot-followup-input", "value"),
        Output("chatbot-last-turn-store", "data", allow_duplicate=True),
        Output("chatbot-conversation-id-store", "data", allow_duplicate=True),
        Input("chatbot-followup-button", "n_clicks"),
        State("chatbot-conversation-id-store", "data"),
        State("chatbot-conversation-store", "data"),
        State("chatbot-selected-context-store", "data"),
        State("chatbot-followup-input", "value"),
        State("chatbot-analysis-type", "value"),
        prevent_initial_call=True,
    )
    def send_followup(
        n_clicks: int | None,
        conversation_id: str | None,
        conversation: dict[str, Any] | None,
        selected_context: dict[str, Any] | None,
        message: str | None,
        briefing_type: str | None,
    ):
        if not n_clicks:
            raise exceptions.PreventUpdate
        message = " ".join((message or "").split())
        if not message:
            return (
                conversation or {},
                _conversation_messages_component((conversation or {}).get("messages")),
                "Escribe una pregunta de seguimiento.",
                "",
                _last_assistant_turn((conversation or {}).get("messages")),
                conversation_id,
            )
        if not conversation_id:
            if not selected_context:
                return (
                    conversation or {},
                    _conversation_messages_component((conversation or {}).get("messages")),
                    "Selecciona un contexto o genera un análisis primero.",
                    message,
                    _last_assistant_turn((conversation or {}).get("messages")),
                    conversation_id,
                )
            created = fetch_chatbot_create_conversation(
                selected_context=selected_context,
                briefing_type=briefing_type or "reliability",
                mode="free_form",
            )
            conversation_id = created.get("conversation_id")
        if not conversation_id:
            raise exceptions.PreventUpdate
        payload = fetch_chatbot_message(
            conversation_id=conversation_id,
            message=message,
            briefing_type=briefing_type or "reliability",
            selected_context=selected_context or None,
        )
        conversation = fetch_chatbot_conversation(conversation_id)
        messages = conversation.get("messages") or []
        return (
            conversation,
            _conversation_messages_component(messages),
            payload.get("status_text", "Respuesta de seguimiento registrada."),
            "",
            _last_assistant_turn(messages),
            conversation_id,
        )

    @app.callback(
        Output("chatbot-feedback-status", "children"),
        Input("chatbot-feedback-helpful", "n_clicks"),
        Input("chatbot-feedback-not-helpful", "n_clicks"),
        State("chatbot-conversation-id-store", "data"),
        State("chatbot-last-turn-store", "data"),
        prevent_initial_call=True,
    )
    def submit_feedback(
        helpful_clicks: int | None,
        not_helpful_clicks: int | None,
        conversation_id: str | None,
        last_turn: dict[str, Any] | None,
    ):
        _ = helpful_clicks, not_helpful_clicks
        if ctx.triggered_id not in {"chatbot-feedback-helpful", "chatbot-feedback-not-helpful"}:
            raise exceptions.PreventUpdate
        turn_id = (last_turn or {}).get("turn_id")
        conversation_id = conversation_id or (last_turn or {}).get("conversation_id")
        if not conversation_id or not turn_id:
            return "No hay una respuesta reciente para calificar."
        rating = "helpful" if ctx.triggered_id == "chatbot-feedback-helpful" else "not_helpful"
        payload = fetch_chatbot_feedback(
            conversation_id=conversation_id,
            turn_id=turn_id,
            rating=rating,
        )
        return payload.get("status_text", "Retroalimentación registrada.")
