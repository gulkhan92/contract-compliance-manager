"""Enum types shared between SQLAlchemy models and the LLM extraction schema.

Each maps 1:1 to a native PostgreSQL ENUM created by the Alembic migrations.
See docs/CONTRACT_CLM_BUILD_PLAN.md §5.3 for the schema these back.
"""

from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    LEGAL_OPS = "legal_ops"
    VIEWER = "viewer"


class ContractType(StrEnum):
    NDA = "NDA"
    MSA = "MSA"
    LEASE = "Lease"
    LICENSE = "License"
    EMPLOYMENT = "Employment"
    VENDOR = "Vendor"
    OTHER = "Other"


class ContractStatus(StrEnum):
    PROCESSING = "processing"
    NEEDS_REVIEW = "needs_review"
    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    ERROR = "error"


class ObligationCategory(StrEnum):
    RENEWAL = "RENEWAL"
    TERMINATION_NOTICE = "TERMINATION_NOTICE"
    PAYMENT_MILESTONE = "PAYMENT_MILESTONE"
    SLA_COMMITMENT = "SLA_COMMITMENT"
    INDEMNIFICATION = "INDEMNIFICATION"
    CONFIDENTIALITY = "CONFIDENTIALITY"
    NON_COMPETE = "NON_COMPETE"
    LIMITATION_OF_LIABILITY = "LIMITATION_OF_LIABILITY"
    GOVERNING_LAW = "GOVERNING_LAW"
    AUDIT_RIGHTS = "AUDIT_RIGHTS"
    DATA_PROTECTION = "DATA_PROTECTION"
    OTHER_OBLIGATION = "OTHER_OBLIGATION"


class RecurrenceType(StrEnum):
    NONE = "none"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"


class ObligationStatus(StrEnum):
    UPCOMING = "upcoming"
    AT_RISK = "at_risk"
    OVERDUE = "overdue"
    RESOLVED = "resolved"
    WAIVED = "waived"


class AlertType(StrEnum):
    EMAIL = "email"
    IN_APP = "in_app"


class AlertStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExtractionJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class LLMProviderName(StrEnum):
    GROQ = "groq"
    GEMINI = "gemini"


class ChatSessionScope(StrEnum):
    ORGANIZATION = "organization"
    CONTRACT = "contract"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT_INFORMATION = "insufficient_information"


class ChatIntent(StrEnum):
    DOMAIN_QUESTION = "domain_question"
    CLAUSE_BENCHMARK = "clause_benchmark"
    CALENDAR_QUERY = "calendar_query"
    OUT_OF_SCOPE = "out_of_scope"


class ChatFeedback(StrEnum):
    NONE = "none"
    UP = "up"
    DOWN = "down"

