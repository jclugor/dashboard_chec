from dash import html

CHEC_GREEN = "#00782b"
CHEC_LIGHT_GREEN = "#16D622"
CHEC_SOFT_GREEN = "#28DB7F"
CHEC_BUTTON_GREEN = "#11BB52CF"


def _nav_button_style(background_image: str, active: bool) -> dict:
    return {
        "width": "100%",
        "height": "12%",
        "marginTop": "7vh" if active else "9vh",
        "border": "3px solid #068f36",
        "backgroundColor": "#01471998" if active else "#cdcdcd44",
        "backgroundImage": background_image,
        "backgroundSize": "70%",
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


def build_shell_layout(initial_workspace_children=None) -> html.Div:
    return html.Div(
        [
            html.Div(
                className="Banner",
                children=[
                    html.Div(
                        className="Image-User",
                        style={
                            "backgroundImage": "url('/assets/images/e0b35f32-93cf-49b5-b63a-248fa22056d1.png')",
                            "backgroundSize": "cover",
                            "backgroundPosition": "center",
                            "backgroundRepeat": "no-repeat",
                            "width": "6%",
                            "height": "80%",
                            "borderRadius": "14px",
                            "marginLeft": "7%",
                        },
                    ),
                    html.Div(
                        "Hola usuario CHEC",
                        className="Welcome-User",
                        style={
                            "width": "23%",
                            "height": "100%",
                            "marginLeft": "2%",
                            "lineHeight": "13vh",
                            "color": "#FFFFFF",
                            "fontFamily": "'DM Sans', sans-serif",
                            "fontSize": "30px",
                            "fontWeight": "700",
                        },
                    ),
                    html.Div(
                        className="CHEC-Logo",
                        style={
                            "backgroundImage": "url('/assets/images/797ea4a7-6ea7-4351-93b9-c76257a788b3.png')",
                            "backgroundSize": "contain",
                            "backgroundPosition": "center",
                            "backgroundRepeat": "no-repeat",
                            "width": "16%",
                            "height": "80%",
                            "position": "relative",
                            "right": "-45%",
                        },
                    ),
                ],
                style={
                    "backgroundColor": CHEC_GREEN,
                    "width": "100%",
                    "height": "13.5vh",
                    "display": "flex",
                    "flexDirection": "row",
                    "alignItems": "center",
                },
            ),
            html.Div(
                [
                    html.Div(
                        className="Nav-Bar",
                        children=[
                            html.Button(
                                id="nav-button-map",
                                className="Maps-Button",
                                style=map_nav_style(True),
                                n_clicks=0,
                            ),
                            html.Button(
                                id="nav-button-prob",
                                className="Graph-Button",
                                style=prob_nav_style(False),
                                n_clicks=0,
                            ),
                            html.Button(
                                id="nav-button-summary",
                                className="Summary-Button",
                                style=summary_nav_style(False),
                                n_clicks=0,
                            ),
                        ],
                        style={
                            "backgroundColor": CHEC_GREEN,
                            "width": "5.83%",
                            "height": "86.5vh",
                            "display": "flex",
                            "flexDirection": "column",
                        },
                    ),
                    html.Div(
                        id="workspace-container",
                        className="Work-Space",
                        children=initial_workspace_children,
                        style={
                            "backgroundColor": "#FFFFFF",
                            "width": "94.17%",
                            "height": "86.5vh",
                            "display": "flex",
                            "flexDirection": "column",
                            "alignItems": "center",
                        },
                    ),
                ],
                style={"display": "flex", "flex": "1"},
            ),
        ],
        style={
            "height": "100vh",
            "margin": 0,
            "display": "flex",
            "flexDirection": "column",
        },
    )
