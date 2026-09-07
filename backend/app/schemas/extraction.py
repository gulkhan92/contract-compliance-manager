"""Pydantic schemas and prompt templates for structured LLM extraction.

See docs/CONTRACT_CLM_BUILD_PLAN.md §7.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import ContractType, ObligationCategory, RecurrenceType

EXTRACTION_SYSTEM_PROMPT = (
    "You are an expert legal contract analyst specializing in contract lifecycle and "
    "obligation management. Analyze the provided numbered candidate paragraphs from a contract "
    "and extract all obligations, renewal terms, termination notices, payment milestones, "
    "SLA commitments, and compliance requirements.\n\n"
    "CRITICAL REQUIREMENTS:\n"
    "1. Return ONLY valid JSON matching the exact schema requested.\n"
    "2. Do not hallucinate or invent obligations not explicitly supported by the text.\n"
    "3. For each obligation, you MUST cite the exact `source_paragraph_index` it came from.\n"
    "4. If a paragraph contains no obligation, omit it.\n"
    "5. Date fields must use ISO-8601 format (YYYY-MM-DD). If not stated, set null.\n"
    "6. Currency codes must be 3 uppercase letters (e.g. USD, EUR, GBP).\n"
    "7. Assign a confidence score between 0.0 and 1.0 reflecting certainty."
)



class ExtractedObligation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: ObligationCategory
    description: str = Field(description="Plain-English summary of the obligation, 1-2 sentences.")
    responsible_party: str | None = Field(
        default=None, description="'us', counterparty name, or specific role."
    )
    trigger_date: date | None = Field(
        default=None, description="Actual deadline, renewal, or payment date (YYYY-MM-DD)."
    )
    notice_period_days: int | None = Field(
        default=None, description="Notice window in days (e.g., 60 for '60 days written notice')."
    )
    monetary_amount: float | None = Field(
        default=None, description="Monetary amount if applicable."
    )
    currency: str | None = Field(
        default=None, max_length=3, description="3-letter currency code, e.g. USD."
    )
    recurrence: RecurrenceType = Field(
        default=RecurrenceType.NONE, description="Recurrence frequency."
    )
    source_paragraph_index: int = Field(
        description="Paragraph index of the candidate chunk this obligation was extracted from."
    )
    confidence: float = Field(
        default=0.85, ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0."
    )


class ContractExtractionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    contract_type_guess: ContractType = Field(
        default=ContractType.OTHER, description="Inferred contract type."
    )
    counterparty_name_guess: str | None = Field(
        default=None, description="Inferred counterparty name."
    )
    effective_date_guess: date | None = Field(
        default=None, description="Inferred effective date (YYYY-MM-DD)."
    )
    expiration_date_guess: date | None = Field(
        default=None, description="Inferred expiration/end date (YYYY-MM-DD)."
    )
    obligations: list[ExtractedObligation] = Field(
        default_factory=list, description="List of extracted structured obligations."
    )


def build_extraction_prompt(candidate_paragraphs: list[tuple[int, str | None, str]]) -> str:
    """Formats candidate chunks into a single batched prompt for the LLM."""
    lines: list[str] = [
        "Please extract all obligations from the following contract paragraphs:",
        "",
    ]
    for idx, heading, text in candidate_paragraphs:
        header = f"[Paragraph {idx}]"
        if heading:
            header += f" (Section: {heading})"
        lines.append(f"{header}\n{text.strip()}\n")
    return "\n".join(lines)
