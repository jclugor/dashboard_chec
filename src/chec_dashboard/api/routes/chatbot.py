from __future__ import annotations

from fastapi import APIRouter

from chec_dashboard.api.schemas.chatbot import (
    ChatbotAssessmentRequest,
    ChatbotAssessmentResponse,
    ChatbotContextOptionsRequest,
    ChatbotContextOptionsResponse,
    ChatbotStatusResponse,
)
from chec_dashboard.core.config import settings
from chec_dashboard.services.chatbot_service import (
    assess_chatbot_context,
    get_chatbot_context_options,
    get_chatbot_status,
)


router = APIRouter(prefix="/chatbot", tags=["chatbot"])


@router.get("/status", response_model=ChatbotStatusResponse)
def chatbot_status() -> ChatbotStatusResponse:
    return ChatbotStatusResponse(**get_chatbot_status(settings))


@router.post("/context-options", response_model=ChatbotContextOptionsResponse)
def chatbot_context_options(request: ChatbotContextOptionsRequest) -> ChatbotContextOptionsResponse:
    payload = get_chatbot_context_options(
        settings=settings,
        context_kind=request.context_kind,
        selected_period=request.selected_period,
        selected_municipio=request.selected_municipio,
        selected_circuits=request.selected_circuits,
        search=request.search,
        limit=request.limit,
    )
    return ChatbotContextOptionsResponse(**payload)


@router.post("/assess", response_model=ChatbotAssessmentResponse)
def chatbot_assess(request: ChatbotAssessmentRequest) -> ChatbotAssessmentResponse:
    payload = assess_chatbot_context(
        settings=settings,
        selected_context=request.selected_context,
        question=request.question,
    )
    return ChatbotAssessmentResponse(**payload)
