from pathlib import Path

from dash import Dash

from chec_dashboard.config import settings
from chec_dashboard.core.logging import configure_logging, get_logger
from chec_dashboard.dash_app import build_dash_layout, register_dash_callbacks
from chec_dashboard.services.startup_validation import (
    build_missing_files_message,
    find_missing_required_files,
)



def create_app() -> Dash:
    configure_logging(settings.log_level)
    logger = get_logger(__name__, settings.log_level)
    missing_files = find_missing_required_files(settings.data_dir) if settings.data_backend == "pickle" else []
    data_warning = None
    if missing_files:
        data_warning = build_missing_files_message(settings.data_dir, missing_files)
        logger.warning(data_warning)
    elif settings.data_backend == "pickle":
        logger.info("Required dashboard data files found in DATA_DIR=%s", settings.data_dir)
    else:
        logger.info("Dashboard data backend configured for %s", settings.data_backend)

    assets_path = Path(__file__).resolve().parent / "assets"
    app = Dash(
        __name__,
        suppress_callback_exceptions=True,
        assets_folder=str(assets_path),
        meta_tags=[
            {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        ],
        external_stylesheets=[
            "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;700&display=swap",
        ],
    )

    app.layout = build_dash_layout(settings, data_warning=data_warning)
    register_dash_callbacks(app, settings)
    return app
