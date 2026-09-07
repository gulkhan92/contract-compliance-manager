"""Integration tests for contract obligation extraction service.

Tests full extraction pipeline:
- Structured obligation extraction and persistence
- Deterministic computed_alert_date math
- Human-in-the-loop review gating (RENEWAL, low confidence)
- Precedent cache deduplication reuse (zero LLM call for cached clauses)
- Provider failure handling and error state persistence
See docs/CONTRACT_CLM_BUILD_PLAN.md §3, §5, §7.
"""

import uuid
from datetime import date
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import (
    ContractStatus,
    ContractType,
    ExtractionJobStatus,
    LLMProviderName,
    ObligationCategory,
    RecurrenceType,
    UserRole,
)
from app.db.models import (
    ClausePrecedentCache,
    Contract,
    ContractChunk,
    ExtractionJob,
    Obligation,
    Organization,
    User,
)
from app.schemas.extraction import ContractExtractionResult, ExtractedObligation
from app.services.embeddings import EMBEDDING_DIM
from app.services.extraction import compute_alert_date, extract_contract_obligations
from app.services.llm.base import (
    BaseLLMProvider,
    ExtractionResponse,
    QuotaExhaustedError,
)
from app.services.llm.router import LLMRouter

_UNIT_VEC = [1.0] + [0.0] * (EMBEDDING_DIM - 1)
_NEAR_VEC = [0.9995] + [0.002] * (EMBEDDING_DIM - 1)


class MockLLMProvider(BaseLLMProvider):
    def __init__(
        self,
        name: LLMProviderName = LLMProviderName.GROQ,
        result: ContractExtractionResult | None = None,
        exception: Exception | None = None,
    ) -> None:
        self._name = name
        self.result = result or ContractExtractionResult(
            contract_type_guess=ContractType.VENDOR,
            counterparty_name_guess="Vendor Corp",
            effective_date_guess=date(2026, 1, 1),
            expiration_date_guess=date(2027, 1, 1),
            obligations=[],
        )
        self.exception = exception
        self.call_count = 0
        self.last_user_prompt: str | None = None

    @property
    def provider_name(self) -> LLMProviderName:
        return self._name

    async def extract_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        schema_json: dict[str, Any],
    ) -> ExtractionResponse:
        self.call_count += 1
        self.last_user_prompt = user_prompt
        if self.exception:
            raise self.exception
        return ExtractionResponse(
            result=self.result,
            provider=self.provider_name,
            tokens_used=280,
            raw_response="{}",
        )


async def _create_test_contract(
    db: AsyncSession, *, org_id: uuid.UUID
) -> tuple[Contract, ExtractionJob]:
    user = User(
        org_id=org_id,
        email=f"uploader_{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="mock",
        role=UserRole.ADMIN,
        full_name="Uploader",
    )
    db.add(user)
    await db.flush()

    contract = Contract(
        org_id=org_id,
        uploaded_by=user.id,
        title="Test Vendor Agreement",
        contract_type=ContractType.OTHER,
        original_filename="test.pdf",
        storage_path="storage/test.pdf",
        file_hash="mock_hash_" + uuid.uuid4().hex,
        status=ContractStatus.PROCESSING,
    )
    db.add(contract)
    await db.flush()

    job = ExtractionJob(
        contract_id=contract.id,
        status=ExtractionJobStatus.QUEUED,
    )
    db.add(job)
    await db.flush()
    return contract, job



def test_compute_alert_date_logic() -> None:
    # 60 days before 2027-03-01 is 2026-12-31 (or Jan 2027 depending on month math)
    target = date(2027, 6, 1)
    # 60 days before June 1 is April 2
    assert compute_alert_date(target, 60) == date(2027, 4, 2)
    # Notice period None defaults to trigger date
    assert compute_alert_date(target, None) == target
    # Trigger date None returns None
    assert compute_alert_date(None, 60) is None


