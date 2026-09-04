"""Upload validation: magic-byte sniffing (never trust filename/Content-Type
alone) and a hard size cap. See docs/CONTRACT_CLM_BUILD_PLAN.md §6.5.
"""

import io
import zipfile
from typing import Literal

MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024  # 20MB

FileKind = Literal["pdf", "docx"]

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK"
_DOCX_MARKER = "word/document.xml"


class UnsupportedFileTypeError(Exception):
    pass


class FileTooLargeError(Exception):
    pass


def detect_file_kind(data: bytes) -> FileKind:
    """Inspects the actual file bytes — a `.pdf` extension or a
    `Content-Type: application/pdf` header prove nothing on their own."""
    if data.startswith(_PDF_MAGIC):
        return "pdf"

    if data.startswith(_ZIP_MAGIC):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if _DOCX_MARKER in archive.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass

    raise UnsupportedFileTypeError("Only PDF and DOCX files are supported.")


def enforce_size_limit(data: bytes) -> None:
    if len(data) > MAX_UPLOAD_SIZE_BYTES:
        raise FileTooLargeError(
            f"File exceeds the {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB upload limit."
        )
