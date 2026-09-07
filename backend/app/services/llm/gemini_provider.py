from google import genai
from google.genai import types
from google.genai.errors import APIError as GeminiAPIError

from app.db.enums import LLMProviderName
from app.services.llm.base import (
    LLMCompletionResult,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
)

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"


class GeminiProvider(LLMProvider):
    name = LLMProviderName.GEMINI

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMCompletionResult:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    temperature=0,
                ),
            )
        except GeminiAPIError as exc:
            if exc.code == 429:
                raise LLMRateLimitError(f"Gemini rate limit: {exc}") from exc
            raise LLMProviderError(f"Gemini API error: {exc}") from exc

        text = response.text
        if text is None:
            raise LLMProviderError("Gemini returned an empty completion.")
        tokens_used = (
            response.usage_metadata.total_token_count
            if response.usage_metadata is not None and response.usage_metadata.total_token_count
            else 0
        )
        return LLMCompletionResult(text=text, tokens_used=tokens_used)
