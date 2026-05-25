from pathlib import Path

from fastapi import APIRouter, Response

from chec_dashboard.api.schemas.responses import HealthResponse, ReadinessCheck, ReadinessResponse
from chec_dashboard.core.config import settings
from chec_dashboard.services.databricks_data_service import databricks_data_readiness_check
from chec_dashboard.services.map_service import REQUIRED_MAP_FILES
from chec_dashboard.services.model_loader import load_local_model
from chec_dashboard.services.probability_service import REQUIRED_PROBABILITY_FILES
from chec_dashboard.services.summary_service import SUMMARY_FILE


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        model_backend=settings.model_backend,
        cache_enabled=settings.cache_enabled,
    )



def _data_readiness_check(data_dir: Path) -> ReadinessCheck:
    if settings.data_backend == "databricks_sql":
        ok, message = databricks_data_readiness_check(settings)
        return ReadinessCheck(ok=ok, message=message)

    required_files = set(REQUIRED_MAP_FILES + REQUIRED_PROBABILITY_FILES + [SUMMARY_FILE])
    missing = [name for name in sorted(required_files) if not (data_dir / name).exists()]
    if missing:
        return ReadinessCheck(ok=False, message=f"Missing required data files: {', '.join(missing)}")
    return ReadinessCheck(ok=True, message="All required data files are available")



def _backend_readiness_check() -> ReadinessCheck:
    backend = settings.model_backend.lower()
    if backend == "mock":
        return ReadinessCheck(ok=True, message="Mock backend ready")

    if backend == "local":
        try:
            load_local_model()
        except Exception as exc:
            return ReadinessCheck(ok=False, message=f"Local model failed to load: {exc}")
        return ReadinessCheck(ok=True, message="Local model loaded")

    if backend == "azure_ml":
        if not settings.azure_ml_endpoint or not settings.azure_ml_key:
            return ReadinessCheck(
                ok=False,
                message="AZURE_ML_ENDPOINT and AZURE_ML_KEY are required for azure_ml backend",
            )
        return ReadinessCheck(ok=True, message="Azure ML backend configured")

    if backend == "databricks":
        if not settings.databricks_host or not settings.databricks_token or not settings.databricks_model_endpoint:
            return ReadinessCheck(
                ok=False,
                message=(
                    "DATABRICKS_HOST, DATABRICKS_TOKEN and DATABRICKS_MODEL_ENDPOINT "
                    "are required for databricks backend"
                ),
            )
        return ReadinessCheck(ok=True, message="Databricks backend configured")

    return ReadinessCheck(ok=False, message=f"Unsupported MODEL_BACKEND: {settings.model_backend}")


@router.get("/ready", response_model=ReadinessResponse)
def readiness(response: Response) -> ReadinessResponse:
    checks = {
        "data": _data_readiness_check(settings.data_dir),
        "backend": _backend_readiness_check(),
    }
    ready = all(check.ok for check in checks.values())
    response.status_code = 200 if ready else 503

    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        ready=ready,
        environment=settings.environment,
        model_backend=settings.model_backend,
        checks=checks,
    )
