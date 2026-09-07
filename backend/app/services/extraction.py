"""Core extraction service orchestrator.

Handles candidate retrieval, precedent cache dedup lookup, LLM batching,
schema-constrained structured extraction, deterministic date arithmetic,
human-in-the-loop review gating, and database persistence.
See docs/CONTRACT_CLM_BUILD_PLAN.md §3, §5, §7.
"""

import hashlib
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import (
    ContractStatus,
    ContractType,
    ExtractionJobStatus,
    ObligationCategory,
    ObligationStatus,
    RecurrenceType,
)
from app.db.models import (
    ClausePrecedentCache,
    Contract,
    ContractChunk,
    ExtractionJob,
    Obligation,
)
from app.schemas.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    ContractExtractionResult,
    build_extraction_prompt,
)
from app.services.dedup import find_cached_extraction
from app.services.llm.router import LLMRouter

logger = logging.getLogger(__name__)

# Categories requiring mandatory human review regardless of confidence score
_MANDATORY_REVIEW_CATEGORIES = {
    ObligationCategory.RENEWAL,
    ObligationCategory.TERMINATION_NOTICE,
}
_CONFIDENCE_REVIEW_THRESHOLD = 0.70


def compute_alert_date(
    trigger_date: date | None, notice_period_days: int | None
) -> date | None:
    """Deterministic date arithmetic: computed_alert_date = trigger_date - notice_period_days."""
    if not trigger_date:
        return None
    if notice_period_days and notice_period_days > 0:
        return trigger_date - timedelta(days=notice_period_days)
    return trigger_date



def requires_human_review(category: ObligationCategory, confidence: float | None) -> bool:
    """Flags obligation for human review queue if confidence < 0.7 or high-stakes category."""
    return (
        category in _MANDATORY_REVIEW_CATEGORIES
        or confidence is None
        or confidence < _CONFIDENCE_REVIEW_THRESHOLD
    )


