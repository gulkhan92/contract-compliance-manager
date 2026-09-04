import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.db.enums import ContractStatus, ContractType, ExtractionJobStatus, LLMProviderName


class ContractSummary(BaseModel):
    id: uuid.UUID
    title: str
    counterparty_name: str | None
    contract_type: ContractType
    status: ContractStatus
    effective_date: date | None
    original_expiration_date: date | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractDetail(ContractSummary):
    original_filename: str
    governing_law: str | None
    contract_value: float | None
    currency: str | None
    extraction_confidence: float | None
    updated_at: datetime


class ExtractionJobSummary(BaseModel):
    id: uuid.UUID
    status: ExtractionJobStatus
    llm_provider_used: LLMProviderName | None
    tokens_used_estimate: int | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None

    model_config = {"from_attributes": True}


class ContractStatusResponse(BaseModel):
    contract_id: uuid.UUID
    contract_status: ContractStatus
    latest_extraction_job: ExtractionJobSummary | None


class ContractUploadResponse(BaseModel):
    contract: ContractDetail
    extraction_job_id: uuid.UUID
