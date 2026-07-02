from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from threading import Lock
from typing import Any, Protocol
import uuid

from chec_dashboard.core.config import Settings
from chec_dashboard.services.databricks_sql import (
    DatabricksSQLWarehouseClient,
    sql_literal,
    sql_table_name,
)


@dataclass(frozen=True)
class ConversationTurn:
    conversation_id: str
    turn_id: str


@dataclass
class ConversationRecord:
    conversation_id: str
    mode: str = "guided"
    briefing_type: str = "reliability"
    analysis_stage: str | None = None
    title: str | None = None
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    skill_id: str | None = None
    skill_version: str | None = None
    skill_hash: str | None = None
    llm_provider: str | None = None
    model_endpoint_name: str | None = None
    created_at: str = field(default_factory=lambda: _utc_now())
    updated_at: str = field(default_factory=lambda: _utc_now())


@dataclass
class ConversationMessage:
    conversation_id: str
    turn_id: str
    role: str
    content: str
    created_at: str = field(default_factory=lambda: _utc_now())
    briefing_type: str = "reliability"
    analysis_stage: str | None = None
    question_id: str | None = None
    skill_id: str | None = None
    skill_version: str | None = None
    skill_hash: str | None = None
    trace_id: str | None = None
    llm_provider: str | None = None
    model_endpoint_name: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieved_chunk_ids: list[str] = field(default_factory=list)
    status_text: str | None = None
    ready: bool = True
    agent_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    agent_skipped_tools: list[dict[str, Any]] = field(default_factory=list)
    agent_route_summary: dict[str, Any] = field(default_factory=dict)
    structured_answer: dict[str, Any] = field(default_factory=dict)
    answer_validation: dict[str, Any] = field(default_factory=dict)
    citation_validation: dict[str, Any] = field(default_factory=dict)
    compliance_validation: dict[str, Any] = field(default_factory=dict)
    prompt_name: str | None = None
    prompt_alias: str | None = None
    prompt_version: str | None = None
    prompt_hash: str | None = None
    mlflow_trace_id: str | None = None
    mlflow_run_id: str | None = None
    latency_ms: int | None = None
    capability_id: str | None = None
    capability_status: str | None = None
    capability_tier: str | None = None
    safe_fallback_used: bool | None = None
    validation_status: str | None = None
    missing_requirements: list[str] = field(default_factory=list)
    contract_name: str | None = None
    contract_version: str | None = None
    contract_hash: str | None = None
    stage_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationFeedback:
    feedback_id: str
    conversation_id: str
    turn_id: str
    rating: str
    comment: str | None = None
    created_at: str = field(default_factory=lambda: _utc_now())


class ConversationStore(Protocol):
    def upsert_conversation(self, conversation: ConversationRecord) -> None:
        ...

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        ...

    def list_messages(self, conversation_id: str, *, limit: int | None = None) -> list[ConversationMessage]:
        ...

    def append_messages(self, messages: list[ConversationMessage]) -> None:
        ...

    def add_feedback(self, feedback: ConversationFeedback) -> None:
        ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if value in {None, ""}:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _sql_json(payload: Any) -> str:
    return sql_literal(_json_dumps(payload))


def _row_value(row: Any, key: str) -> Any:
    if hasattr(row, "get"):
        return row.get(key)
    return getattr(row, key)


def resolve_conversation_turn(conversation_id: str | None = None) -> ConversationTurn:
    return ConversationTurn(
        conversation_id=(conversation_id or f"conv-{uuid.uuid4().hex}"),
        turn_id=f"turn-{uuid.uuid4().hex}",
    )


def conversation_payload(
    conversation: ConversationRecord,
    messages: list[ConversationMessage] | None = None,
) -> dict[str, Any]:
    return {
        "conversation_id": conversation.conversation_id,
        "mode": conversation.mode,
        "briefing_type": conversation.briefing_type,
        "analysis_stage": conversation.analysis_stage,
        "title": conversation.title,
        "context_snapshot": conversation.context_snapshot,
        "skill_id": conversation.skill_id,
        "skill_version": conversation.skill_version,
        "skill_hash": conversation.skill_hash,
        "llm_provider": conversation.llm_provider,
        "model_endpoint_name": conversation.model_endpoint_name,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "messages": [message_payload(message) for message in (messages or [])],
    }


