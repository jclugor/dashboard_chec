from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatbotAPIModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_validate", "model_dump"))


class ChatbotStatusResponse(ChatbotAPIModel):
    enabled: bool
    llm_provider: str = "mock"
    llm_configured: bool = False
    llm_endpoint_configured: bool = True
    model_endpoint_name: str | None = None
    llm_max_tokens: int | None = None
    llm_temperature: float | None = None
    gemini_configured: bool
    corpus_available: bool
    ready: bool
    skills_available: bool = False
    skills_count: int = 0
    skill_errors_count: int = 0
    documents_count: int = 0
    chunks_count: int = 0
    message: str


class ChatbotSkillStatusItem(ChatbotAPIModel):
    skill_id: str | None = None
    version: str | None = None
    status: str | None = None
    source_type: str
    source_path: str
    skill_hash: str | None = None
    errors: list[str] = Field(default_factory=list)
    file_name: str | None = None


class ChatbotSkillStatusResponse(ChatbotAPIModel):
    skills_available: bool
    skills_count: int
    skill_errors_count: int
    supported_file_types: list[str] = Field(default_factory=list)
    lifecycle_directories: dict[str, Any] = Field(default_factory=dict)
    skills: list[ChatbotSkillStatusItem] = Field(default_factory=list)
    validation_errors: list[ChatbotSkillStatusItem] = Field(default_factory=list)


class ChatbotContextOptionsRequest(ChatbotAPIModel):
    context_kind: Literal["view", "event", "asset"]
    selected_period: str
    selected_municipio: str
    selected_circuits: list[str] | None = None
    search: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class ChatbotContextItem(ChatbotAPIModel):
    id: str
    label: str
    kind: Literal["view", "event", "asset"]
    summary: str
    context: dict[str, Any] = Field(default_factory=dict)


class ChatbotContextOptionsResponse(ChatbotAPIModel):
    items: list[ChatbotContextItem] = Field(default_factory=list)
    status_text: str


class ChatbotCitation(ChatbotAPIModel):
    id: str
    title: str
    source_path: str | None = None
    page: int | None = None
    snippet: str
    score: float


class ChatbotAssessmentRequest(ChatbotAPIModel):
    selected_context: dict[str, Any] = Field(default_factory=dict)
    question: str | None = None
    briefing_type: Literal["reliability", "compliance", "maintenance"] = "reliability"
    question_id: str | None = None
    conversation_id: str | None = None


class ChatbotAssessmentResponse(ChatbotAPIModel):
    answer: str
    citations: list[ChatbotCitation] = Field(default_factory=list)
    status_text: str
    ready: bool
    briefing_type: Literal["reliability", "compliance", "maintenance"] = "reliability"
    conversation_id: str | None = None
    turn_id: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    skill_hash: str | None = None
    trace_id: str | None = None
    llm_provider: str | None = None
    model_endpoint_name: str | None = None


class ChatbotConversationMessage(ChatbotAPIModel):
    conversation_id: str
    turn_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str | None = None
    briefing_type: Literal["reliability", "compliance", "maintenance"] = "reliability"
    question_id: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    skill_hash: str | None = None
    trace_id: str | None = None
    llm_provider: str | None = None
    model_endpoint_name: str | None = None
    citations: list[ChatbotCitation] = Field(default_factory=list)
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    status_text: str | None = None
    ready: bool = True


class ChatbotConversationCreateRequest(ChatbotAPIModel):
    selected_context: dict[str, Any] = Field(default_factory=dict)
    briefing_type: Literal["reliability", "compliance", "maintenance"] = "reliability"
    mode: Literal["guided", "free_form"] = "guided"


class ChatbotConversationResponse(ChatbotAPIModel):
    conversation_id: str
    mode: str = "guided"
    briefing_type: Literal["reliability", "compliance", "maintenance"] = "reliability"
    title: str | None = None
    context_snapshot: dict[str, Any] = Field(default_factory=dict)
    skill_id: str | None = None
    skill_version: str | None = None
    skill_hash: str | None = None
    llm_provider: str | None = None
    model_endpoint_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    messages: list[ChatbotConversationMessage] = Field(default_factory=list)


class ChatbotConversationMessageRequest(ChatbotAPIModel):
    message: str
    briefing_type: Literal["reliability", "compliance", "maintenance"] | None = None
    selected_context: dict[str, Any] | None = None


class ChatbotConversationMessageResponse(ChatbotAssessmentResponse):
    pass


class ChatbotFeedbackRequest(ChatbotAPIModel):
    conversation_id: str
    turn_id: str
    rating: Literal["helpful", "not_helpful"]
    comment: str | None = None


class ChatbotFeedbackResponse(ChatbotAPIModel):
    feedback_id: str
    conversation_id: str
    turn_id: str
    rating: Literal["helpful", "not_helpful"]
    comment: str | None = None
    created_at: str | None = None
    status_text: str
