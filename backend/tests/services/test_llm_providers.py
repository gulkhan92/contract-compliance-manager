"""Unit tests for Groq and Gemini LLM providers using MockTransport.

Ensures zero paid API tokens or live network calls are made during CI.
See docs/CONTRACT_CLM_BUILD_PLAN.md §3, §7.
"""

import json
from typing import Any

import httpx
import pytest

from app.db.enums import ContractType, LLMProviderName, ObligationCategory, RecurrenceType
from app.schemas.extraction import ContractExtractionResult
from app.services.llm.base import (
    LLMProviderError,
    LLMRateLimitError,
    LLMSchemaValidationError,
)
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider

_SAMPLE_EXTRACTION_DICT: dict[str, Any] = {
    "contract_type_guess": "Vendor",
    "counterparty_name_guess": "Acme Cloud Corp",
    "effective_date_guess": "2026-01-01",
    "expiration_date_guess": "2027-01-01",
    "obligations": [
        {
            "category": "RENEWAL",
            "description": "Auto-renews for 1 year unless 60 days written notice provided.",
            "responsible_party": "us",
            "trigger_date": "2027-01-01",
            "notice_period_days": 60,
            "monetary_amount": None,
            "currency": None,
            "recurrence": "annually",
            "source_paragraph_index": 2,
            "confidence": 0.95,
        }
    ],
}


@pytest.mark.asyncio
async def test_groq_provider_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_SAMPLE_EXTRACTION_DICT),
                    }
                }
            ],
            "usage": {"total_tokens": 342},
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GroqProvider(api_key="mock-groq-key", http_client=client)
        resp = await provider.extract_structured(
            system_prompt="system",
            user_prompt="contract text",
            schema_json=ContractExtractionResult.model_json_schema(),
        )

    assert resp.provider == LLMProviderName.GROQ
    assert resp.tokens_used == 342
    assert resp.result.contract_type_guess == ContractType.VENDOR
    assert len(resp.result.obligations) == 1
    assert resp.result.obligations[0].category == ObligationCategory.RENEWAL
    assert resp.result.obligations[0].notice_period_days == 60


@pytest.mark.asyncio
async def test_groq_provider_rate_limit_429() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Rate limit exceeded")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GroqProvider(api_key="mock-groq-key", http_client=client)
        with pytest.raises(LLMRateLimitError) as exc_info:
            await provider.extract_structured(
                system_prompt="sys",
                user_prompt="text",
                schema_json={},
            )
    assert "429" in str(exc_info.value)


@pytest.mark.asyncio
async def test_groq_provider_schema_validation_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "choices": [{"message": {"content": "not valid json!"}}],
            "usage": {"total_tokens": 10},
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GroqProvider(api_key="mock-groq-key", http_client=client)
        with pytest.raises(LLMSchemaValidationError):
            await provider.extract_structured(
                system_prompt="sys",
                user_prompt="text",
                schema_json={},
            )


@pytest.mark.asyncio
async def test_groq_provider_requires_api_key() -> None:
    provider = GroqProvider(api_key=None)
    with pytest.raises(LLMProviderError, match="GROQ_API_KEY is not configured"):
        await provider.extract_structured(
            system_prompt="sys",
            user_prompt="text",
            schema_json={},
        )


@pytest.mark.asyncio
async def test_gemini_provider_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": json.dumps(_SAMPLE_EXTRACTION_DICT)}]
                    }
                }
            ],
            "usageMetadata": {"totalTokenCount": 412},
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="mock-gemini-key", http_client=client)
        resp = await provider.extract_structured(
            system_prompt="system",
            user_prompt="contract text",
            schema_json=ContractExtractionResult.model_json_schema(),
        )

    assert resp.provider == LLMProviderName.GEMINI
    assert resp.tokens_used == 412
    assert resp.result.counterparty_name_guess == "Acme Cloud Corp"
    assert resp.result.obligations[0].recurrence == RecurrenceType.ANNUALLY


@pytest.mark.asyncio
async def test_gemini_provider_rate_limit_429() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Resource exhausted")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="mock-gemini-key", http_client=client)
        with pytest.raises(LLMRateLimitError):
            await provider.extract_structured(
                system_prompt="sys",
                user_prompt="text",
                schema_json={},
            )


@pytest.mark.asyncio
async def test_gemini_provider_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "candidates": [{"content": {"parts": [{"text": "{malformed JSON"}]}}],
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        provider = GeminiProvider(api_key="mock-gemini-key", http_client=client)
        with pytest.raises(LLMSchemaValidationError):
            await provider.extract_structured(
                system_prompt="sys",
                user_prompt="text",
                schema_json={},
            )
