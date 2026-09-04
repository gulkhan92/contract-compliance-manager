"""Parses an uploaded contract into paragraph-level chunks, with best-effort
section-heading detection. See docs/CONTRACT_CLM_BUILD_PLAN.md §12 Phase 3.

This is intentionally a coarse, heuristic pass — not the obligation
extraction itself (that's Phase 5's LLM step). Its job is to break the
document into reviewable/embeddable units and tag each with the nearest
preceding heading, where one can be found.
"""

import io
import re
from dataclasses import dataclass

import docx
import pymupdf

from app.services.file_validation import FileKind

_MAX_HEADING_LENGTH = 100
_MAX_STORED_HEADING_LENGTH = 500  # matches contract_chunks.section_heading column

_NUMBERED_HEADING_PATTERN = re.compile(
    r"^\s*(ARTICLE|SECTION)\s+[IVXLCDM\d]+\b|^\s*\d{1,2}(\.\d{1,2})*\.?\s+[A-Z]"
)


@dataclass(frozen=True)
class ParsedParagraph:
    paragraph_index: int
    section_heading: str | None
    raw_text: str


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LENGTH:
        return False
    if _NUMBERED_HEADING_PATTERN.match(stripped):
        return True
    letters = [c for c in stripped if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def parse_pdf(data: bytes) -> list[ParsedParagraph]:
    paragraphs: list[ParsedParagraph] = []
    current_heading: str | None = None
    index = 0

    # PyMuPDF ships no type stubs; `pymupdf.open` is an alias for the
    # (untyped) Document constructor.
    with pymupdf.open(stream=data, filetype="pdf") as document:  # type: ignore[no-untyped-call]
        for page in document:
            for block in page.get_text("blocks"):
                text = block[4].replace("\xa0", " ").strip()
                if not text:
                    continue

                first_line = text.split("\n", 1)[0]
                if _looks_like_heading(first_line):
                    current_heading = first_line[:_MAX_STORED_HEADING_LENGTH]

                paragraphs.append(
                    ParsedParagraph(
                        paragraph_index=index,
                        section_heading=current_heading,
                        raw_text=text,
                    )
                )
                index += 1

    return paragraphs


def parse_docx(data: bytes) -> list[ParsedParagraph]:
    paragraphs: list[ParsedParagraph] = []
    current_heading: str | None = None
    index = 0

    document = docx.Document(io.BytesIO(data))
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        is_heading_style = para.style is not None and para.style.name.lower().startswith("heading")
        if is_heading_style or _looks_like_heading(text):
            current_heading = text[:_MAX_STORED_HEADING_LENGTH]

        paragraphs.append(
            ParsedParagraph(paragraph_index=index, section_heading=current_heading, raw_text=text)
        )
        index += 1

    return paragraphs


def parse_document(data: bytes, file_kind: FileKind) -> list[ParsedParagraph]:
    if file_kind == "pdf":
        return parse_pdf(data)
    return parse_docx(data)
