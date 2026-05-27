from __future__ import annotations

from dash import Dash, Input, Output, State
from dash import ctx, exceptions
from flask import jsonify, request, send_from_directory

from chec_dashboard.config import Settings
from chec_dashboard.dash_app.api_client import (
    StartupStatus,
    check_api_health,
    check_api_ready,
    warm_api_metadata,
)
from chec_dashboard.services.data_service import (
    get_map_filter_metadata,
    get_map_metadata,
    get_map_payload,
    get_probability_columns_metadata,
    get_probability_filter_options_metadata,
    get_probability_metadata,
    get_probability_payload,
    get_summary_metadata,
    get_summary_payload,
)
from chec_dashboard.services.chatbot_service import (
    assess_chatbot_context,
    get_chatbot_context_options,
    get_chatbot_status,
)
from chec_dashboard.services.databricks_data_service import databricks_data_readiness_check
from chec_dashboard.services.startup_validation import find_missing_required_files
from chec_dashboard.pages.chatbot_page import get_layout as chatbot_layout
from chec_dashboard.pages.chatbot_page import register_callbacks as register_chatbot_callbacks
from chec_dashboard.pages.map_page import get_layout as map_layout
from chec_dashboard.pages.map_page import register_callbacks as register_map_callbacks
from chec_dashboard.pages.probability_page import get_layout as probability_layout
from chec_dashboard.pages.probability_page import register_callbacks as register_probability_callbacks
from chec_dashboard.pages.summary_page import get_layout as summary_layout
from chec_dashboard.pages.summary_page import register_callbacks as register_summary_callbacks
from chec_dashboard.ui.shell import (
    build_startup_screen,
    map_nav_style,
    prob_nav_style,
    chat_nav_style,
    summary_nav_style,
)


def register_dash_callbacks(app: Dash, settings: Settings) -> None:
    _register_health_route(app)
    _register_local_contract_routes(app, settings)
    _register_output_route(app, settings)
    _register_startup_callbacks(app, settings)
    _register_root_callbacks(app, settings)
    register_map_callbacks(app, settings)
    register_probability_callbacks(app, settings)
    register_summary_callbacks(app, settings)
    register_chatbot_callbacks(app, settings)


def _register_health_route(app: Dash) -> None:
    @app.server.route("/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok"}), 200


