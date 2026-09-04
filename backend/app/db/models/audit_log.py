import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Records who accessed/modified what and when — a compliance
    requirement, not optional polish. See
    docs/CONTRACT_CLM_BUILD_PLAN.md §6.9."""

    __tablename__ = "audit_log"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # Mapped to the "metadata" column under a non-"metadata" attribute name —
    # `metadata` is reserved on every SQLAlchemy declarative model (it's the
    # class-level `MetaData` object).
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)

    ip_address: Mapped[str | None] = mapped_column(INET)
