from dash import dcc, html

from chec_dashboard.config import Settings

CHEC_GREEN = "#00782b"
CHEC_LIGHT_GREEN = "#16D622"
CHEC_SOFT_GREEN = "#28DB7F"
CHEC_BUTTON_GREEN = "#11BB52CF"


def _nav_button_style(background_image: str, active: bool) -> dict:
    return {
        "border": "3px solid #068f36",
        "backgroundColor": "#01471998" if active else "#cdcdcd44",
        "backgroundImage": background_image,
        "backgroundSize": "68%",
        "backgroundPosition": "center",
        "backgroundRepeat": "no-repeat",
        "cursor": "pointer",
    }


def map_nav_style(active: bool) -> dict:
    return _nav_button_style(
        "url('/assets/images/22ab6d20-fe4b-421e-9ffd-eec28093a1b5.png')",
        active,
    )


def prob_nav_style(active: bool) -> dict:
    return _nav_button_style(
        "url('/assets/images/7f201cec-29ad-4dc6-ad2c-b331f289fd8a.png')",
        active,
    )


def summary_nav_style(active: bool) -> dict:
    return _nav_button_style(
        "url('/assets/images/stats-graph-svgrepo-com.svg')",
        active,
    )


def build_startup_screen(
    message: str = "Inicializando dashboard...",
    *,
    detail: str | None = None,
    is_error: bool = False,
) -> html.Div:
    color = "#8a0000" if is_error else CHEC_GREEN
    background = "#ffe6e6" if is_error else "#f5fff8"
    return html.Div(
        [
            html.Div(
                style={
                    "width": "54px",
                    "height": "54px",
                    "border": "6px solid #d8f4df",
                    "borderTopColor": color,
                    "borderRadius": "50%",
                    "animation": "spin 1s linear infinite",
                    "marginBottom": "18px",
                },
            ),
            html.Div(
                message,
                style={
                    "fontFamily": "'DM Sans', sans-serif",
                    "fontSize": "26px",
                    "fontWeight": "700",
                    "color": color,
                    "textAlign": "center",
                },
            ),
            html.Div(
                detail or "Estamos activando los servicios. Esto puede tardar unos segundos.",
                style={
                    "fontFamily": "'DM Sans', sans-serif",
                    "fontSize": "16px",
                    "fontWeight": "700",
                    "color": "#014719" if not is_error else color,
                    "textAlign": "center",
                    "maxWidth": "620px",
                    "marginTop": "10px",
                    "lineHeight": "1.4",
                },
            ),
        ],
        style={
            "width": "100%",
            "height": "100%",
            "backgroundColor": background,
            "display": "flex",
            "flexDirection": "column",
            "alignItems": "center",
            "justifyContent": "center",
            "padding": "24px",
            "boxSizing": "border-box",
        },
    )


def build_shell_layout(
    settings: Settings,
    initial_workspace_children=None,
    data_warning: str | None = None,
) -> html.Div:
    warning_banner = (
        html.Div(
            data_warning,
            className="dashboard-warning-banner",
            style={
                "backgroundColor": "#ffe6e6",
                "color": "#8a0000",
                "fontFamily": "'DM Sans', sans-serif",
                "fontWeight": "700",
                "fontSize": "14px",
                "padding": "10px 14px",
                "borderBottom": "2px solid #f4b2b2",
            },
        )
        if data_warning
        else None
    )
    return html.Div(
        [
            html.Div(
                className="dashboard-header Banner",
                children=[
                    html.Div(
                        className="dashboard-header-user-group",
                        children=[
                            html.Div(
                                className="dashboard-header-user-avatar Image-User",
                                style={
                                    "backgroundImage": "url('/assets/images/e0b35f32-93cf-49b5-b63a-248fa22056d1.png')",
                                    "backgroundSize": "cover",
                                    "backgroundPosition": "center",
                                    "backgroundRepeat": "no-repeat",
                                },
                            ),
                            html.Div(
                                "Hola usuario CHEC",
                                className="dashboard-header-user-text Welcome-User",
                                style={
                                    "color": "#FFFFFF",
                                    "fontFamily": "'DM Sans', sans-serif",
                                    "fontWeight": "700",
                                },
                            ),
                        ],
                    ),
                    html.Div(
                        className="dashboard-header-logo CHEC-Logo",
                        style={
                            "backgroundImage": "url('/assets/images/797ea4a7-6ea7-4351-93b9-c76257a788b3.png')",
                            "backgroundSize": "contain",
                            "backgroundPosition": "center",
                            "backgroundRepeat": "no-repeat",
                        },
                    ),
                ],
                style={
                    "backgroundColor": CHEC_GREEN,
                },
            ),
            warning_banner,
            html.Div(
                [
                    html.Div(
                        className="dashboard-nav Nav-Bar",
                        children=[
                            html.Button(
                                id="nav-button-map",
                                className="dashboard-nav-button dashboard-nav-button-map Maps-Button",
                                style=map_nav_style(True),
                                n_clicks=0,
                                disabled=True,
                            ),
                            html.Button(
                                id="nav-button-prob",
                                className="dashboard-nav-button dashboard-nav-button-prob Graph-Button",
                                style=prob_nav_style(False),
                                n_clicks=0,
                                disabled=True,
                            ),
                            html.Button(
                                id="nav-button-summary",
                                className="dashboard-nav-button dashboard-nav-button-summary Summary-Button",
                                style=summary_nav_style(False),
                                n_clicks=0,
                                disabled=True,
                            ),
                        ],
                        style={"backgroundColor": CHEC_GREEN},
                    ),
                    html.Div(
                        id="workspace-container",
                        className="dashboard-workspace Work-Space",
                        children=initial_workspace_children,
                        style={
                            "backgroundColor": "#FFFFFF",
                            "display": "flex",
                            "flexDirection": "column",
                            "alignItems": "center",
                        },
                    ),
                ],
                className="dashboard-main",
            ),
            dcc.Store(id="api-startup-state", data={"status": "warming"}),
            dcc.Store(id="api-heartbeat-status"),
            dcc.Interval(
                id="api-startup-interval",
                interval=settings.api_startup_poll_seconds * 1000,
                n_intervals=0,
                disabled=False,
            ),
            dcc.Interval(
                id="api-heartbeat-interval",
                interval=settings.api_keepalive_seconds * 1000,
                n_intervals=0,
                disabled=True,
            ),
        ],
        className="dashboard-shell",
        style={
            "margin": 0,
            "display": "flex",
            "flexDirection": "column",
        },
    )
