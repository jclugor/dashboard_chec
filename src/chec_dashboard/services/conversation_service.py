from __future__ import annotations

from dataclasses import dataclass
import uuid


@dataclass(frozen=True)
class ConversationTurn:
    conversation_id: str
    turn_id: str


def resolve_conversation_turn(conversation_id: str | None = None) -> ConversationTurn:
    return ConversationTurn(
        conversation_id=(conversation_id or f"conv-{uuid.uuid4().hex}"),
        turn_id=f"turn-{uuid.uuid4().hex}",
    )
