"""Orchestrates the LLM extraction step for one contract: check the
clause-dedup cache first, batch everything that isn't a cache hit into a
single schema-constrained call, validate with one corrective retry,
fall back to the secondary provider on failure, and persist obligations —
computing calendar math in plain Python, never delegating it to the LLM.
If no provider currently has quota headroom, the extraction_job is left
QUEUED rather than failed, so a future retry sweep can pick it back up.
See docs/CONTRACT_CLM_BUILD_PLAN.md §3, §7, and §12 Phase 5.

The schema-constrained-call-with-retry-and-fallback machinery itself lives
in services/llm/orchestration.py, shared with the chatbot's generation step
(docs/CHATBOT_INTEGRATION_PLAN.md §6.2) rather than duplicated here.
"""

import hashlib
import logging
import uuid
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ContractStatus, ExtractionJobStatus, ObligationCategory
from app.db.models import ClausePrecedentCache, Contract, ContractChunk, ExtractionJob, Obligation
from app.schemas.extraction import ContractExtractionResult, ExtractedObligation
from app.services.dedup import find_cached_extraction
from app.services.llm.orchestration import call_llm_with_fallback
from app.services.llm.prompt import SYSTEM_PROMPT, build_user_prompt, chunk_label
from app.services.obligation_dates import compute_alert_date, initial_obligation_status

logger = logging.getLogger(__name__)

_HIGH_STAKES_CATEGORIES = (ObligationCategory.RENEWAL, ObligationCategory.TERMINATION_NOTICE)
_CONFIDENCE_REVIEW_THRESHOLD = 0.7


def _is_human_reviewed(category: ObligationCategory, confidence: float) -> bool:
    """Every obligation touching TERMINATION_NOTICE/RENEWAL, or below the
    confidence threshold, is surfaced for human review — this system
    assists a human, it never silently auto-trusts the LLM for legally
    binding dates. See §7."""
    if category in _HIGH_STAKES_CATEGORIES:
        return False
    return confidence >= _CONFIDENCE_REVIEW_THRESHOLD


def _build_obligation(
    *,
    contract_id: uuid.UUID,
    source_chunk_id: uuid.UUID,
    raw_source_text: str,
    extracted: ExtractedObligation,
) -> Obligation:
    computed_alert_date = compute_alert_date(extracted.trigger_date, extracted.notice_period_days)
    return Obligation(
        contract_id=contract_id,
        source_chunk_id=source_chunk_id,
        category=extracted.category,
        description=extracted.description,
        responsible_party=extracted.responsible_party,
        trigger_date=extracted.trigger_date,
        notice_period_days=extracted.notice_period_days,
        computed_alert_date=computed_alert_date,
        monetary_amount=extracted.monetary_amount,
        currency=extracted.currency,
        recurrence=extracted.recurrence,
        status=initial_obligation_status(extracted.trigger_date, computed_alert_date),
        confidence_score=extracted.confidence,
        is_human_reviewed=_is_human_reviewed(extracted.category, extracted.confidence),
        raw_source_text=raw_source_text,
    )


def _obligations_from_cache(cached_extraction: object) -> list[ExtractedObligation]:
    if not isinstance(cached_extraction, list):
        return []
    obligations: list[ExtractedObligation] = []
    for item in cached_extraction:
        try:
            obligations.append(ExtractedObligation.model_validate(item))
        except ValidationError:
            logger.warning("Skipping malformed cached extraction entry.")
    return obligations


def _average_confidence(obligations: list[ExtractedObligation]) -> float | None:
    if not obligations:
        return None
    return sum(o.confidence for o in obligations) / len(obligations)


