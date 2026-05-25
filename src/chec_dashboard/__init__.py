def create_app():
    from .app import create_app as _create_app

    return _create_app()


def create_api_app():
    from .api.main import create_api_app as _create_api_app

    return _create_api_app()


__all__ = ["create_app", "create_api_app"]
