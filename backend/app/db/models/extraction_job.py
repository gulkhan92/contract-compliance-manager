import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.enums import ExtractionJobStatus, LLMProviderName
from app.db.pg_types import extraction_job_status_enum, llm_provider_name_enum

if TYPE_CHECKING:
    from app.db.models.contract import Contract


class ExtractionJob(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "extraction_jobs"

    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id"), nullable=False, index=True
    )
    status: Mapped[ExtractionJobStatus] = mapped_column(
        extraction_job_status_enum,
        nullable=False,
        default=ExtractionJobStatus.QUEUED,
        index=True,
    )
    llm_provider_used: Mapped[LLMProviderName | None] = mapped_column(llm_provider_name_enum)
    tokens_used_estimate: Mapped[int | None] = mapped_column(Integer)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    contract: Mapped["Contract"] = relationship(back_populates="extraction_jobs")