def message_payload(message: ConversationMessage) -> dict[str, Any]:
    return {
        "conversation_id": message.conversation_id,
        "turn_id": message.turn_id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at,
        "briefing_type": message.briefing_type,
        "analysis_stage": message.analysis_stage,
        "question_id": message.question_id,
        "skill_id": message.skill_id,
        "skill_version": message.skill_version,
        "skill_hash": message.skill_hash,
        "trace_id": message.trace_id,
        "llm_provider": message.llm_provider,
        "model_endpoint_name": message.model_endpoint_name,
        "citations": message.citations,
        "retrieved_chunk_ids": message.retrieved_chunk_ids,
        "status_text": message.status_text,
        "ready": message.ready,
        "agent_tool_calls": message.agent_tool_calls,
        "agent_skipped_tools": message.agent_skipped_tools,
        "agent_route_summary": message.agent_route_summary,
        "structured_answer": message.structured_answer,
        "answer_validation": message.answer_validation,
        "citation_validation": message.citation_validation,
        "compliance_validation": message.compliance_validation,
        "prompt_name": message.prompt_name,
        "prompt_alias": message.prompt_alias,
        "prompt_version": message.prompt_version,
        "prompt_hash": message.prompt_hash,
        "mlflow_trace_id": message.mlflow_trace_id,
        "mlflow_run_id": message.mlflow_run_id,
        "latency_ms": message.latency_ms,
        "capability_id": message.capability_id,
        "capability_status": message.capability_status,
        "capability_tier": message.capability_tier,
        "safe_fallback_used": message.safe_fallback_used,
        "validation_status": message.validation_status,
        "missing_requirements": message.missing_requirements,
        "contract_name": message.contract_name,
        "contract_version": message.contract_version,
        "contract_hash": message.contract_hash,
        "stage_metadata": message.stage_metadata,
        **(message.stage_metadata or {}),
    }


class MemoryConversationStore:
    def __init__(self) -> None:
        self._conversations: dict[str, ConversationRecord] = {}
        self._messages: dict[str, list[ConversationMessage]] = {}
        self._feedback: list[ConversationFeedback] = []
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._conversations.clear()
            self._messages.clear()
            self._feedback.clear()

    def upsert_conversation(self, conversation: ConversationRecord) -> None:
        with self._lock:
            existing = self._conversations.get(conversation.conversation_id)
            if existing is not None:
                conversation.created_at = existing.created_at
            conversation.updated_at = _utc_now()
            self._conversations[conversation.conversation_id] = conversation
            self._messages.setdefault(conversation.conversation_id, [])

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self._lock:
            return self._conversations.get(conversation_id)

    def list_messages(self, conversation_id: str, *, limit: int | None = None) -> list[ConversationMessage]:
        with self._lock:
            messages = list(self._messages.get(conversation_id, []))
        if limit is not None and limit > 0:
            return messages[-limit:]
        return messages

    def append_messages(self, messages: list[ConversationMessage]) -> None:
        with self._lock:
            for message in messages:
                self._messages.setdefault(message.conversation_id, []).append(message)

    def add_feedback(self, feedback: ConversationFeedback) -> None:
        with self._lock:
            self._feedback.append(feedback)


