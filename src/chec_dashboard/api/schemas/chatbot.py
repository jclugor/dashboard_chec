from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatbotAPIModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=("model_validate", "model_dump"))


class ChatbotStatusResponse(ChatbotAPIModel):
    enabled: bool
    gemini_configured: bool
    corpus_available: bool
    ready: bool
    documents_count: int = 0
    chunks_count: int = 0
    message: str


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


class ChatbotAssessmentResponse(ChatbotAPIModel):
    answer: str
    citations: list[ChatbotCitation] = Field(default_factory=list)
    status_text: str
    ready: bool
    briefing_type: Literal["reliability", "compliance", "maintenance"] = "reliability"
