from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatbotAPIModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_validate", "model_dump"))


class ChatbotStatusResponse(ChatbotAPIModel):
    enabled: bool
    llm_provider: str = "mock"
    llm_configured: bool = False
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
