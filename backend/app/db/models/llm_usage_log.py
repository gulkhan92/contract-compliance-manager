from datetime import date as date_type
from datetime import datetime

from sqlalchemy import Date, DateTime, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.enums import LLMProviderName
from app.db.pg_types import llm_provider_name_enum


class LLMUsageLog(UUIDPrimaryKeyMixin, Base):
    """One row per (provider, date); read before every LLM call to pick a
    provider with headroom, incremented after every call. See
    docs/CONTRACT_CLM_BUILD_PLAN.md §3 (dual-provider failover)."""

    __tablename__ = "llm_usage_log"
    __table_args__ = (UniqueConstraint("provider", "date", name="uq_llm_usage_log_provider_date"),)

    provider: Mapped[LLMProviderName] = mapped_column(llm_provider_name_enum, nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    requests_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
