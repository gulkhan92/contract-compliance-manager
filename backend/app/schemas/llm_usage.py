from datetime import date

from pydantic import BaseModel

from app.db.enums import LLMProviderName


class LLMUsageSummary(BaseModel):
    provider: LLMProviderName
    date: date
    requests_used: int
    tokens_used: int
    requests_limit: int
    tokens_limit: int
    has_headroom: bool
