"""Tests for retry_queued_extractions — the sweep that picks back up
extraction_jobs left QUEUED because no LLM provider had quota headroom at
upload time. Found via live-testing the running app: a contract uploaded
with no API keys configured stayed "processing" forever, with nothing in
the codebase that ever retried it. See app/services/ingestion.py.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.enums import (
    ContractStatus,
    ExtractionJobStatus,
    LLMProviderName,
    ObligationCategory,
    UserRole,
)
from app.db.models import Contract, ContractChunk, ExtractionJob, Obligation, Organization, User
from app.services.ingestion import retry_queued_extractions
from app.services.llm import orchestration as orchestration_module
from app.services.llm.base import LLMCompletionResult, LLMProvider

EMBEDDING_DIM = 768
_UNIT_X = [1.0] + [0.0] * (EMBEDDING_DIM - 1)

_VALID_RESPONSE = """
{
  "contract_type_guess": "NDA",
  "counterparty_name_guess": "Acme Corp",
  "effective_date_guess": "2026-01-01",
  "expiration_date_guess": "2027-01-01",
  "obligations": [
    {
      "category": "CONFIDENTIALITY",
      "description": "Both parties keep terms confidential.",
      "responsible_party": "Both parties",
      "trigger_date": null,
      "notice_period_days": null,
      "monetary_amount": null,
      "currency": null,
      "recurrence": "none",
      "source_paragraph_id": "P0",
      "confidence": 0.9
    }
  ]
}
"""


class _StubProvider(LLMProvider):
    def __init__(self, name: LLMProviderName, responses: list[object]) -> None:
        self.name = name
        self._responses = list(responses)
        self.calls = 0

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMCompletionResult:
        self.calls += 1
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return LLMCompletionResult(text=str(outcome), tokens_used=80)


async def _setup(db_session: AsyncSession) -> tuple[Contract, ExtractionJob]:
    org = Organization(name="Retry Sweep Test Org")
    db_session.add(org)
    await db_session.flush()
    user = User(
        org_id=org.id,
        email=f"{uuid.uuid4()}@example.com",
        hashed_password="not-a-real-hash",
        role=UserRole.LEGAL_OPS,
        full_name="Test User",
    )
    db_session.add(user)
    await db_session.flush()
    contract = Contract(
        org_id=org.id,
        uploaded_by=user.id,
        title="Retry Test Contract",
        original_filename="test.pdf",
        storage_path="storage/test.pdf",
        file_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        status=ContractStatus.PROCESSING,
    )
    db_session.add(contract)
    await db_session.flush()
    db_session.add(
        ContractChunk(
            contract_id=contract.id,
            paragraph_index=0,
            raw_text="Each party shall keep the other's information confidential.",
            embedding=_UNIT_X,
            passed_prefilter=True,
        )
    )
    job = ExtractionJob(contract_id=contract.id, status=ExtractionJobStatus.QUEUED)
    db_session.add(job)
    await db_session.flush()
    return contract, job


@pytest.mark.asyncio
async def test_retry_picks_up_queued_job_once_a_provider_has_headroom(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract, job = await _setup(db_session)
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    monkeypatch.setattr(
        orchestration_module,
        "build_provider",
        lambda name: _StubProvider(name, [_VALID_RESPONSE]),
    )

    result = await retry_queued_extractions(db_session)

    assert result.jobs_retried == 1
    assert result.jobs_succeeded == 1
    assert result.jobs_still_queued == 0
    assert job.status == ExtractionJobStatus.SUCCEEDED

    obligations = (
        await db_session.execute(
            Obligation.__table__.select().where(Obligation.contract_id == contract.id)
        )
    ).fetchall()
    assert len(obligations) == 1
    assert obligations[0].category == ObligationCategory.CONFIDENTIALITY


@pytest.mark.asyncio
async def test_retry_leaves_job_queued_if_still_no_provider_headroom(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _contract, job = await _setup(db_session)
    monkeypatch.setattr(get_settings(), "groq_api_key", None)
    monkeypatch.setattr(get_settings(), "gemini_api_key", None)

    result = await retry_queued_extractions(db_session)

    assert result.jobs_retried == 1
    assert result.jobs_succeeded == 0
    assert result.jobs_still_queued == 1
    assert job.status == ExtractionJobStatus.QUEUED


@pytest.mark.asyncio
async def test_retry_discards_partial_obligations_before_reprocessing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prior attempt can have already persisted cache-hit obligations for
    some chunks before hitting one with no provider headroom and going back
    to QUEUED. Retrying must not pile a second copy of those on top."""
    contract, job = await _setup(db_session)
    db_session.add(
        Obligation(
            contract_id=contract.id,
            category=ObligationCategory.CONFIDENTIALITY,
            description="Stale obligation from an interrupted first attempt.",
            responsible_party="Both parties",
        )
    )
    await db_session.flush()

    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    monkeypatch.setattr(
        orchestration_module,
        "build_provider",
        lambda name: _StubProvider(name, [_VALID_RESPONSE]),
    )

    await retry_queued_extractions(db_session)

    obligations = (
        await db_session.execute(
            Obligation.__table__.select().where(Obligation.contract_id == contract.id)
        )
    ).fetchall()
    assert len(obligations) == 1
    assert obligations[0].description == "Both parties keep terms confidential."
