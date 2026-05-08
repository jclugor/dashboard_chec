from pathlib import Path

from dash import Dash, Input, Output
from dash import ctx, exceptions
from flask import send_from_directory

from chec_dashboard.config import settings
from chec_dashboard.pages.map_page import get_layout as map_layout
from chec_dashboard.pages.map_page import register_callbacks as register_map_callbacks
from chec_dashboard.pages.probability_page import get_layout as probability_layout
from chec_dashboard.pages.probability_page import register_callbacks as register_probability_callbacks
from chec_dashboard.pages.summary_page import get_layout as summary_layout
from chec_dashboard.pages.summary_page import register_callbacks as register_summary_callbacks
from chec_dashboard.services.summary_service import load_summary_dataset
from chec_dashboard.ui.shell import (
    build_shell_layout,
    map_nav_style,
    prob_nav_style,
    summary_nav_style,
)


def create_app() -> Dash:
    assets_path = Path(__file__).resolve().parent / "assets"
    app = Dash(
        __name__,
        suppress_callback_exceptions=True,
        assets_folder=str(assets_path),
        external_stylesheets=[
            "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;700&display=swap",
            "https://fonts.googleapis.com/css2?family=Poppins:wght@700&display=swap",
        ],
    )

    initial_workspace = map_layout(settings)
    app.layout = build_shell_layout(initial_workspace_children=initial_workspace)
    _warm_summary_cache()
    _register_output_route(app)
    _register_root_callbacks(app)
    register_map_callbacks(app, settings)
    register_probability_callbacks(app, settings)
    register_summary_callbacks(app, settings)
    return app


def _warm_summary_cache() -> None:
    try:
        load_summary_dataset(str(settings.data_dir))
    except Exception:
        # Keep startup resilient; summary tab will surface a friendly error state.
        pass


def _register_output_route(app: Dash) -> None:
    @app.server.route("/outputs/<path:filename>")
    def serve_outputs(filename: str):
        return send_from_directory(str(settings.output_dir), filename)


def _register_root_callbacks(app: Dash) -> None:
    @app.callback(
        Output("workspace-container", "children"),
        Output("nav-button-map", "style"),
        Output("nav-button-prob", "style"),
        Output("nav-button-summary", "style"),
        Input("nav-button-map", "n_clicks"),
        Input("nav-button-prob", "n_clicks"),
        Input("nav-button-summary", "n_clicks"),
        prevent_initial_call=True,
    )
    def navigate_tabs(n_map: int, n_prob: int, n_summary: int):
        if ctx.triggered_id is None:
            raise exceptions.PreventUpdate
        if ctx.triggered_id == "nav-button-map":
            return (
                map_layout(settings),
                map_nav_style(True),
                prob_nav_style(False),
                summary_nav_style(False),
            )
        if ctx.triggered_id == "nav-button-prob":
            return (
                probability_layout(),
                map_nav_style(False),
                prob_nav_style(True),
                summary_nav_style(False),
            )
        if ctx.triggered_id == "nav-button-summary":
            return (
                summary_layout(settings),
                map_nav_style(False),
                prob_nav_style(False),
                summary_nav_style(True),
            )
        raise exceptions.PreventUpdate
