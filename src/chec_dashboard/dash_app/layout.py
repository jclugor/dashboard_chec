from __future__ import annotations

from dash import html

from chec_dashboard.config import Settings
from chec_dashboard.ui.shell import build_shell_layout, build_startup_screen



def build_dash_layout(settings: Settings, data_warning: str | None = None) -> html.Div:
    initial_workspace = build_startup_screen()
    return build_shell_layout(
        settings=settings,
        initial_workspace_children=initial_workspace,
        data_warning=data_warning,
    )