class DatabricksSQLConversationStore:
    def __init__(self, settings: Settings, client: DatabricksSQLWarehouseClient | None = None):
        self._settings = settings
        self._client = client or DatabricksSQLWarehouseClient(settings)

    @property
    def conversations_table(self) -> str:
        return sql_table_name(
            self._settings.databricks_catalog_name,
            self._settings.chatbot_conversation_schema,
            "agent_conversations",
        )

    @property
    def messages_table(self) -> str:
        return sql_table_name(
            self._settings.databricks_catalog_name,
            self._settings.chatbot_conversation_schema,
            "agent_messages",
        )

    @property
    def feedback_table(self) -> str:
        return sql_table_name(
            self._settings.databricks_catalog_name,
            self._settings.chatbot_conversation_schema,
            "agent_feedback",
        )

    def upsert_conversation(self, conversation: ConversationRecord) -> None:
        statement = f"""
MERGE INTO {self.conversations_table} target
USING (
  SELECT
    {sql_literal(conversation.conversation_id)} AS conversation_id,
    {sql_literal(conversation.mode)} AS mode,
    {sql_literal(conversation.briefing_type)} AS briefing_type,
    {sql_literal(conversation.analysis_stage)} AS analysis_stage,
    {sql_literal(conversation.title)} AS title,
    {_sql_json(conversation.context_snapshot)} AS context_snapshot_json,
    {sql_literal(conversation.skill_id)} AS skill_id,
    {sql_literal(conversation.skill_version)} AS skill_version,
    {sql_literal(conversation.skill_hash)} AS skill_hash,
    {sql_literal(conversation.llm_provider)} AS llm_provider,
    {sql_literal(conversation.model_endpoint_name)} AS model_endpoint_name
) source
ON target.conversation_id = source.conversation_id
WHEN MATCHED THEN UPDATE SET
  updated_at = current_timestamp(),
  mode = source.mode,
  briefing_type = source.briefing_type,
  analysis_stage = source.analysis_stage,
  title = source.title,
  context_snapshot_json = source.context_snapshot_json,
  skill_id = source.skill_id,
  skill_version = source.skill_version,
  skill_hash = source.skill_hash,
  llm_provider = source.llm_provider,
  model_endpoint_name = source.model_endpoint_name
WHEN NOT MATCHED THEN INSERT (
  conversation_id, created_at, updated_at, mode, briefing_type, title,
  analysis_stage, context_snapshot_json, skill_id, skill_version, skill_hash, llm_provider,
  model_endpoint_name
) VALUES (
  source.conversation_id, current_timestamp(), current_timestamp(), source.mode,
  source.briefing_type, source.title, source.analysis_stage, source.context_snapshot_json, source.skill_id,
  source.skill_version, source.skill_hash, source.llm_provider, source.model_endpoint_name
)
""".strip()
        self._client.fetch_dataframe(statement)

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        frame = self._client.fetch_dataframe(
            f"""
SELECT conversation_id, created_at, updated_at, mode, briefing_type, analysis_stage, title,
       context_snapshot_json, skill_id, skill_version, skill_hash, llm_provider,
       model_endpoint_name
FROM {self.conversations_table}
WHERE conversation_id = {sql_literal(conversation_id)}
LIMIT 1
""".strip()
        )
        if frame.empty:
            return None
        row = frame.iloc[0]
        return ConversationRecord(
            conversation_id=str(_row_value(row, "conversation_id")),
            mode=str(_row_value(row, "mode") or "guided"),
            briefing_type=str(_row_value(row, "briefing_type") or "reliability"),
            analysis_stage=_row_value(row, "analysis_stage"),
            title=_row_value(row, "title"),
            context_snapshot=_json_loads(_row_value(row, "context_snapshot_json"), {}),
            skill_id=_row_value(row, "skill_id"),
            skill_version=_row_value(row, "skill_version"),
            skill_hash=_row_value(row, "skill_hash"),
            llm_provider=_row_value(row, "llm_provider"),
            model_endpoint_name=_row_value(row, "model_endpoint_name"),
            created_at=str(_row_value(row, "created_at") or ""),
            updated_at=str(_row_value(row, "updated_at") or ""),
        )

    def list_messages(self, conversation_id: str, *, limit: int | None = None) -> list[ConversationMessage]:
        limit_clause = f"LIMIT {int(limit)}" if limit and limit > 0 else ""
        frame = self._client.fetch_dataframe(
            f"""
SELECT conversation_id, turn_id, role, content, created_at, briefing_type, analysis_stage,
       question_id, skill_id, skill_version, skill_hash, trace_id, llm_provider,
       model_endpoint_name, citations_json, retrieved_chunk_ids_json, status_text, ready,
       agent_tool_calls_json, agent_skipped_tools_json, agent_route_summary_json,
       structured_answer_json, answer_validation_json, citation_validation_json,
       compliance_validation_json, prompt_name, prompt_alias, prompt_version,
       prompt_hash, mlflow_trace_id, mlflow_run_id, latency_ms,
       capability_id, capability_status, capability_tier, safe_fallback_used,
       validation_status, missing_requirements_json, contract_name, contract_version,
       contract_hash, stage_metadata_json
FROM {self.messages_table}
WHERE conversation_id = {sql_literal(conversation_id)}
ORDER BY created_at ASC, CASE role WHEN 'user' THEN 0 ELSE 1 END ASC
{limit_clause}
""".strip()
        )
        if frame.empty:
            return []
        return [self._message_from_row(row) for _, row in frame.iterrows()]

    def append_messages(self, messages: list[ConversationMessage]) -> None:
        for message in messages:
            self._client.fetch_dataframe(
                f"""
INSERT INTO {self.messages_table} (
  conversation_id, turn_id, role, content, created_at, briefing_type, question_id,
  analysis_stage, skill_id, skill_version, skill_hash, trace_id, llm_provider, model_endpoint_name, citations_json,
  retrieved_chunk_ids_json, status_text, ready, agent_tool_calls_json,
  agent_skipped_tools_json, agent_route_summary_json, structured_answer_json,
  answer_validation_json, citation_validation_json, compliance_validation_json,
  prompt_name, prompt_alias, prompt_version, prompt_hash, mlflow_trace_id,
  mlflow_run_id, latency_ms, capability_id, capability_status, capability_tier,
  safe_fallback_used, validation_status, missing_requirements_json, contract_name,
  contract_version, contract_hash, stage_metadata_json
) VALUES (
  {sql_literal(message.conversation_id)},
  {sql_literal(message.turn_id)},
  {sql_literal(message.role)},
  {sql_literal(message.content)},
  current_timestamp(),
  {sql_literal(message.briefing_type)},
  {sql_literal(message.question_id)},
  {sql_literal(message.analysis_stage)},
  {sql_literal(message.skill_id)},
  {sql_literal(message.skill_version)},
  {sql_literal(message.skill_hash)},
  {sql_literal(message.trace_id)},
  {sql_literal(message.llm_provider)},
  {sql_literal(message.model_endpoint_name)},
  {_sql_json(message.citations)},
  {_sql_json(message.retrieved_chunk_ids)},
  {sql_literal(message.status_text)},
  {sql_literal(message.ready)},
  {_sql_json(message.agent_tool_calls)},
  {_sql_json(message.agent_skipped_tools)},
  {_sql_json(message.agent_route_summary)},
  {_sql_json(message.structured_answer)},
  {_sql_json(message.answer_validation)},
  {_sql_json(message.citation_validation)},
  {_sql_json(message.compliance_validation)},
  {sql_literal(message.prompt_name)},
  {sql_literal(message.prompt_alias)},
  {sql_literal(message.prompt_version)},
  {sql_literal(message.prompt_hash)},
  {sql_literal(message.mlflow_trace_id)},
  {sql_literal(message.mlflow_run_id)},
  {sql_literal(message.latency_ms)},
  {sql_literal(message.capability_id)},
  {sql_literal(message.capability_status)},
  {sql_literal(message.capability_tier)},
  {sql_literal(message.safe_fallback_used)},
  {sql_literal(message.validation_status)},
  {_sql_json(message.missing_requirements)},
  {sql_literal(message.contract_name)},
  {sql_literal(message.contract_version)},
  {sql_literal(message.contract_hash)},
  {_sql_json(message.stage_metadata)}
)
""".strip()
            )

    def add_feedback(self, feedback: ConversationFeedback) -> None:
        self._client.fetch_dataframe(
            f"""
INSERT INTO {self.feedback_table} (
  feedback_id, conversation_id, turn_id, rating, comment, created_at
) VALUES (
  {sql_literal(feedback.feedback_id)},
  {sql_literal(feedback.conversation_id)},
  {sql_literal(feedback.turn_id)},
  {sql_literal(feedback.rating)},
  {sql_literal(feedback.comment)},
  current_timestamp()
)
""".strip()
        )

    @staticmethod
    def _message_from_row(row: Any) -> ConversationMessage:
        return ConversationMessage(
            conversation_id=str(_row_value(row, "conversation_id")),
            turn_id=str(_row_value(row, "turn_id")),
            role=str(_row_value(row, "role")),
            content=str(_row_value(row, "content") or ""),
            created_at=str(_row_value(row, "created_at") or ""),
            briefing_type=str(_row_value(row, "briefing_type") or "reliability"),
            analysis_stage=_row_value(row, "analysis_stage"),
            question_id=_row_value(row, "question_id"),
            skill_id=_row_value(row, "skill_id"),
            skill_version=_row_value(row, "skill_version"),
            skill_hash=_row_value(row, "skill_hash"),
            trace_id=_row_value(row, "trace_id"),
            llm_provider=_row_value(row, "llm_provider"),
            model_endpoint_name=_row_value(row, "model_endpoint_name"),
            citations=_json_loads(_row_value(row, "citations_json"), []),
            retrieved_chunk_ids=_json_loads(_row_value(row, "retrieved_chunk_ids_json"), []),
            status_text=_row_value(row, "status_text"),
            ready=bool(_row_value(row, "ready")),
            agent_tool_calls=_json_loads(_row_value(row, "agent_tool_calls_json"), []),
            agent_skipped_tools=_json_loads(_row_value(row, "agent_skipped_tools_json"), []),
            agent_route_summary=_json_loads(_row_value(row, "agent_route_summary_json"), {}),
            structured_answer=_json_loads(_row_value(row, "structured_answer_json"), {}),
            answer_validation=_json_loads(_row_value(row, "answer_validation_json"), {}),
            citation_validation=_json_loads(_row_value(row, "citation_validation_json"), {}),
            compliance_validation=_json_loads(_row_value(row, "compliance_validation_json"), {}),
            prompt_name=_row_value(row, "prompt_name"),
            prompt_alias=_row_value(row, "prompt_alias"),
            prompt_version=_row_value(row, "prompt_version"),
            prompt_hash=_row_value(row, "prompt_hash"),
            mlflow_trace_id=_row_value(row, "mlflow_trace_id"),
            mlflow_run_id=_row_value(row, "mlflow_run_id"),
            latency_ms=_row_value(row, "latency_ms"),
            capability_id=_row_value(row, "capability_id"),
            capability_status=_row_value(row, "capability_status"),
            capability_tier=_row_value(row, "capability_tier"),
            safe_fallback_used=bool(_row_value(row, "safe_fallback_used")) if _row_value(row, "safe_fallback_used") is not None else None,
            validation_status=_row_value(row, "validation_status"),
            missing_requirements=_json_loads(_row_value(row, "missing_requirements_json"), []),
            contract_name=_row_value(row, "contract_name"),
            contract_version=_row_value(row, "contract_version"),
            contract_hash=_row_value(row, "contract_hash"),
            stage_metadata=_json_loads(_row_value(row, "stage_metadata_json"), {}),
        )


