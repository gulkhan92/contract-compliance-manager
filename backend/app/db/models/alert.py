import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.enums import AlertStatus, AlertType
from app.db.pg_types import alert_status_enum, alert_type_enum

if TYPE_CHECKING:
    from app.db.models.obligation import Obligation
    from app.db.models.user import User


class Alert(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "alerts"

    obligation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("obligations.id"), nullable=False, index=True
    )
    alert_type: Mapped[AlertType] = mapped_column(
        alert_type_enum, nullable=False, default=AlertType.EMAIL
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[AlertStatus] = mapped_column(
        alert_status_enum,
        nullable=False,
        default=AlertStatus.PENDING,
        index=True,
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    obligation: Mapped["Obligation"] = relationship(back_populates="alerts")
    recipient: Mapped["User"] = relationship(foreign_keys=[recipient_user_id])
