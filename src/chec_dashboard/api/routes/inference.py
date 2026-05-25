from fastapi import APIRouter, Request, Response

from chec_dashboard.api.schemas.requests import InferenceRequest
from chec_dashboard.api.schemas.responses import InferenceResponse
from chec_dashboard.core.config import settings
from chec_dashboard.services.inference_service import get_inference_service


router = APIRouter(tags=["inference"])


@router.post("/inference", response_model=InferenceResponse)
def inference(request: InferenceRequest, http_request: Request, response: Response) -> InferenceResponse:
    request_id = getattr(http_request.state, "request_id", "unknown")
    service = get_inference_service(settings)
    result = service.predict(
        features=request.features,
        context=request.context,
        request_id=request_id,
    )
    response.headers["X-Request-ID"] = request_id
    return InferenceResponse(
        request_id=result.request_id,
        backend=result.backend,
        prediction=result.prediction,
        label=result.label,
        model_version=result.model_version,
        raw_response=result.raw_response,
    )
