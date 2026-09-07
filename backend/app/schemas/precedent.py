import uuid

from pydantic import BaseModel


class PrecedentSearchResult(BaseModel):
    chunk_id: uuid.UUID
    contract_id: uuid.UUID
    contract_title: str
    section_heading: str | None
    raw_text: str
    similarity: float