def _register_local_contract_routes(app: Dash, settings: Settings) -> None:
    empty_map_metadata = {
        "action": None,
        "dates": [],
        "municipios": [],
        "default_date": None,
        "default_municipio": None,
        "circuits": [],
        "default_circuit": None,
        "outputs": [],
        "default_output": None,
    }
    empty_summary_metadata = {
        "circuits": [],
        "default_circuit": None,
        "min_date": None,
        "max_date": None,
        "default_start": None,
        "default_end": None,
    }
    empty_probability_metadata = {
        "action": "criteria",
        "criteria_options": [],
        "columns": [],
        "filter_kind": None,
        "value_options": [],
        "is_empty": False,
        "message": None,
    }

    @app.server.route("/ready", methods=["GET"])
    def ready():
        if settings.data_backend == "databricks_sql":
            data_ok, data_message = databricks_data_readiness_check(settings)
        else:
            missing_files = find_missing_required_files(settings.data_dir)
            data_ok = not missing_files
            if missing_files:
                data_message = f"Missing required data files: {', '.join(sorted(missing_files))}"
            else:
                data_message = "All required data files are available"

        backend_ok = True
        backend_message = "Backend routing handled in-process"
        ready_value = data_ok and backend_ok
        status_code = 200 if ready_value else 503
        return (
            jsonify(
                {
                    "status": "ready" if ready_value else "not_ready",
                    "ready": ready_value,
                    "environment": settings.environment,
                    "model_backend": settings.model_backend,
                    "checks": {
                        "data": {"ok": data_ok, "message": data_message},
                        "backend": {"ok": backend_ok, "message": backend_message},
                    },
                }
            ),
            status_code,
        )

    @app.server.route("/data", methods=["GET", "POST"])
    def data():
        try:
            if request.method == "GET":
                section = request.args.get("section", "all")
                if section == "all":
                    payload = {
                        "map": get_map_metadata(settings),
                        "summary": get_summary_metadata(settings),
                        "probability": get_probability_metadata(settings),
                    }
                elif section == "map":
                    payload = {
                        "map": get_map_metadata(settings),
                        "summary": empty_summary_metadata,
                        "probability": empty_probability_metadata,
                    }
                elif section == "summary":
                    payload = {
                        "map": empty_map_metadata,
                        "summary": get_summary_metadata(settings),
                        "probability": empty_probability_metadata,
                    }
                elif section == "probability":
                    payload = {
                        "map": empty_map_metadata,
                        "summary": empty_summary_metadata,
                        "probability": get_probability_metadata(settings),
                    }
                else:
                    raise ValueError(f"Unsupported section: {section}")
                return jsonify(payload), 200

            payload = request.get_json(force=True) or {}
            mode = payload.get("mode")
            if mode == "summary":
                summary = payload.get("summary") or {}
                response_payload = {
                    "mode": "summary",
                    "summary": get_summary_payload(
                        settings=settings,
                        start_date_raw=summary.get("start_date"),
                        end_date_raw=summary.get("end_date"),
                        circuito=summary.get("circuito"),
                        metric_mode=summary.get("metric_mode") or "BOTH",
                    ),
                }
            elif mode == "probability":
                probability = payload.get("probability") or {}
                response_payload = {
                    "mode": "probability",
                    "probability": get_probability_payload(
                        settings=settings,
                        criteria=probability.get("criteria") or "",
                        target_column=probability.get("target_column") or "",
                        filters=probability.get("filters") or [],
                    ),
                }
            elif mode == "probability_metadata":
                metadata = payload.get("probability_metadata") or {}
                action = metadata.get("action")
                if action == "criteria":
                    probability_metadata = get_probability_metadata(settings)
                elif action == "columns":
                    probability_metadata = get_probability_columns_metadata(
                        settings=settings,
                        criteria=metadata.get("criteria") or "",
                    )
                elif action == "filter_options":
                    probability_metadata = get_probability_filter_options_metadata(
                        settings=settings,
                        criteria=metadata.get("criteria") or "",
                        selected_column=metadata.get("selected_column") or "",
                        previous_filters=metadata.get("previous_filters") or [],
                    )
                else:
                    raise ValueError(f"Unsupported probability metadata action: {action}")
                response_payload = {
                    "mode": "probability_metadata",
                    "probability_metadata": probability_metadata,
                }
            elif mode == "map_metadata":
                metadata = payload.get("map_metadata") or {}
                response_payload = {
                    "mode": "map_metadata",
                    "map_metadata": get_map_filter_metadata(
                        settings=settings,
                        action=metadata.get("action") or "",
                        selected_period=metadata.get("selected_period") or "",
                        selected_municipio=metadata.get("selected_municipio") or "",
                    ),
                }
            elif mode == "map":
                map_payload = payload.get("map") or {}
                response_payload = {
                    "mode": "map",
                    "map": get_map_payload(
                        settings=settings,
                        selected_period=map_payload.get("selected_period") or "",
                        selected_municipio=map_payload.get("selected_municipio") or "",
                        selected_circuit=map_payload.get("selected_circuit"),
                        selected_circuits=map_payload.get("selected_circuits"),
                        selected_output=map_payload.get("selected_output"),
                        day=int(map_payload.get("day") or 1),
                    ),
                }
            else:
                raise ValueError(f"Unsupported mode: {mode}")

            return jsonify(response_payload), 200
        except Exception as exc:
            return jsonify({"detail": str(exc), "error_type": "dash_local_contract_error"}), 400

    @app.server.route("/chatbot/status", methods=["GET"])
    def chatbot_status():
        return jsonify(get_chatbot_status(settings)), 200

    @app.server.route("/chatbot/context-options", methods=["POST"])
    def chatbot_context_options():
        try:
            payload = request.get_json(force=True) or {}
            response_payload = get_chatbot_context_options(
                settings=settings,
                context_kind=payload.get("context_kind") or "event",
                selected_period=payload.get("selected_period") or "",
                selected_municipio=payload.get("selected_municipio") or "",
                selected_circuits=payload.get("selected_circuits"),
                search=payload.get("search"),
                limit=int(payload.get("limit") or 50),
            )
            return jsonify(response_payload), 200
        except Exception as exc:
            return jsonify({"detail": str(exc), "error_type": "dash_local_contract_error"}), 400

    @app.server.route("/chatbot/assess", methods=["POST"])
    def chatbot_assess():
        try:
            payload = request.get_json(force=True) or {}
            response_payload = assess_chatbot_context(
                settings=settings,
                selected_context=payload.get("selected_context") or {},
                question=payload.get("question"),
            )
            return jsonify(response_payload), 200
        except Exception as exc:
            return jsonify({"detail": str(exc), "error_type": "dash_local_contract_error"}), 400


def _register_output_route(app: Dash, settings: Settings) -> None:
    @app.server.route("/outputs/<path:filename>")
    def serve_outputs(filename: str):
        return send_from_directory(str(settings.output_dir), filename)


def _startup_status(settings: Settings) -> StartupStatus:
    ready_status = check_api_ready()
    if not ready_status.ready:
        return ready_status

    warmup_status = warm_api_metadata()
    if not warmup_status.ready:
        return warmup_status

    return StartupStatus("ready", "Dashboard listo.")


