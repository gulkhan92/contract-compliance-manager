import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedUpdatedAtMixin, UUIDPrimaryKeyMixin
from app.db.enums import ObligationCategory, ObligationStatus, RecurrenceType
from app.db.pg_types import obligation_category_enum, obligation_status_enum, recurrence_type_enum

if TYPE_CHECKING:
    from app.db.models.alert import Alert
    from app.db.models.contract import Contract
    from app.db.models.contract_chunk import ContractChunk
    from app.db.models.user import User


class Obligation(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    __tablename__ = "obligations"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False, index=True
    )
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_chunks.id")
    )

    category: Mapped[ObligationCategory] = mapped_column(
        obligation_category_enum, nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    responsible_party: Mapped[str | None] = mapped_column(String(500))

    trigger_date: Mapped[date | None] = mapped_column(Date, index=True)
    notice_period_days: Mapped[int | None] = mapped_column()
    computed_alert_date: Mapped[date | None] = mapped_column(Date, index=True)

    monetary_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))

    recurrence: Mapped[RecurrenceType] = mapped_column(
        recurrence_type_enum,
        nullable=False,
        default=RecurrenceType.NONE,
    )
    status: Mapped[ObligationStatus] = mapped_column(
        obligation_status_enum,
        nullable=False,
        default=ObligationStatus.UPCOMING,
        index=True,
    )
    confidence_score: Mapped[float | None] = mapped_column()
    is_human_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    raw_source_text: Mapped[str | None] = mapped_column(Text)

    contract: Mapped["Contract"] = relationship(back_populates="obligations")
    source_chunk: Mapped["ContractChunk | None"] = relationship(back_populates="obligations")
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assigned_to])
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="obligation", cascade="all, delete-orphan"
    )