_MEMORY_STORE = MemoryConversationStore()


def get_conversation_store(settings: Settings) -> ConversationStore:
    if settings.chatbot_conversation_backend == "databricks_sql":
        return DatabricksSQLConversationStore(settings)
    return _MEMORY_STORE


def reset_memory_conversation_store() -> None:
    _MEMORY_STORE.clear()


def create_conversation(
    settings: Settings,
    *,
    conversation_id: str | None = None,
    mode: str = "guided",
    briefing_type: str = "reliability",
    analysis_stage: str | None = None,
    selected_context: dict[str, Any] | None = None,
    title: str | None = None,
    skill_id: str | None = None,
    skill_version: str | None = None,
    skill_hash: str | None = None,
    llm_provider: str | None = None,
    model_endpoint_name: str | None = None,
) -> ConversationRecord:
    record = ConversationRecord(
        conversation_id=conversation_id or resolve_conversation_turn().conversation_id,
        mode=mode,
        briefing_type=briefing_type,
        analysis_stage=analysis_stage,
        title=title,
        context_snapshot=selected_context or {},
        skill_id=skill_id,
        skill_version=skill_version,
        skill_hash=skill_hash,
        llm_provider=llm_provider,
        model_endpoint_name=model_endpoint_name,
    )
    get_conversation_store(settings).upsert_conversation(record)
    return record


