"""Google Gemini LLM provider implementation.

Uses Gemini's REST API with response_mime_type="application/json".
See docs/CONTRACT_CLM_BUILD_PLAN.md §3 (secondary/fallback provider).
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

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"


class GeminiProvider(BaseLLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 45.0,
    ) -> None:
        self._api_key = api_key or get_settings().gemini_api_key
        self._model = model
        self._http_client = http_client
        self._timeout = timeout

    @property
    def provider_name(self) -> LLMProviderName:
        return LLMProviderName.GEMINI

    async def extract_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_json: dict[str, Any],
    ) -> ExtractionResponse:
        if not self._api_key:
            raise LLMProviderError("GEMINI_API_KEY is not configured.")

        full_system_prompt = (
            f"{system_prompt}\n\n"
            f"You MUST output valid JSON conforming to this JSON Schema:\n"
            f"{json.dumps(schema_json, indent=2)}"
        )

        url = f"{GEMINI_BASE_URL}/{self._model}:generateContent"
        params = {"key": self._api_key}

        payload = {
            "system_instruction": {"parts": [{"text": full_system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.1,
            },
        }

        headers = {"Content-Type": "application/json"}

        try:
            if self._http_client:
                response = await self._http_client.post(
                    url, params=params, json=payload, headers=headers, timeout=self._timeout
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        url, params=params, json=payload, headers=headers, timeout=self._timeout
                    )
        except httpx.TimeoutException as exc:
            raise LLMProviderError(f"Gemini request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(f"Network error calling Gemini: {exc}") from exc

        if response.status_code == 429:
            raise LLMRateLimitError(f"Gemini rate limit exceeded (429): {response.text}")

        if response.status_code >= 400:
            raise LLMProviderError(
                f"Gemini API returned HTTP {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise LLMProviderError("Gemini returned empty candidate list.")
            raw_text = candidates[0]["content"]["parts"][0]["text"]
            tokens_used = data.get("usageMetadata", {}).get("totalTokenCount", 0)
        except (KeyError, json.JSONDecodeError, IndexError) as exc:
            raise LLMProviderError(f"Invalid response payload from Gemini: {exc}") from exc

        try:
            result = ContractExtractionResult.model_validate_json(raw_text)
        except ValidationError as exc:
            logger.warning("Gemini output failed schema validation: %s", exc)
            raise LLMSchemaValidationError(f"Schema validation failed: {exc}") from exc

        return ExtractionResponse(
            result=result,
            provider=self.provider_name,
            tokens_used=tokens_used,
            raw_response=raw_text,
        )
