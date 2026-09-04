"""Deterministic, zero-LLM-cost pre-filter — the first stage of the
token-minimization funnel in docs/CONTRACT_CLM_BUILD_PLAN.md §3. Flags
candidate paragraphs (dates, durations, currency amounts, or
obligation-relevant keywords) and discards obvious boilerplate before
anything reaches an embedding model or the LLM.
"""

import re

_DATE_PATTERN = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    r"|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?"
    r"|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+\d{1,2},?\s+\d{4}\b",
    re.IGNORECASE,
)
_DURATION_PATTERN = re.compile(r"\b\d+\s*(?:day|days|month|months|year|years)\b", re.IGNORECASE)
_CURRENCY_PATTERN = re.compile(r"\$\s?[\d,]+(?:\.\d{2})?|\bUSD\b|\bEUR\b|\bGBP\b")

_OBLIGATION_KEYWORDS = (
    "renew",
    "terminat",
    "indemnif",
    "confidential",
    "non-compete",
    "noncompete",
    "audit",
    "liability",
    "governing law",
    "notice",
    "warrant",
    "insurance",
    "payment",
    "invoice",
    "milestone",
    "service level",
    " sla ",
    "data protection",
    "gdpr",
    "assign",
)

_BOILERPLATE_HEADING_KEYWORDS = (
    "DEFINITION",
    "RECITAL",
    "WITNESS WHEREOF",
    "NOTARIZATION",
    "NOTARY",
    "SIGNATURE",
    "EXHIBIT",
    "SCHEDULE",
)
_BOILERPLATE_TEXT_PATTERNS = (
    re.compile(r"in witness whereof", re.IGNORECASE),
    re.compile(r"notary public", re.IGNORECASE),
    re.compile(r"^\s*by:\s*_+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*/s/", re.MULTILINE),
)


def is_boilerplate(*, section_heading: str | None, raw_text: str) -> bool:
    if section_heading and any(
        keyword in section_heading.upper() for keyword in _BOILERPLATE_HEADING_KEYWORDS
    ):
        return True
    return any(pattern.search(raw_text) for pattern in _BOILERPLATE_TEXT_PATTERNS)


def has_obligation_signal(raw_text: str) -> bool:
    if (
        _DATE_PATTERN.search(raw_text)
        or _DURATION_PATTERN.search(raw_text)
        or _CURRENCY_PATTERN.search(raw_text)
    ):
        return True
    lowered = f" {raw_text.lower()} "
    return any(keyword in lowered for keyword in _OBLIGATION_KEYWORDS)


def classify_chunk(*, section_heading: str | None, raw_text: str) -> tuple[bool, bool]:
    """Returns (is_boilerplate, passed_prefilter)."""
    boilerplate = is_boilerplate(section_heading=section_heading, raw_text=raw_text)
    passed = (not boilerplate) and has_obligation_signal(raw_text)
    return boilerplate, passed
