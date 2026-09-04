"""Single shared instance of each native-PostgreSQL-ENUM column type.

Instantiate once per name here and import from this module in every model
that needs it — an enum reused across tables (e.g. `llm_provider_name` in
both `extraction_jobs` and `llm_usage_log`) must resolve to the exact same
SQLAlchemy `Enum` object, not two separately-constructed ones with a
matching `name=`, so Alembic autogenerate and `Base.metadata.create_all`
only ever see one `CREATE TYPE`.
"""

from app.db.base import pg_enum
from app.db.enums import (
    AlertStatus,
    AlertType,
    ContractStatus,
    ContractType,
    ExtractionJobStatus,
    LLMProviderName,
    ObligationCategory,
    ObligationStatus,
    RecurrenceType,
    UserRole,
)

user_role_enum = pg_enum(UserRole, name="user_role")
contract_type_enum = pg_enum(ContractType, name="contract_type")
contract_status_enum = pg_enum(ContractStatus, name="contract_status")
obligation_category_enum = pg_enum(ObligationCategory, name="obligation_category")
recurrence_type_enum = pg_enum(RecurrenceType, name="recurrence_type")
obligation_status_enum = pg_enum(ObligationStatus, name="obligation_status")
alert_type_enum = pg_enum(AlertType, name="alert_type")
alert_status_enum = pg_enum(AlertStatus, name="alert_status")
extraction_job_status_enum = pg_enum(ExtractionJobStatus, name="extraction_job_status")
llm_provider_name_enum = pg_enum(LLMProviderName, name="llm_provider_name")
