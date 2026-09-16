"""Import every model here so `Base.metadata` is fully populated for Alembic
autogenerate and `Base.metadata.create_all` (tests)."""

from app.db.models.alert import Alert
from app.db.models.audit_log import AuditLog
from app.db.models.chat_message import ChatMessage
from app.db.models.chat_session import ChatSession
from app.db.models.clause_precedent_cache import ClausePrecedentCache
from app.db.models.contract import Contract
from app.db.models.contract_chunk import ContractChunk
from app.db.models.cuad_reference_clause import CuadReferenceClause
from app.db.models.extraction_job import ExtractionJob
from app.db.models.llm_usage_log import LLMUsageLog
from app.db.models.obligation import Obligation
from app.db.models.organization import Organization
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User

__all__ = [
    "Alert",
    "AuditLog",
    "ChatMessage",
    "ChatSession",
    "ClausePrecedentCache",
    "Contract",
    "ContractChunk",
    "CuadReferenceClause",
    "ExtractionJob",
    "LLMUsageLog",
    "Obligation",
    "Organization",
    "RefreshToken",
    "User",
]

