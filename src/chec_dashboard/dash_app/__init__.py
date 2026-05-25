def register_dash_callbacks(*args, **kwargs):
    from chec_dashboard.dash_app.callbacks import register_dash_callbacks as _register

    return _register(*args, **kwargs)



def build_dash_layout(*args, **kwargs):
    from chec_dashboard.dash_app.layout import build_dash_layout as _build

    return _build(*args, **kwargs)


__all__ = ["register_dash_callbacks", "build_dash_layout"]