def get_conversation_detail(settings: Settings, conversation_id: str) -> dict[str, Any] | None:
    store = get_conversation_store(settings)
    conversation = store.get_conversation(conversation_id)
    if conversation is None:
        return None
    messages = store.list_messages(conversation_id)
    return conversation_payload(conversation, messages)


def recent_conversation_messages(
    settings: Settings,
    conversation_id: str,
) -> list[dict[str, Any]]:
    limit = settings.chatbot_memory_max_turns * 2
    all_messages = get_conversation_store(settings).list_messages(conversation_id)
    messages = _bounded_memory_messages(all_messages, limit=limit)
    return [message_payload(message) for message in messages]


def record_conversation_turn(
    settings: Settings,
    *,
    conversation_id: str,
    turn_id: str,
    user_message: str,
    assistant_message: str,
    briefing_type: str,
    question_id: str | None,
    context_snapshot: dict[str, Any],
    skill_id: str | None,
    skill_version: str | None,
    skill_hash: str | None,
    trace_id: str | None,
    llm_provider: str | None,
    model_endpoint_name: str | None,
    citations: list[dict[str, Any]],
    retrieved_chunk_ids: list[str],
    status_text: str,
    ready: bool,
    agent_tool_calls: list[dict[str, Any]] | None = None,
    agent_skipped_tools: list[dict[str, Any]] | None = None,
    agent_route_summary: dict[str, Any] | None = None,
    structured_answer: dict[str, Any] | None = None,
    answer_validation: dict[str, Any] | None = None,
    citation_validation: dict[str, Any] | None = None,
    compliance_validation: dict[str, Any] | None = None,
    prompt_name: str | None = None,
    prompt_alias: str | None = None,
    prompt_version: str | None = None,
    prompt_hash: str | None = None,
    mlflow_trace_id: str | None = None,
    mlflow_run_id: str | None = None,
    latency_ms: int | None = None,
    mode: str = "guided",
    analysis_stage: str | None = None,
    capability_id: str | None = None,
    capability_status: str | None = None,
    capability_tier: str | None = None,
    safe_fallback_used: bool | None = None,
    validation_status: str | None = None,
    missing_requirements: list[str] | None = None,
    contract_name: str | None = None,
    contract_version: str | None = None,
    contract_hash: str | None = None,
    stage_metadata: dict[str, Any] | None = None,
) -> None:
    store = get_conversation_store(settings)
    conversation = ConversationRecord(
        conversation_id=conversation_id,
        mode=mode,
        briefing_type=briefing_type,
        analysis_stage=analysis_stage,
        title=_conversation_title(user_message),
        context_snapshot=context_snapshot,
        skill_id=skill_id,
        skill_version=skill_version,
        skill_hash=skill_hash,
        llm_provider=llm_provider,
        model_endpoint_name=model_endpoint_name,
    )
    store.upsert_conversation(conversation)
    store.append_messages(
        [
            ConversationMessage(
                conversation_id=conversation_id,
                turn_id=turn_id,
                role="user",
                content=user_message,
                briefing_type=briefing_type,
                analysis_stage=analysis_stage,
                question_id=question_id,
                skill_id=skill_id,
                skill_version=skill_version,
                skill_hash=skill_hash,
                trace_id=trace_id,
                llm_provider=llm_provider,
                model_endpoint_name=model_endpoint_name,
                ready=ready,
                prompt_name=prompt_name,
                prompt_alias=prompt_alias,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                mlflow_trace_id=mlflow_trace_id,
                mlflow_run_id=mlflow_run_id,
                latency_ms=latency_ms,
                capability_id=capability_id,
                capability_status=capability_status,
                capability_tier=capability_tier,
                safe_fallback_used=safe_fallback_used,
                validation_status=validation_status,
                missing_requirements=missing_requirements or [],
                contract_name=contract_name,
                contract_version=contract_version,
                contract_hash=contract_hash,
                stage_metadata=stage_metadata or {},
            ),
            ConversationMessage(
                conversation_id=conversation_id,
                turn_id=turn_id,
                role="assistant",
                content=assistant_message,
                briefing_type=briefing_type,
                analysis_stage=analysis_stage,
                question_id=question_id,
                skill_id=skill_id,
                skill_version=skill_version,
                skill_hash=skill_hash,
                trace_id=trace_id,
                llm_provider=llm_provider,
                model_endpoint_name=model_endpoint_name,
                citations=citations,
                retrieved_chunk_ids=retrieved_chunk_ids,
                status_text=status_text,
                ready=ready,
                agent_tool_calls=agent_tool_calls or [],
                agent_skipped_tools=agent_skipped_tools or [],
                agent_route_summary=agent_route_summary or {},
                structured_answer=structured_answer or {},
                answer_validation=answer_validation or {},
                citation_validation=citation_validation or {},
                compliance_validation=compliance_validation or {},
                prompt_name=prompt_name,
                prompt_alias=prompt_alias,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                mlflow_trace_id=mlflow_trace_id,
                mlflow_run_id=mlflow_run_id,
                latency_ms=latency_ms,
                capability_id=capability_id,
                capability_status=capability_status,
                capability_tier=capability_tier,
                safe_fallback_used=safe_fallback_used,
                validation_status=validation_status,
                missing_requirements=missing_requirements or [],
                contract_name=contract_name,
                contract_version=contract_version,
                contract_hash=contract_hash,
                stage_metadata=stage_metadata or {},
            ),
        ]
    )