async def _run_llm_batch(
    session: AsyncSession,
    *,
    contract: Contract,
    extraction_job: ExtractionJob,
    chunks: list[ContractChunk],
) -> int | None:
    """Returns the number of obligations persisted (0 or more) on
    success, or None if no provider was available / every provider
    failed — the caller must treat None as "still queued", not a hard
    failure of the whole contract."""
    user_prompt = build_user_prompt(chunks)
    outcome = await call_llm_with_fallback(
        session,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=ContractExtractionResult,
    )
    if outcome is None:
        logger.info("No LLM provider had headroom for contract %s; leaving it queued.", contract.id)
        return None

    provider_name, extraction_result, tokens_used = outcome
    extraction_job.llm_provider_used = provider_name
    extraction_job.tokens_used_estimate = (
        extraction_job.tokens_used_estimate or 0
    ) + tokens_used

    contract.extraction_confidence = _average_confidence(extraction_result.obligations)
    if contract.counterparty_name is None:
        contract.counterparty_name = extraction_result.counterparty_name_guess
    if contract.effective_date is None:
        contract.effective_date = extraction_result.effective_date_guess
    if contract.original_expiration_date is None:
        contract.original_expiration_date = extraction_result.expiration_date_guess

    chunks_by_label = {chunk_label(c): c for c in chunks}
    obligations_by_chunk_id: dict[uuid.UUID, list[ExtractedObligation]] = {c.id: [] for c in chunks}

    persisted = 0
    for extracted in extraction_result.obligations:
        chunk = chunks_by_label.get(extracted.source_paragraph_id)
        if chunk is None:
            logger.warning(
                "LLM cited unknown source_paragraph_id %r; skipping.", extracted.source_paragraph_id
            )
            continue
        session.add(
            _build_obligation(
                contract_id=contract.id,
                source_chunk_id=chunk.id,
                raw_source_text=chunk.raw_text,
                extracted=extracted,
            )
        )
        obligations_by_chunk_id[chunk.id].append(extracted)
        persisted += 1

    # One clause_precedent_cache entry per chunk we actually sent to the
    # LLM — including chunks where it found nothing, so a future
    # near-duplicate of *that* text also short-circuits (§3 step 3).
    for chunk in chunks:
        chunk_obligations = obligations_by_chunk_id[chunk.id]
        session.add(
            ClausePrecedentCache(
                org_id=contract.org_id,
                text_hash=hashlib.sha256(chunk.raw_text.encode("utf-8")).hexdigest(),
                embedding=chunk.embedding,
                category=(
                    chunk_obligations[0].category
                    if chunk_obligations
                    else ObligationCategory.OTHER_OBLIGATION
                ),
                cached_extraction=[o.model_dump(mode="json") for o in chunk_obligations],
            )
        )

    return persisted


async def _finalize_contract(session: AsyncSession, *, contract: Contract) -> None:
    result = await session.execute(
        select(Obligation.is_human_reviewed).where(Obligation.contract_id == contract.id)
    )
    review_flags = result.scalars().all()
    if not review_flags:
        return
    needs_review = any(not flag for flag in review_flags)
    contract.status = ContractStatus.NEEDS_REVIEW if needs_review else ContractStatus.ACTIVE


async def extract_contract_obligations(
    session: AsyncSession, *, contract: Contract, extraction_job: ExtractionJob
) -> None:
    """Runs LLM extraction for one contract's already-embedded candidate
    chunks. Never raises — this runs inside the same request as the
    upload (for now; see ingestion.py's note on synchronous vs. worker
    processing) and a provider outage must not 500 that request. Every
    outcome, including "no provider available right now", is recorded on
    extraction_job/contract instead."""
    result = await session.execute(
        select(ContractChunk)
        .where(ContractChunk.contract_id == contract.id, ContractChunk.passed_prefilter.is_(True))
        .order_by(ContractChunk.paragraph_index)
    )
    candidate_chunks = [c for c in result.scalars().all() if c.embedding is not None]
    if not candidate_chunks:
        return

    chunks_needing_llm: list[ContractChunk] = []

    for chunk in candidate_chunks:
        # candidate_chunks was already filtered to embedding is not None above,
        # but that narrowing doesn't survive the mapped-attribute re-access.
        assert chunk.embedding is not None
        cached = await find_cached_extraction(
            session, org_id=contract.org_id, embedding=chunk.embedding
        )
        if cached is None:
            chunks_needing_llm.append(chunk)
            continue
        for extracted in _obligations_from_cache(cached.cached_extraction):
            session.add(
                _build_obligation(
                    contract_id=contract.id,
                    source_chunk_id=chunk.id,
                    raw_source_text=chunk.raw_text,
                    extracted=extracted,
                )
            )

    if chunks_needing_llm:
        llm_result = await _run_llm_batch(
            session, contract=contract, extraction_job=extraction_job, chunks=chunks_needing_llm
        )
        if llm_result is None:
            # No provider had headroom, or every provider failed. What
            # was already persisted via cache hits stays persisted; the
            # job goes back to QUEUED (even though the caller may have
            # already marked it RUNNING) so a future retry sweep can find
            # it by status rather than it looking permanently in-flight.
            extraction_job.status = ExtractionJobStatus.QUEUED
            await session.flush()
            return

    await session.flush()
    await _finalize_contract(session, contract=contract)
    extraction_job.status = ExtractionJobStatus.SUCCEEDED
    extraction_job.finished_at = datetime.now(UTC)
    await session.flush()
