"""Groq LLM provider implementation.

Uses Groq's OpenAI-compatible completions endpoint with JSON mode.
See docs/CONTRACT_CLM_BUILD_PLAN.md §3 (primary provider).
"""

import json
import logging
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import get_settings
from app.db.enums import LLMProviderName
from app.schemas.extraction import ContractExtractionResult
from app.services.llm.base import (
    BaseLLMProvider,
    ExtractionResponse,
    LLMProviderError,
    LLMRateLimitError,
    LLMSchemaValidationError,
)

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"


class GroqProvider(BaseLLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_GROQ_MODEL,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 45.0,
    ) -> None:
        self._api_key = api_key or get_settings().groq_api_key
        self._model = model
        self._http_client = http_client
        self._timeout = timeout

    @property
    def provider_name(self) -> LLMProviderName:
        return LLMProviderName.GROQ

    async def extract_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_json: dict[str, Any],
    ) -> ExtractionResponse:
        if not self._api_key:
            raise LLMProviderError("GROQ_API_KEY is not configured.")

        # Augment system prompt with JSON schema definition to guide JSON mode
        full_system_prompt = (
            f"{system_prompt}\n\n"
            f"You MUST output valid JSON conforming to this JSON Schema:\n"
            f"{json.dumps(schema_json, indent=2)}"
        )

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": full_system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            if self._http_client:
                response = await self._http_client.post(
                    GROQ_API_URL, json=payload, headers=headers, timeout=self._timeout
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        GROQ_API_URL, json=payload, headers=headers, timeout=self._timeout
                    )
        except httpx.TimeoutException as exc:
            raise LLMProviderError(f"Groq request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(f"Network error calling Groq: {exc}") from exc

        if response.status_code == 429:
            raise LLMRateLimitError(f"Groq rate limit exceeded (429): {response.text}")

        if response.status_code >= 400:
            raise LLMProviderError(
                f"Groq API returned HTTP {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
            raw_text = data["choices"][0]["message"]["content"]
            tokens_used = data.get("usage", {}).get("total_tokens", 0)
        except (KeyError, json.JSONDecodeError, IndexError) as exc:
            raise LLMProviderError(f"Invalid API response format from Groq: {exc}") from exc

        try:
            result = ContractExtractionResult.model_validate_json(raw_text)
        except ValidationError as exc:
            logger.warning("Groq output failed schema validation: %s", exc)
            raise LLMSchemaValidationError(
                f"Schema validation failed: {exc}",
            ) from exc

        return ExtractionResponse(
            result=result,
            provider=self.provider_name,
            tokens_used=tokens_used,
            raw_response=raw_text,
        )