def _bounded_memory_messages(messages: list[ConversationMessage], *, limit: int) -> list[ConversationMessage]:
    if limit <= 0 or len(messages) <= limit:
        return messages
    omitted = messages[:-limit]
    recent = messages[-limit:]
    user_count = sum(1 for message in omitted if message.role == "user")
    assistant_count = sum(1 for message in omitted if message.role == "assistant")
    first_text = _compact_message_text(omitted[0].content if omitted else "")
    last_text = _compact_message_text(omitted[-1].content if omitted else "")
    digest_source = "|".join(f"{message.turn_id}:{message.role}:{message.content}" for message in omitted)
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:16]
    summary = ConversationMessage(
        conversation_id=recent[0].conversation_id,
        turn_id=f"memory-{digest}",
        role="assistant",
        content=(
            "Memoria compacta deterministica: "
            f"{len(omitted)} mensajes previos omitidos "
            f"({user_count} usuario, {assistant_count} asistente). "
            f"Primer tema: {first_text or 'N/D'}. "
            f"Ultimo tema antes del historial reciente: {last_text or 'N/D'}."
        ),
        created_at=omitted[-1].created_at if omitted else _utc_now(),
        briefing_type=recent[0].briefing_type,
        skill_id=recent[0].skill_id,
        skill_version=recent[0].skill_version,
        skill_hash=recent[0].skill_hash,
        trace_id=recent[0].trace_id,
        llm_provider=recent[0].llm_provider,
        model_endpoint_name=recent[0].model_endpoint_name,
        ready=True,
    )
    return [summary, *recent]


def _compact_message_text(value: str) -> str:
    return " ".join((value or "").split())[:220]


def record_feedback(
    settings: Settings,
    *,
    conversation_id: str,
    turn_id: str,
    rating: str,
    comment: str | None = None,
) -> dict[str, Any]:
    feedback = ConversationFeedback(
        feedback_id=f"feedback-{uuid.uuid4().hex}",
        conversation_id=conversation_id,
        turn_id=turn_id,
        rating=rating,
        comment=comment,
    )
    get_conversation_store(settings).add_feedback(feedback)
    return {
        "feedback_id": feedback.feedback_id,
        "conversation_id": feedback.conversation_id,
        "turn_id": feedback.turn_id,
        "rating": feedback.rating,
        "comment": feedback.comment,
        "created_at": feedback.created_at,
        "status_text": "Retroalimentación registrada.",
    }


def _conversation_title(message: str) -> str:
    compact = " ".join(message.split())
    return compact[:80] if compact else "Conversación técnica"