@pytest.mark.asyncio
async def test_extract_contract_zero_candidates(db_session: AsyncSession) -> None:
    org = Organization(name="Zero Candidates Org")
    db_session.add(org)
    await db_session.flush()

    contract, job = await _create_test_contract(db_session, org_id=org.id)

    # Chunk that did not pass prefilter
    chunk = ContractChunk(
        contract_id=contract.id,
        paragraph_index=0,
        section_heading="DEFINITIONS",
        raw_text="Some boilerplate text.",
        is_boilerplate=True,
        passed_prefilter=False,
    )
    db_session.add(chunk)
    await db_session.flush()

    mock_provider = MockLLMProvider()
    router = LLMRouter(groq_provider=mock_provider, gemini_provider=mock_provider)

    await extract_contract_obligations(db_session, contract_id=contract.id, router=router)

    assert mock_provider.call_count == 0  # No LLM call needed
    assert contract.status == ContractStatus.ACTIVE
    assert job.status == ExtractionJobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_extract_contract_successful_pipeline(db_session: AsyncSession) -> None:
    org = Organization(name="Extraction Pipeline Org")
    db_session.add(org)
    await db_session.flush()

    contract, job = await _create_test_contract(db_session, org_id=org.id)

    # Candidate chunk
    chunk = ContractChunk(
        contract_id=contract.id,
        paragraph_index=1,
        section_heading="TERM AND TERMINATION",
        raw_text="Either party may terminate upon 30 days written notice.",
        is_boilerplate=False,
        passed_prefilter=True,
        embedding=_UNIT_VEC,
    )
    db_session.add(chunk)
    await db_session.flush()

    mock_result = ContractExtractionResult(
        contract_type_guess=ContractType.VENDOR,
        counterparty_name_guess="Cloud Solutions Ltd",
        effective_date_guess=date(2026, 1, 1),
        expiration_date_guess=date(2027, 1, 1),
        obligations=[
            ExtractedObligation(
                category=ObligationCategory.TERMINATION_NOTICE,
                description="30 days written notice to terminate.",
                responsible_party="either party",
                trigger_date=date(2027, 1, 1),
                notice_period_days=30,
                recurrence=RecurrenceType.NONE,
                source_paragraph_index=1,
                confidence=0.92,
            ),
            ExtractedObligation(
                category=ObligationCategory.PAYMENT_MILESTONE,
                description="Net 30 payment terms.",
                responsible_party="us",
                trigger_date=date(2026, 6, 30),
                notice_period_days=14,
                monetary_amount=5000.0,
                currency="USD",
                recurrence=RecurrenceType.MONTHLY,
                source_paragraph_index=1,
                confidence=0.88,
            ),
        ],
    )

    mock_provider = MockLLMProvider(result=mock_result)
    router = LLMRouter(groq_provider=mock_provider, gemini_provider=mock_provider)

    await extract_contract_obligations(db_session, contract_id=contract.id, router=router)

    assert mock_provider.call_count == 1
    assert contract.status == ContractStatus.NEEDS_REVIEW
    assert contract.counterparty_name == "Cloud Solutions Ltd"
    assert contract.contract_type == ContractType.VENDOR
    assert job.status == ExtractionJobStatus.SUCCEEDED
    assert job.llm_provider_used == LLMProviderName.GROQ
    assert job.tokens_used_estimate == 280

    # Verify obligations created in database
    obs_query = select(Obligation).where(Obligation.contract_id == contract.id)
    obs = list((await db_session.execute(obs_query)).scalars().all())
    assert len(obs) == 2

    term_ob = next(o for o in obs if o.category == ObligationCategory.TERMINATION_NOTICE)
    assert term_ob.notice_period_days == 30
    assert term_ob.computed_alert_date == date(2026, 12, 2)
    # Termination notice mandatory review
    assert term_ob.is_human_reviewed is False

    pay_ob = next(o for o in obs if o.category == ObligationCategory.PAYMENT_MILESTONE)
    assert pay_ob.monetary_amount == 5000.0
    assert pay_ob.currency == "USD"
    assert pay_ob.computed_alert_date == date(2026, 6, 16)
    # Non-renewal/termination with high confidence does not require mandatory review
    assert pay_ob.is_human_reviewed is True

    # Verify high-confidence clause added to precedent cache
    cache_query = select(ClausePrecedentCache).where(ClausePrecedentCache.org_id == org.id)
    cached_entries = list((await db_session.execute(cache_query)).scalars().all())
    assert len(cached_entries) >= 1


