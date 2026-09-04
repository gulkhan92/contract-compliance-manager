import io
import zipfile

import pytest

from app.services.file_validation import (
    MAX_UPLOAD_SIZE_BYTES,
    FileTooLargeError,
    UnsupportedFileTypeError,
    detect_file_kind,
    enforce_size_limit,
)


def test_detects_pdf_by_magic_bytes() -> None:
    assert detect_file_kind(b"%PDF-1.7\n...rest of a real pdf...") == "pdf"


def test_detects_docx_by_zip_contents() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
        archive.writestr("[Content_Types].xml", "<Types/>")
    assert detect_file_kind(buffer.getvalue()) == "docx"


def test_rejects_renamed_text_file_pretending_to_be_pdf() -> None:
    """The whole point of magic-byte sniffing: a `.pdf`-named file that is
    actually plain text must not be trusted just because of its extension —
    the caller only ever passes us raw bytes, never the filename."""
    with pytest.raises(UnsupportedFileTypeError):
        detect_file_kind(b"just a plain text file, not a real pdf")


def test_rejects_generic_zip_that_is_not_a_docx() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hello")
    with pytest.raises(UnsupportedFileTypeError):
        detect_file_kind(buffer.getvalue())


def test_enforce_size_limit_allows_boundary() -> None:
    enforce_size_limit(b"x" * MAX_UPLOAD_SIZE_BYTES)


def test_enforce_size_limit_rejects_oversized_file() -> None:
    with pytest.raises(FileTooLargeError):
        enforce_size_limit(b"x" * (MAX_UPLOAD_SIZE_BYTES + 1))