def _max_attempts_reached(settings: Settings, n_intervals: int | None) -> bool:
    return (
        settings.api_startup_max_attempts > 0
        and n_intervals is not None
        and n_intervals >= settings.api_startup_max_attempts
    )


def _register_startup_callbacks(app: Dash, settings: Settings) -> None:
    @app.callback(
        Output("workspace-container", "children", allow_duplicate=True),
        Output("nav-button-map", "disabled"),
        Output("nav-button-prob", "disabled"),
        Output("nav-button-summary", "disabled"),
        Output("nav-button-chat", "disabled"),
        Output("api-startup-interval", "disabled"),
        Output("api-heartbeat-interval", "disabled"),
        Output("api-startup-state", "data"),
        Input("api-startup-interval", "n_intervals"),
        State("api-startup-state", "data"),
        prevent_initial_call=True,
    )
    def initialize_dashboard(n_intervals: int | None, startup_state: dict | None):
        if startup_state and startup_state.get("status") == "ready":
            raise exceptions.PreventUpdate

        status = _startup_status(settings)
        if status.ready:
            try:
                workspace = map_layout(settings)
            except Exception as exc:
                status = StartupStatus("warming", str(exc))
            else:
                return (
                    workspace,
                    False,
                    False,
                    False,
                    False,
                    True,
                    False,
                    {"status": "ready", "message": status.message},
                )

        if status.status == "data_unavailable":
            return (
                build_startup_screen(
                    "Datos no disponibles",
                    detail=status.message,
                    is_error=True,
                ),
                True,
                True,
                True,
                True,
                True,
                True,
                {"status": status.status, "message": status.message},
            )

        if _max_attempts_reached(settings, n_intervals):
            message = (
                "No fue posible inicializar el backend dentro del límite configurado. "
                "Revisa los logs del API."
            )
            return (
                build_startup_screen("No se pudo inicializar", detail=message, is_error=True),
                True,
                True,
                True,
                True,
                True,
                True,
                {"status": "error", "message": message},
            )

        return (
            build_startup_screen(
                "Inicializando dashboard...",
                detail=status.message,
                is_error=False,
            ),
            True,
            True,
            True,
            True,
            False,
            True,
            {"status": status.status, "message": status.message},
        )

    @app.callback(
        Output("api-heartbeat-status", "data"),
        Input("api-heartbeat-interval", "n_intervals"),
        State("api-startup-state", "data"),
        prevent_initial_call=True,
    )
    def keep_api_warm(n_intervals: int | None, startup_state: dict | None):
        if not startup_state or startup_state.get("status") != "ready":
            raise exceptions.PreventUpdate
        status = check_api_health()
        return {
            "status": status.status,
            "message": status.message,
            "status_code": status.status_code,
            "n_intervals": n_intervals,
        }


def _register_root_callbacks(app: Dash, settings: Settings) -> None:
    @app.callback(
        Output("workspace-container", "children"),
        Output("nav-button-map", "style"),
        Output("nav-button-prob", "style"),
        Output("nav-button-summary", "style"),
        Output("nav-button-chat", "style"),
        Input("nav-button-map", "n_clicks"),
        Input("nav-button-prob", "n_clicks"),
        Input("nav-button-summary", "n_clicks"),
        Input("nav-button-chat", "n_clicks"),
        State("api-startup-state", "data"),
        prevent_initial_call=True,
    )
    def navigate_tabs(n_map: int, n_prob: int, n_summary: int, n_chat: int, startup_state: dict | None):
        _ = n_map
        _ = n_prob
        _ = n_summary
        _ = n_chat
        if ctx.triggered_id is None:
            raise exceptions.PreventUpdate
        if not startup_state or startup_state.get("status") != "ready":
            raise exceptions.PreventUpdate
        if ctx.triggered_id == "nav-button-map":
            return (
                map_layout(settings),
                map_nav_style(True),
                prob_nav_style(False),
                summary_nav_style(False),
                chat_nav_style(False),
            )
        if ctx.triggered_id == "nav-button-prob":
            return (
                probability_layout(),
                map_nav_style(False),
                prob_nav_style(True),
                summary_nav_style(False),
                chat_nav_style(False),
            )
        if ctx.triggered_id == "nav-button-summary":
            return (
                summary_layout(settings),
                map_nav_style(False),
                prob_nav_style(False),
                summary_nav_style(True),
                chat_nav_style(False),
            )
        if ctx.triggered_id == "nav-button-chat":
            return (
                chatbot_layout(settings),
                map_nav_style(False),
                prob_nav_style(False),
                summary_nav_style(False),
                chat_nav_style(True),
            )
        raise exceptions.PreventUpdate
