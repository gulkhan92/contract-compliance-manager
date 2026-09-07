"""Generic schema-constrained-call orchestration: one provider call, one
corrective retry on schema validation failure, then fallback to the next
provider in priority order — the exact pattern extraction.py established
(docs/CONTRACT_CLM_BUILD_PLAN.md §7) and the chatbot's generation step
(docs/CHATBOT_INTEGRATION_PLAN.md §6.2) reuses verbatim rather than
reimplementing. Generic over the response Pydantic model so both callers
share one implementation instead of two copies of the same retry/fallback
logic drifting apart over time.
"""

import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.enums import LLMProviderName
from app.services.llm import quota
from app.services.llm.base import LLMProvider, LLMProviderError
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.groq_provider import GroqProvider

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)


def build_provider(name: LLMProviderName) -> LLMProvider:
    settings = get_settings()
    if name == LLMProviderName.GROQ:
        assert settings.groq_api_key is not None, "select_provider already checked this"
        return GroqProvider(api_key=settings.groq_api_key)
    assert settings.gemini_api_key is not None, "select_provider already checked this"
    return GeminiProvider(api_key=settings.gemini_api_key)


def build_corrective_prompt(*, previous_response: str, validation_error: str) -> str:
    return (
        "Your last response failed schema validation with this error:\n"
        f"{validation_error}\n\n"
        "Your last response was:\n"
        f"{previous_response}\n\n"
        "Return corrected JSON that matches the schema exactly. Only output "
        "the corrected JSON object — no prose, no markdown fences."
    )


async def call_with_validation_retry(
    provider: LLMProvider, *, system_prompt: str, user_prompt: str, response_model: type[_T]
) -> tuple[_T, int]:
    """One provider call, with a single corrective retry on schema
    validation failure. Returns (parsed_result, total_tokens_used). A
    second validation failure propagates to the caller, which falls back
    to the other provider rather than retrying indefinitely."""
    completion = await provider.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
    tokens_used = completion.tokens_used

    try:
        return response_model.model_validate_json(completion.text), tokens_used
    except ValidationError as exc:
        logger.info("%s returned invalid JSON, retrying once with a correction.", provider.name)
        corrective_prompt = build_corrective_prompt(
            previous_response=completion.text, validation_error=str(exc)
        )
        retry_completion = await provider.complete_json(
            system_prompt=system_prompt, user_prompt=corrective_prompt
        )
        tokens_used += retry_completion.tokens_used
        return response_model.model_validate_json(retry_completion.text), tokens_used


async def call_llm_with_fallback(
    session: AsyncSession, *, system_prompt: str, user_prompt: str, response_model: type[_T]
) -> tuple[LLMProviderName, _T, int] | None:
    """Tries providers in priority order, skipping any with no headroom,
    falling back to the next on any failure. Returns None if no provider
    currently has both a configured key and headroom — never raises."""
    for provider_name in quota.PROVIDER_ORDER:
        if not await quota.has_headroom(session, provider_name):
            continue
        provider = build_provider(provider_name)
        try:
            result, tokens = await call_with_validation_retry(
                provider,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=response_model,
            )
        except (LLMProviderError, ValidationError) as exc:
            logger.warning("%s call failed, trying next provider: %s", provider_name, exc)
            continue
        await quota.record_usage(session, provider_name, tokens=tokens)
        return provider_name, result, tokens
    return None