async def extract_contract_obligations(
    db: AsyncSession,
    *,
    contract_id: uuid.UUID,
    router: LLMRouter | None = None,
) -> None:
    """Orchestrates structured obligation extraction for a contract."""
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise ValueError(f"Contract {contract_id} not found.")

    # Retrieve most recent extraction job for this contract
    job_stmt = (
        select(ExtractionJob)
        .where(ExtractionJob.contract_id == contract_id)
        .order_by(ExtractionJob.started_at.desc().nullslast())
    )

    job_res = await db.execute(job_stmt)
    extraction_job = job_res.scalars().first()
    if extraction_job is None:
        extraction_job = ExtractionJob(
            contract_id=contract_id,
            status=ExtractionJobStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(extraction_job)
    else:
        extraction_job.status = ExtractionJobStatus.RUNNING
        extraction_job.started_at = datetime.now(UTC)
        extraction_job.error_message = None

    await db.flush()

    # Load chunks
    chunk_stmt = (
        select(ContractChunk)
        .where(ContractChunk.contract_id == contract_id)
        .order_by(ContractChunk.paragraph_index)
    )
    chunk_res = await db.execute(chunk_stmt)
    all_chunks = list(chunk_res.scalars().all())

    candidate_chunks = [
        chunk for chunk in all_chunks if chunk.passed_prefilter and not chunk.is_boilerplate
    ]

    if not candidate_chunks:
        logger.info(
            "Contract %s has no candidate chunks. Marking succeeded with 0 obligations.",
            contract_id,
        )
        contract.status = ContractStatus.ACTIVE
        contract.extraction_confidence = 1.0
        extraction_job.status = ExtractionJobStatus.SUCCEEDED
        extraction_job.finished_at = datetime.now(UTC)
        await db.flush()
        return

    chunk_by_idx: dict[int, ContractChunk] = {c.paragraph_index: c for c in all_chunks}
    active_router = router or LLMRouter()

    try:
        # 1. Check Clause Precedent Cache for deduplication (Zero LLM cost)
        uncached_chunks: list[ContractChunk] = []
        reused_items: list[tuple[ContractChunk, dict[str, Any]]] = []

        for chunk in candidate_chunks:
            if chunk.embedding is not None:
                cached_match = await find_cached_extraction(
                    db, org_id=contract.org_id, embedding=chunk.embedding
                )
                if cached_match is not None:
                    logger.info(
                        "Deduplication hit for chunk %s (category: %s). Reusing cached extraction.",
                        chunk.id,
                        cached_match.category,
                    )
                    reused_items.append((chunk, cached_match.cached_extraction))
                    continue
            uncached_chunks.append(chunk)

        extracted_obligations_to_save: list[Obligation] = []
        new_precedent_cache_entries: list[ClausePrecedentCache] = []

        # 2. Rehydrate reused obligations from precedent cache
        for chunk, cached_dict in reused_items:
            category_val = ObligationCategory(
                cached_dict.get("category", ObligationCategory.OTHER_OBLIGATION)
            )
            trig_date = (
                datetime.fromisoformat(cached_dict["trigger_date"]).date()
                if cached_dict.get("trigger_date")
                else None
            )
            notice_days = cached_dict.get("notice_period_days")
            alert_dt = compute_alert_date(trig_date, notice_days)
            conf = float(cached_dict.get("confidence", 0.95))

            ob = Obligation(
                contract_id=contract.id,
                source_chunk_id=chunk.id,
                category=category_val,
                description=cached_dict.get("description", "Cached obligation"),
                responsible_party=cached_dict.get("responsible_party"),
                trigger_date=trig_date,
                notice_period_days=notice_days,
                computed_alert_date=alert_dt,
                monetary_amount=cached_dict.get("monetary_amount"),
                currency=cached_dict.get("currency"),
                recurrence=RecurrenceType(cached_dict.get("recurrence", RecurrenceType.NONE)),
                status=ObligationStatus.UPCOMING,
                confidence_score=conf,
                is_human_reviewed=not requires_human_review(category_val, conf),
                raw_source_text=chunk.raw_text,
            )
            extracted_obligations_to_save.append(ob)

        # 3. Call LLM for remaining uncached candidate paragraphs
        if uncached_chunks:
            prompt_tuples = [
                (c.paragraph_index, c.section_heading, c.raw_text) for c in uncached_chunks
            ]
            user_prompt = build_extraction_prompt(prompt_tuples)

            extraction_resp = await active_router.extract_with_failover(
                db,
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )

            result: ContractExtractionResult = extraction_resp.result
            extraction_job.llm_provider_used = extraction_resp.provider
            extraction_job.tokens_used_estimate = extraction_resp.tokens_used

            # Update contract guessed metadata
            if result.contract_type_guess and contract.contract_type == ContractType.OTHER:
                contract.contract_type = result.contract_type_guess
            if result.counterparty_name_guess:
                contract.counterparty_name = result.counterparty_name_guess
            if result.effective_date_guess:
                contract.effective_date = result.effective_date_guess
            if result.expiration_date_guess:
                contract.original_expiration_date = result.expiration_date_guess

            # Process new obligations
            for ext in result.obligations:
                # Resolve source chunk
                source_chunk = chunk_by_idx.get(ext.source_paragraph_index)
                if source_chunk is None and uncached_chunks:
                    source_chunk = uncached_chunks[0]

                alert_date = compute_alert_date(ext.trigger_date, ext.notice_period_days)
                needs_review = requires_human_review(ext.category, ext.confidence)

                source_chunk_id = source_chunk.id if source_chunk else None
                source_text = source_chunk.raw_text if source_chunk else None

                ob = Obligation(
                    contract_id=contract.id,
                    source_chunk_id=source_chunk_id,
                    category=ext.category,
                    description=ext.description,
                    responsible_party=ext.responsible_party,
                    trigger_date=ext.trigger_date,
                    notice_period_days=ext.notice_period_days,
                    computed_alert_date=alert_date,
                    monetary_amount=ext.monetary_amount,
                    currency=ext.currency,
                    recurrence=ext.recurrence,
                    status=ObligationStatus.UPCOMING,
                    confidence_score=ext.confidence,
                    is_human_reviewed=not needs_review,
                    raw_source_text=source_text,
                )
                extracted_obligations_to_save.append(ob)

                # If high-confidence and chunk has embedding, cache for future dedup
                if source_chunk and source_chunk.embedding and ext.confidence >= 0.8:
                    text_hash = hashlib.sha256(source_chunk.raw_text.encode("utf-8")).hexdigest()
                    cache_entry = ClausePrecedentCache(
                        org_id=contract.org_id,
                        text_hash=text_hash,
                        embedding=source_chunk.embedding,
                        category=ext.category,
                        cached_extraction={
                            "category": ext.category.value,
                            "description": ext.description,
                            "responsible_party": ext.responsible_party,
                            "trigger_date": (
                                ext.trigger_date.isoformat() if ext.trigger_date else None
                            ),
                            "notice_period_days": ext.notice_period_days,
                            "monetary_amount": ext.monetary_amount,
                            "currency": ext.currency,
                            "recurrence": ext.recurrence.value,
                            "confidence": ext.confidence,
                        },
                        hit_count=0,
                    )
                    new_precedent_cache_entries.append(cache_entry)

        # 4. Save obligations and new cache entries
        if extracted_obligations_to_save:
            db.add_all(extracted_obligations_to_save)

        if new_precedent_cache_entries:
            db.add_all(new_precedent_cache_entries)

        # 5. Determine contract status and overall confidence
        has_unreviewed = any(not ob.is_human_reviewed for ob in extracted_obligations_to_save)
        contract.status = ContractStatus.NEEDS_REVIEW if has_unreviewed else ContractStatus.ACTIVE

        if extracted_obligations_to_save:
            scores = [
                ob.confidence_score
                for ob in extracted_obligations_to_save
                if ob.confidence_score is not None
            ]
            contract.extraction_confidence = (sum(scores) / len(scores)) if scores else 0.85
        else:
            contract.extraction_confidence = 1.0


        extraction_job.status = ExtractionJobStatus.SUCCEEDED
        extraction_job.finished_at = datetime.now(UTC)
        await db.flush()

    except Exception as exc:
        logger.exception("Extraction failed for contract %s: %s", contract_id, exc)
        extraction_job.status = ExtractionJobStatus.FAILED
        extraction_job.error_message = str(exc)
        extraction_job.finished_at = datetime.now(UTC)
        contract.status = ContractStatus.ERROR
        await db.flush()
        raise
