import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin
from app.db.enums import ChatConfidence, ChatFeedback, ChatIntent, ChatRole
from app.db.pg_types import (
    chat_confidence_enum,
    chat_feedback_enum,
    chat_intent_enum,
    chat_role_enum,
)

if TYPE_CHECKING:
    from app.db.models.chat_session import ChatSession


class ChatMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False, index=True
    )
    role: Mapped[ChatRole] = mapped_column(chat_role_enum, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Assistant messages only — null on user/system messages.
    confidence: Mapped[ChatConfidence | None] = mapped_column(chat_confidence_enum)
    intent: Mapped[ChatIntent | None] = mapped_column(chat_intent_enum)
    # Serialized list[ChatCitation] (schemas/chat.py) — null until an
    # assistant message has passed the faithfulness guardrail.
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # Serialized AnswerDiagnostics (schemas/chat.py) — populated only when
    # confidence=INSUFFICIENT_INFORMATION, so a declined answer can be
    # explained (what was retrieved, at what scores, and which stage
    # turned it away) instead of just showing the fixed apology string.
    # Null for a real answer and for out_of_scope/calendar_query turns,
    # which never retrieve.
    retrieval_diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # Plan §9 lists this as a nullable enum including "none" as a value;
    # collapsed to a single non-nullable column with NONE as the default
    # instead, so "no feedback yet" has exactly one representation rather
    # than two (NULL vs. 'none').
    feedback: Mapped[ChatFeedback] = mapped_column(
        chat_feedback_enum, nullable=False, default=ChatFeedback.NONE
    )
    # Links this message to its full observability trace in the
    # self-hosted Langfuse instance — see services/observability.py. Null
    # whenever Langfuse isn't configured/reachable; tracing is best-effort
    # and must never block the chat pipeline itself.
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(64))

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
