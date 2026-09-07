from groq import AsyncGroq, RateLimitError
from groq import GroqError as GroqSDKError

from app.db.enums import LLMProviderName
from app.services.llm.base import (
    LLMCompletionResult,
    LLMProvider,
    LLMProviderError,
    LLMRateLimitError,
)

DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"


class GroqProvider(LLMProvider):
    name = LLMProviderName.GROQ

    def __init__(self, api_key: str, model: str = DEFAULT_GROQ_MODEL) -> None:
        self._client = AsyncGroq(api_key=api_key)
        self._model = model

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMCompletionResult:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
        except RateLimitError as exc:
            raise LLMRateLimitError(f"Groq rate limit: {exc}") from exc
        except GroqSDKError as exc:
            raise LLMProviderError(f"Groq API error: {exc}") from exc

        content = response.choices[0].message.content
        if content is None:
            raise LLMProviderError("Groq returned an empty completion.")
        tokens_used = response.usage.total_tokens if response.usage is not None else 0
        return LLMCompletionResult(text=content, tokens_used=tokens_used)
