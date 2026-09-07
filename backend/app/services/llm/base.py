"""Base interfaces and exceptions for LLM providers.

See docs/CONTRACT_CLM_BUILD_PLAN.md §3 and §7.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.db.enums import LLMProviderName
from app.schemas.extraction import ContractExtractionResult


class LLMProviderError(Exception):
    """Base exception for LLM provider failures."""


class LLMRateLimitError(LLMProviderError):
    """Raised when an LLM provider returns a 429 Too Many Requests / Rate Limit error."""


class LLMSchemaValidationError(LLMProviderError):
    """Raised when LLM output cannot be parsed or validated against the target schema."""


class QuotaExhaustedError(LLMProviderError):
    """Raised when all configured LLM providers have exhausted their quota."""


@dataclass
class ExtractionResponse:
    result: ContractExtractionResult
    provider: LLMProviderName
    tokens_used: int
    raw_response: str


class BaseLLMProvider(ABC):
    """Abstract interface for LLM extraction providers."""

    @property
    @abstractmethod
    def provider_name(self) -> LLMProviderName:
        """Provider identifier."""

    @abstractmethod
    async def extract_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_json: dict[str, Any],
    ) -> ExtractionResponse:
        """Executes a structured extraction call conforming to schema_json.

        Raises:
            LLMRateLimitError: If provider returns 429 rate limit.
            LLMSchemaValidationError: If output is malformed / invalid schema.
            LLMProviderError: On any other provider/network error.
        """
