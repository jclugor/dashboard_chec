from __future__ import annotations

from fastapi import APIRouter, HTTPException

from chec_dashboard.api.schemas.chatbot import (
    ChatbotAssessmentRequest,
    ChatbotAssessmentResponse,
    ChatbotConversationCreateRequest,
    ChatbotConversationMessageRequest,
    ChatbotConversationMessageResponse,
    ChatbotConversationResponse,
    ChatbotContextOptionsRequest,
    ChatbotContextOptionsResponse,
    ChatbotFeedbackRequest,
    ChatbotFeedbackResponse,
    ChatbotSkillStatusResponse,
    ChatbotStatusResponse,
)
from chec_dashboard.core.config import settings
from chec_dashboard.services.chatbot_service import (
    assess_chatbot_context,
    create_chatbot_conversation,
    get_chatbot_context_options,
    get_chatbot_conversation,
    get_skill_status,
    get_chatbot_status,
    send_chatbot_message,
    submit_chatbot_feedback,
)


router = APIRouter(prefix="/chatbot", tags=["chatbot"])


@router.get("/status", response_model=ChatbotStatusResponse)
def chatbot_status() -> ChatbotStatusResponse:
    return ChatbotStatusResponse(**get_chatbot_status(settings))


@router.get("/skills/status", response_model=ChatbotSkillStatusResponse)
def chatbot_skills_status() -> ChatbotSkillStatusResponse:
    return ChatbotSkillStatusResponse(**get_skill_status(settings))


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
        briefing_type=request.briefing_type,
        question_id=request.question_id,
        conversation_id=request.conversation_id,
    )
    return ChatbotAssessmentResponse(**payload)


@router.post("/conversations", response_model=ChatbotConversationResponse)
def chatbot_create_conversation(request: ChatbotConversationCreateRequest) -> ChatbotConversationResponse:
    payload = create_chatbot_conversation(
        settings=settings,
        selected_context=request.selected_context,
        briefing_type=request.briefing_type,
        mode=request.mode,
    )
    return ChatbotConversationResponse(**payload)


@router.get("/conversations/{conversation_id}", response_model=ChatbotConversationResponse)
def chatbot_get_conversation(conversation_id: str) -> ChatbotConversationResponse:
    payload = get_chatbot_conversation(settings, conversation_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada.")
    return ChatbotConversationResponse(**payload)


@router.post("/conversations/{conversation_id}/messages", response_model=ChatbotConversationMessageResponse)
def chatbot_send_message(
    conversation_id: str,
    request: ChatbotConversationMessageRequest,
) -> ChatbotConversationMessageResponse:
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message es obligatorio.")
    payload = send_chatbot_message(
        settings=settings,
        conversation_id=conversation_id,
        message=request.message,
        briefing_type=request.briefing_type,
        selected_context=request.selected_context,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada.")
    return ChatbotConversationMessageResponse(**payload)


@router.post("/feedback", response_model=ChatbotFeedbackResponse)
def chatbot_feedback(request: ChatbotFeedbackRequest) -> ChatbotFeedbackResponse:
    try:
        payload = submit_chatbot_feedback(
            settings=settings,
            conversation_id=request.conversation_id,
            turn_id=request.turn_id,
            rating=request.rating,
            comment=request.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ChatbotFeedbackResponse(**payload)
