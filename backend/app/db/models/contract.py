import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedUpdatedAtMixin, UUIDPrimaryKeyMixin
from app.db.enums import ContractStatus, ContractType
from app.db.pg_types import contract_status_enum, contract_type_enum

if TYPE_CHECKING:
    from app.db.models.contract_chunk import ContractChunk
    from app.db.models.extraction_job import ExtractionJob
    from app.db.models.obligation import Obligation
    from app.db.models.organization import Organization
    from app.db.models.user import User


class Contract(UUIDPrimaryKeyMixin, CreatedUpdatedAtMixin, Base):
    __tablename__ = "contracts"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    counterparty_name: Mapped[str | None] = mapped_column(String(500))
    contract_type: Mapped[ContractType] = mapped_column(
        contract_type_enum, nullable=False, default=ContractType.OTHER
    )

    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[ContractStatus] = mapped_column(
        contract_status_enum,
        nullable=False,
        default=ContractStatus.PROCESSING,
        index=True,
    )

    effective_date: Mapped[date | None] = mapped_column(Date)
    original_expiration_date: Mapped[date | None] = mapped_column(Date)
    governing_law: Mapped[str | None] = mapped_column(String(255))
    contract_value: Mapped[float | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))

    extraction_confidence: Mapped[float | None] = mapped_column()

    organization: Mapped["Organization"] = relationship(back_populates="contracts")
    uploaded_by_user: Mapped["User"] = relationship(
        back_populates="uploaded_contracts", foreign_keys=[uploaded_by]
    )
    chunks: Mapped[list["ContractChunk"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )
    obligations: Mapped[list["Obligation"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )
    extraction_jobs: Mapped[list["ExtractionJob"]] = relationship(
        back_populates="contract", cascade="all, delete-orphan"
    )
