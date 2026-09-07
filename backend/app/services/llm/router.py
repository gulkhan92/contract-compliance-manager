"""Quota-aware provider selection and failover router.

Tracks daily usage in `llm_usage_log` table; selects provider with headroom;
handles 429 failover and single corrective schema retries.
See docs/CONTRACT_CLM_BUILD_PLAN.md §3 and §7.
"""

import logging
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.enums import LLMProviderName
from app.db.models import LLMUsageLog
from app.schemas.extraction import ContractExtractionResult
from app.services.llm.base import (
    BaseLLMProvider,
    ExtractionResponse,
    LLMProviderError,
    LLMRateLimitError,
    LLMSchemaValidationError,
    QuotaExhaustedError,
)
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider

logger = logging.getLogger(__name__)

# Daily free-tier limits as specified in docs/CONTRACT_CLM_BUILD_PLAN.md §3
GROQ_DAILY_REQUEST_LIMIT = 1000
GROQ_DAILY_TOKEN_LIMIT = 200_000
GEMINI_DAILY_REQUEST_LIMIT = 1500


class LLMRouter:
    def __init__(
        self,
        groq_provider: BaseLLMProvider | None = None,
        gemini_provider: BaseLLMProvider | None = None,
    ) -> None:
        settings = get_settings()
        self.groq_provider = groq_provider or GroqProvider(api_key=settings.groq_api_key)
        self.gemini_provider = gemini_provider or GeminiProvider(api_key=settings.gemini_api_key)

    async def get_or_create_usage(
        self, db: AsyncSession, provider: LLMProviderName, target_date: date
    ) -> LLMUsageLog:
        """Retrieves or initializes the usage row for a given provider and date."""
        query = select(LLMUsageLog).where(
            LLMUsageLog.provider == provider, LLMUsageLog.date == target_date
        )
        result = await db.execute(query)
        usage = result.scalar_one_or_none()
        if usage is None:
            usage = LLMUsageLog(
                provider=provider,
                date=target_date,
                requests_used=0,
                tokens_used=0,
            )
            db.add(usage)
            await db.flush()
        return usage

    async def record_usage(
        self,
        db: AsyncSession,
        provider: LLMProviderName,
        tokens_used: int,
    ) -> None:
        """Increments requests and tokens used for today."""
        today = datetime.now(UTC).date()
        usage = await self.get_or_create_usage(db, provider, today)
        usage.requests_used += 1
        usage.tokens_used += tokens_used
        usage.last_updated_at = datetime.now(UTC)
        await db.flush()

    async def has_headroom(
        self, db: AsyncSession, provider: LLMProviderName, target_date: date
    ) -> bool:
        """Checks whether the given provider has available quota for target_date."""
        usage = await self.get_or_create_usage(db, provider, target_date)
        if provider == LLMProviderName.GROQ:
            return (
                usage.requests_used < GROQ_DAILY_REQUEST_LIMIT
                and usage.tokens_used < GROQ_DAILY_TOKEN_LIMIT
            )
        if provider == LLMProviderName.GEMINI:
            return usage.requests_used < GEMINI_DAILY_REQUEST_LIMIT
        return True

    async def extract_with_failover(
        self,
        db: AsyncSession,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> ExtractionResponse:
        """Attempts extraction using Groq (if headroom available), falling back to Gemini.

        Executes one corrective schema retry per provider before falling back.
        Updates `llm_usage_log` on successful completion.

        Raises:
            QuotaExhaustedError: If all providers have exceeded quota or failed.
        """
        today = datetime.now(UTC).date()
        schema_json: dict[str, Any] = ContractExtractionResult.model_json_schema()

        providers_to_try: list[BaseLLMProvider] = []
        groq_ok = await self.has_headroom(db, LLMProviderName.GROQ, today)
        gemini_ok = await self.has_headroom(db, LLMProviderName.GEMINI, today)

        if groq_ok:
            providers_to_try.append(self.groq_provider)
        if gemini_ok:
            providers_to_try.append(self.gemini_provider)

        if not providers_to_try:
            logger.error("Both Groq and Gemini daily quotas are exhausted for %s", today)
            raise QuotaExhaustedError(
                f"All LLM provider quotas exhausted for {today}. Cannot extract obligations."
            )

        last_error: Exception | None = None

        for provider in providers_to_try:
            logger.info("Attempting extraction with provider: %s", provider.provider_name)
            try:
                # 1. First attempt with provider
                response = await self._call_with_retry(
                    provider=provider,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema_json=schema_json,
                )
                # Successful extraction: record usage in DB
                await self.record_usage(db, provider.provider_name, response.tokens_used)
                return response
            except LLMRateLimitError as exc:
                logger.warning(
                    "Provider %s hit rate limit (429): %s. Falling back.",
                    provider.provider_name,
                    exc,
                )
                last_error = exc
                continue
            except LLMProviderError as exc:
                logger.warning(
                    "Provider %s failed with error: %s. Falling back.",
                    provider.provider_name,
                    exc,
                )
                last_error = exc
                continue

        # If loop finished without returning, all tried providers failed
        raise QuotaExhaustedError(
            f"All available LLM providers failed or exhausted: {last_error}"
        ) from last_error

    async def _call_with_retry(
        self,
        *,
        provider: BaseLLMProvider,
        system_prompt: str,
        user_prompt: str,
        schema_json: dict[str, Any],
    ) -> ExtractionResponse:
        """Executes a single provider call with at most 1 corrective schema retry."""
        try:
            return await provider.extract_structured(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_json=schema_json,
            )
        except LLMSchemaValidationError as val_exc:
            logger.warning(
                "Provider %s produced invalid schema. Triggering 1 corrective retry. Error: %s",
                provider.provider_name,
                val_exc,
            )
            corrective_prompt = (
                f"{user_prompt}\n\n"
                f"[CORRECTION INSTRUCTION]: Your previous output failed schema validation with: "
                f"{val_exc}. You MUST output ONLY valid JSON matching the exact schema."
            )
            return await provider.extract_structured(
                system_prompt=system_prompt,
                user_prompt=corrective_prompt,
                schema_json=schema_json,
            )
