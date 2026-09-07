"""Unit tests for quota tracking and LLMRouter failover.

Tests provider headroom calculation, usage logging in `llm_usage_log`,
automatic fallback from Groq to Gemini on 429, and quota exhaustion.
See docs/CONTRACT_CLM_BUILD_PLAN.md §3, §7.
"""

from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ContractType, LLMProviderName
from app.schemas.extraction import ContractExtractionResult
from app.services.llm.base import (
    BaseLLMProvider,
    ExtractionResponse,
    LLMProviderError,
    LLMRateLimitError,
    LLMSchemaValidationError,
    QuotaExhaustedError,
)
from app.services.llm.router import (
    GROQ_DAILY_REQUEST_LIMIT,
    LLMRouter,
)


class DummyProvider(BaseLLMProvider):
    def __init__(
        self,
        name: LLMProviderName,
        result: ContractExtractionResult | None = None,
        exception: Exception | None = None,
    ) -> None:
        self._name = name
        self.result = result or ContractExtractionResult(contract_type_guess=ContractType.NDA)
        self.exception = exception
        self.call_count = 0
        self.prompts_received: list[str] = []

    @property
    def provider_name(self) -> LLMProviderName:
        return self._name

    async def extract_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_json: dict[str, Any],
    ) -> ExtractionResponse:
        self.call_count += 1
        self.prompts_received.append(user_prompt)
        if self.exception:
            raise self.exception
        return ExtractionResponse(
            result=self.result,
            provider=self.provider_name,
            tokens_used=150,
            raw_response="{}",
        )


@pytest.mark.asyncio
async def test_get_or_create_usage(db_session: AsyncSession) -> None:
    router = LLMRouter()
    target_date = date(2099, 1, 1)

    usage1 = await router.get_or_create_usage(db_session, LLMProviderName.GROQ, target_date)
    assert usage1.provider == LLMProviderName.GROQ
    assert usage1.requests_used == 0
    assert usage1.tokens_used == 0

    usage2 = await router.get_or_create_usage(db_session, LLMProviderName.GROQ, target_date)
    assert usage1.id == usage2.id


@pytest.mark.asyncio
async def test_record_usage_increments_metrics(db_session: AsyncSession) -> None:
    router = LLMRouter()
    today = datetime.now(UTC).date()
    initial_usage = await router.get_or_create_usage(db_session, LLMProviderName.GROQ, today)
    init_req = initial_usage.requests_used
    init_tokens = initial_usage.tokens_used

    await router.record_usage(db_session, LLMProviderName.GROQ, tokens_used=250)
    usage = await router.get_or_create_usage(db_session, LLMProviderName.GROQ, today)
    assert usage.requests_used == init_req + 1
    assert usage.tokens_used == init_tokens + 250

    await router.record_usage(db_session, LLMProviderName.GROQ, tokens_used=100)
    assert usage.requests_used == init_req + 2
    assert usage.tokens_used == init_tokens + 350



@pytest.mark.asyncio
async def test_router_selects_groq_when_headroom_available(db_session: AsyncSession) -> None:
    groq = DummyProvider(LLMProviderName.GROQ)
    gemini = DummyProvider(LLMProviderName.GEMINI)
    router = LLMRouter(groq_provider=groq, gemini_provider=gemini)

    resp = await router.extract_with_failover(
        db_session, system_prompt="sys", user_prompt="prompt"
    )

    assert resp.provider == LLMProviderName.GROQ
    assert groq.call_count == 1
    assert gemini.call_count == 0


@pytest.mark.asyncio
async def test_router_falls_back_to_gemini_on_groq_429(db_session: AsyncSession) -> None:
    groq = DummyProvider(LLMProviderName.GROQ, exception=LLMRateLimitError("429"))
    gemini = DummyProvider(LLMProviderName.GEMINI)
    router = LLMRouter(groq_provider=groq, gemini_provider=gemini)

    resp = await router.extract_with_failover(
        db_session, system_prompt="sys", user_prompt="prompt"
    )

    assert resp.provider == LLMProviderName.GEMINI
    assert groq.call_count == 1
    assert gemini.call_count == 1


@pytest.mark.asyncio
async def test_router_routes_directly_to_gemini_when_groq_quota_exhausted(
    db_session: AsyncSession,
) -> None:
    today = datetime.now(UTC).date()
    router = LLMRouter()
    # Artificially exhaust Groq usage
    usage = await router.get_or_create_usage(db_session, LLMProviderName.GROQ, today)
    usage.requests_used = GROQ_DAILY_REQUEST_LIMIT
    await db_session.flush()

    groq = DummyProvider(LLMProviderName.GROQ)
    gemini = DummyProvider(LLMProviderName.GEMINI)
    router_with_mocks = LLMRouter(groq_provider=groq, gemini_provider=gemini)

    resp = await router_with_mocks.extract_with_failover(
        db_session, system_prompt="sys", user_prompt="prompt"
    )

    assert resp.provider == LLMProviderName.GEMINI
    assert groq.call_count == 0
    assert gemini.call_count == 1


@pytest.mark.asyncio
async def test_router_raises_quota_exhausted_when_all_fail(db_session: AsyncSession) -> None:
    groq = DummyProvider(LLMProviderName.GROQ, exception=LLMProviderError("Groq down"))
    gemini = DummyProvider(LLMProviderName.GEMINI, exception=LLMProviderError("Gemini down"))
    router = LLMRouter(groq_provider=groq, gemini_provider=gemini)

    with pytest.raises(QuotaExhaustedError):
        await router.extract_with_failover(
            db_session, system_prompt="sys", user_prompt="prompt"
        )


@pytest.mark.asyncio
async def test_router_executes_corrective_schema_retry(db_session: AsyncSession) -> None:
    # First call raises schema validation error; second call succeeds
    groq = DummyProvider(LLMProviderName.GROQ)
    success_resp = ExtractionResponse(
        result=ContractExtractionResult(contract_type_guess=ContractType.MSA),
        provider=LLMProviderName.GROQ,
        tokens_used=120,
        raw_response="{}",
    )
    groq.extract_structured = AsyncMock(  # type: ignore[method-assign]
        side_effect=[LLMSchemaValidationError("Missing fields"), success_resp]
    )

    gemini = DummyProvider(LLMProviderName.GEMINI)
    router = LLMRouter(groq_provider=groq, gemini_provider=gemini)

    resp = await router.extract_with_failover(
        db_session, system_prompt="sys", user_prompt="original prompt"
    )

    assert resp.provider == LLMProviderName.GROQ
    assert groq.extract_structured.call_count == 2
    # Verify corrective prompt was sent
    second_call_kwargs = groq.extract_structured.call_args_list[1].kwargs
    assert "[CORRECTION INSTRUCTION]" in second_call_kwargs["user_prompt"]
