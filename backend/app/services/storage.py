"""Local filesystem storage for uploaded contract files.

Stored outside any web-served root, under a server-generated
`{org_id}/{contract_id}.{ext}` path — never derived from the user-supplied
filename — so a malicious filename can't path-traverse or overwrite another
org's file. See docs/CONTRACT_CLM_BUILD_PLAN.md §6.6.
"""

import uuid
from pathlib import Path

from app.core.config import get_settings
from app.services.file_validation import FileKind


def _storage_root() -> Path:
    return Path(get_settings().storage_root)


def save_contract_file(
    *, org_id: uuid.UUID, contract_id: uuid.UUID, file_kind: FileKind, data: bytes
) -> str:
    """Writes the file and returns its path relative to the storage root
    (what gets persisted in `contracts.storage_path`)."""
    relative_path = Path(str(org_id)) / f"{contract_id}.{file_kind}"
    absolute_path = _storage_root() / relative_path
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    absolute_path.write_bytes(data)
    return str(relative_path)


def read_contract_file(storage_path: str) -> bytes:
    return (_storage_root() / storage_path).read_bytes()
