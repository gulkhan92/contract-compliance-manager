"""Builds the single batched, schema-constrained extraction prompt per
contract — never one call per clause type or per paragraph, since
repeating the system prompt + document context N times is the single
biggest avoidable token cost. See docs/CONTRACT_CLM_BUILD_PLAN.md §3
step 4 and §7.
"""

import json

from app.db.models import ContractChunk
from app.schemas.extraction import ContractExtractionResult

SYSTEM_PROMPT = (
    "You are a contract analysis assistant. Given numbered candidate "
    "paragraphs from a legal contract, extract every genuine obligation, "
    "deadline, renewal window, and monetary milestone they contain. "
    "Return ONLY a single valid JSON object matching the provided JSON "
    "schema — no prose, no markdown fences. Do not invent obligations "
    "that aren't clearly supported by the text. If a paragraph contains "
    "no obligation, omit it entirely. Always cite source_paragraph_id "
    "exactly as given in the paragraph label."
)


def chunk_label(chunk: ContractChunk) -> str:
    """A short, LLM-friendly identifier the model echoes back as
    source_paragraph_id — deliberately not the chunk's real UUID, which
    an LLM cannot reliably reproduce character-for-character. Mapped back
    to the real contract_chunks.id when persisting (see extraction.py)."""
    return f"P{chunk.paragraph_index}"


def build_user_prompt(chunks: list[ContractChunk]) -> str:
    schema = json.dumps(ContractExtractionResult.model_json_schema())
    paragraphs = "\n\n".join(f"[{chunk_label(c)}] {c.raw_text}" for c in chunks)
    return (
        f"JSON schema to match:\n{schema}\n\n"
        f"Candidate paragraphs:\n{paragraphs}"
    )