@pytest.mark.asyncio
async def test_extract_contract_reuses_precedent_cache_and_skips_llm(
    db_session: AsyncSession,
) -> None:
    org = Organization(name="Cache Reuse Org")
    db_session.add(org)
    await db_session.flush()

    # Pre-seed precedent cache with an existing clause
    cached_payload = {
        "category": "RENEWAL",
        "description": "Auto-renews for 1 year.",
        "responsible_party": "both",
        "trigger_date": "2027-05-01",
        "notice_period_days": 60,
        "monetary_amount": None,
        "currency": None,
        "recurrence": "annually",
        "confidence": 0.98,
    }
    cache_row = ClausePrecedentCache(
        org_id=org.id,
        text_hash="abc" * 21 + "a",
        embedding=_UNIT_VEC,
        category=ObligationCategory.RENEWAL,
        cached_extraction=cached_payload,
        hit_count=0,
    )
    db_session.add(cache_row)
    await db_session.flush()

    contract, job = await _create_test_contract(db_session, org_id=org.id)

    # Chunk with vector near _UNIT_VEC (similarity > 0.99)
    chunk = ContractChunk(
        contract_id=contract.id,
        paragraph_index=1,
        section_heading="RENEWAL",
        raw_text="The agreement shall automatically renew for successive 1-year terms.",
        is_boilerplate=False,
        passed_prefilter=True,
        embedding=_NEAR_VEC,
    )
    db_session.add(chunk)
    await db_session.flush()

    mock_provider = MockLLMProvider()
    router = LLMRouter(groq_provider=mock_provider, gemini_provider=mock_provider)

    await extract_contract_obligations(db_session, contract_id=contract.id, router=router)

    # Because chunk matched precedent cache, zero LLM calls were required!
    assert mock_provider.call_count == 0
    assert job.status == ExtractionJobStatus.SUCCEEDED

    obs = list(
        (
            await db_session.execute(
                select(Obligation).where(Obligation.contract_id == contract.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(obs) == 1
    assert obs[0].category == ObligationCategory.RENEWAL
    assert obs[0].description == "Auto-renews for 1 year."
    assert obs[0].computed_alert_date == date(2027, 3, 2)


@pytest.mark.asyncio
async def test_extract_contract_failure_updates_status(db_session: AsyncSession) -> None:
    org = Organization(name="Failure Org")
    db_session.add(org)
    await db_session.flush()

    contract, job = await _create_test_contract(db_session, org_id=org.id)

    chunk = ContractChunk(
        contract_id=contract.id,
        paragraph_index=1,
        section_heading="TERM",
        raw_text="Candidate text.",
        is_boilerplate=False,
        passed_prefilter=True,
        embedding=_UNIT_VEC,
    )
    db_session.add(chunk)
    await db_session.flush()

    failing_provider = MockLLMProvider(exception=QuotaExhaustedError("All quotas exhausted"))
    router = LLMRouter(groq_provider=failing_provider, gemini_provider=failing_provider)

    with pytest.raises(QuotaExhaustedError):
        await extract_contract_obligations(db_session, contract_id=contract.id, router=router)

    assert contract.status == ContractStatus.ERROR
    assert job.status == ExtractionJobStatus.FAILED
    assert "All quotas exhausted" in (job.error_message or "")
