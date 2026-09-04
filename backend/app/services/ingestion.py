"""Orchestrates parsing + chunking + pre-filtering for one contract.

Runs synchronously inside the upload request rather than via a background
task/worker: this stage is fast, CPU-only, local parsing with no network or
LLM calls, so there's nothing here that benefits from being offloaded yet.
Phase 5's LLM extraction call is the step that actually needs async job
processing — via the `worker` process already wired in
infra/docker-compose.yml — and that's where extraction_jobs.status will
start meaning something over a non-trivial time window.
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ContractStatus, ExtractionJobStatus
from app.db.models import Contract, ContractChunk, ExtractionJob
from app.services.document_parser import parse_document
from app.services.file_validation import FileKind
from app.services.prefilter import classify_chunk


async def ingest_contract_document(
    db: AsyncSession,
    *,
    contract: Contract,
    extraction_job: ExtractionJob,
    file_kind: FileKind,
    data: bytes,
) -> None:
    extraction_job.status = ExtractionJobStatus.RUNNING
    extraction_job.started_at = datetime.now(UTC)
    await db.flush()

    try:
        paragraphs = parse_document(data, file_kind)
    except Exception as exc:  # parsing a hostile/corrupt file must not 500
        extraction_job.status = ExtractionJobStatus.FAILED
        extraction_job.error_message = f"Failed to parse document: {exc}"
        extraction_job.finished_at = datetime.now(UTC)
        contract.status = ContractStatus.ERROR
        await db.flush()
        return

    for paragraph in paragraphs:
        is_boilerplate, passed_prefilter = classify_chunk(
            section_heading=paragraph.section_heading, raw_text=paragraph.raw_text
        )
        db.add(
            ContractChunk(
                contract_id=contract.id,
                paragraph_index=paragraph.paragraph_index,
                section_heading=paragraph.section_heading,
                raw_text=paragraph.raw_text,
                is_boilerplate=is_boilerplate,
                passed_prefilter=passed_prefilter,
            )
        )

    extraction_job.status = ExtractionJobStatus.SUCCEEDED
    extraction_job.finished_at = datetime.now(UTC)
    await db.flush()
