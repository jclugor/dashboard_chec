from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from chec_dashboard.api.routes.data import router as data_router
from chec_dashboard.api.routes.health import router as health_router
from chec_dashboard.api.routes.inference import router as inference_router
from chec_dashboard.api.schemas.responses import ErrorResponse
from chec_dashboard.core.config import settings
from chec_dashboard.core.logging import configure_logging, get_logger
from chec_dashboard.services.inference_service import (
    InferenceBackendRequestError,
    InferenceTimeoutError,
)
from chec_dashboard.services.startup_validation import (
    build_missing_files_message,
    find_missing_required_files,
)



def _error_json(status_code: int, detail: str, error_type: str, request_id: str) -> JSONResponse:
    payload = ErrorResponse(detail=detail, error_type=error_type)
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(),
        headers={"X-Request-ID": request_id},
    )



def create_api_app() -> FastAPI:
    configure_logging(settings.log_level)
    logger = get_logger(__name__, settings.log_level)
    missing_files = find_missing_required_files(settings.data_dir)
    if missing_files:
        logger.warning(build_missing_files_message(settings.data_dir, missing_files))
    else:
        logger.info("Required API data files found in DATA_DIR=%s", settings.data_dir)

    app = FastAPI(
        title="CHEC Dashboard API",
        version="0.2.0",
        description="Backend API for Dash frontend data and inference orchestration.",
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(health_router)
    app.include_router(data_router)
    app.include_router(inference_router)

    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(request: Request, exc: FileNotFoundError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return _error_json(404, str(exc), "file_not_found", request_id)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        return _error_json(400, str(exc), "validation", request_id)

    @app.exception_handler(InferenceTimeoutError)
    async def inference_timeout_handler(request: Request, exc: InferenceTimeoutError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        logger.warning("Inference timeout", extra={"request_id": request_id, "error": str(exc)})
        return _error_json(504, str(exc), "inference_timeout", request_id)

    @app.exception_handler(InferenceBackendRequestError)
    async def inference_backend_handler(
        request: Request,
        exc: InferenceBackendRequestError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        logger.warning("Inference backend request failure", extra={"request_id": request_id, "error": str(exc)})
        return _error_json(502, str(exc), "inference_backend_error", request_id)

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        logger.exception("Unhandled API error", exc_info=exc, extra={"request_id": request_id})
        return _error_json(500, "Internal server error", "internal_error", request_id)

    return app


app = create_api_app()
