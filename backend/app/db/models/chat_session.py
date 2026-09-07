import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedUpdatedAtMixin, UUIDPrimaryKeyMixin
from app.db.enums import ChatSessionScope
from app.db.pg_types import chat_session_scope_enum

if TYPE_CHECKING:
    from app.db.models.chat_message import ChatMessage
    from app.db.models.contract import Contract


class ChatSession(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    __tablename__ = "chat_sessions"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    scope: Mapped[ChatSessionScope] = mapped_column(chat_session_scope_enum, nullable=False)
    # Set only when scope=contract — a "Chat about this contract" session.
    # An org-wide session (scope=organization) leaves this null and can
    # still reference any of the org's contracts in its retrieved citations.
    contract_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id")
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    contract: Mapped["Contract | None"] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.created_at"
    )
