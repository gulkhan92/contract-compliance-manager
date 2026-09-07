"""Quota-aware provider selection: read today's usage from llm_usage_log
*before* making a call and pick whichever provider has headroom, rather
than trying-and-catching-429 on every request. See
docs/CONTRACT_CLM_BUILD_PLAN.md §3 (dual-provider failover).
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.enums import LLMProviderName
from app.db.models import LLMUsageLog

# Groq first (primary, per plan §3), Gemini second (fallback).
PROVIDER_ORDER: tuple[LLMProviderName, ...] = (LLMProviderName.GROQ, LLMProviderName.GEMINI)


@dataclass(frozen=True)
class ProviderLimits:
    requests_per_day: int
    tokens_per_day: int


def _provider_limits() -> dict[LLMProviderName, ProviderLimits]:
    settings = get_settings()
    return {
        LLMProviderName.GROQ: ProviderLimits(
            requests_per_day=settings.groq_daily_request_limit,
            tokens_per_day=settings.groq_daily_token_limit,
        ),
        LLMProviderName.GEMINI: ProviderLimits(
            requests_per_day=settings.gemini_daily_request_limit,
            tokens_per_day=settings.gemini_daily_token_limit,
        ),
    }


def _configured_api_key(provider: LLMProviderName) -> str | None:
    settings = get_settings()
    return settings.groq_api_key if provider == LLMProviderName.GROQ else settings.gemini_api_key


async def _usage_today(session: AsyncSession, provider: LLMProviderName) -> LLMUsageLog | None:
    result = await session.execute(
        select(LLMUsageLog).where(
            LLMUsageLog.provider == provider, LLMUsageLog.date == date.today()
        )
    )
    return result.scalar_one_or_none()


async def has_headroom(session: AsyncSession, provider: LLMProviderName) -> bool:
    """False if the provider has no API key configured at all — a
    provider you haven't given a key to should never be "selected", not
    even to fail loudly on the first call."""
    if not _configured_api_key(provider):
        return False
    usage = await _usage_today(session, provider)
    if usage is None:
        return True
    limits = _provider_limits()[provider]
    return (
        usage.requests_used < limits.requests_per_day
        and usage.tokens_used < limits.tokens_per_day
    )


async def select_provider(session: AsyncSession) -> LLMProviderName | None:
    """Returns None if no provider currently has both a configured key
    and headroom left today — the caller must treat that as "queue for
    later", never as a hard failure. See extraction.py."""
    for provider in PROVIDER_ORDER:
        if await has_headroom(session, provider):
            return provider
    return None


@dataclass(frozen=True)
class ProviderUsageSummary:
    provider: LLMProviderName
    date: date
    requests_used: int
    tokens_used: int
    requests_limit: int
    tokens_limit: int
    has_headroom: bool


async def get_usage_summary(session: AsyncSession) -> list[ProviderUsageSummary]:
    """Today's usage for every provider, for the admin ops view
    (docs/CONTRACT_CLM_BUILD_PLAN.md §8's `GET /admin/llm-usage`) — includes
    providers with zero calls today so the dashboard always shows every
    configured provider, not just the ones that happened to be used."""
    limits = _provider_limits()
    summaries = []
    for provider in PROVIDER_ORDER:
        usage = await _usage_today(session, provider)
        summaries.append(
            ProviderUsageSummary(
                provider=provider,
                date=date.today(),
                requests_used=usage.requests_used if usage is not None else 0,
                tokens_used=usage.tokens_used if usage is not None else 0,
                requests_limit=limits[provider].requests_per_day,
                tokens_limit=limits[provider].tokens_per_day,
                has_headroom=await has_headroom(session, provider),
            )
        )
    return summaries


async def record_usage(session: AsyncSession, provider: LLMProviderName, *, tokens: int) -> None:
    usage = await _usage_today(session, provider)
    if usage is None:
        session.add(
            LLMUsageLog(provider=provider, date=date.today(), requests_used=1, tokens_used=tokens)
        )
    else:
        usage.requests_used += 1
        usage.tokens_used += tokens
    await session.flush()
