"""Backfills `contract_chunks` for contracts that have none — specifically
the demo org: scripts/seed_demo_data.py creates `Contract`/`Obligation`
rows directly from CUAD's pre-extracted annotations (fast, deterministic,
no LLM cost) without ever running the real ingestion pipeline, so those
contracts' real PDF files sit on disk unparsed and unembedded. That's fine
for the extraction/obligation/calendar features, which only need
`Obligation` rows — but the chatbot's retrieval has nothing to search
without real `contract_chunks`. Found via live-testing the chatbot against
the seeded demo org: every domain-question query returned
insufficient_information because retrieval found zero chunks, not because
of any LLM/API-key problem.

Replicates services/ingestion.py's parse -> prefilter -> embed steps
exactly (same `classify_chunk` logic, same "only embed passed_prefilter
chunks" rule), reading each contract's already-saved file from disk via
services/storage.py — but deliberately stops there: it never calls
extract_contract_obligations, so it costs zero LLM tokens and creates no
duplicate obligations alongside the ones seed_demo_data.py already wrote.

Usage (from backend/, with the venv active and the DB migrated/seeded):
    python -m scripts.backfill_contract_chunks
    python -m scripts.backfill_contract_chunks --org-name "Demo Legal Ops"
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Contract, ContractChunk, Organization
from app.db.session import AsyncSessionLocal
from app.services.document_parser import parse_document
from app.services.embeddings import embed_texts
from app.services.file_validation import detect_file_kind
from app.services.prefilter import classify_chunk
from app.services.storage import read_contract_file


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-name", default=None, help="Limit to one org (default: all orgs).")
    return parser.parse_args(argv)


async def _contracts_missing_chunks(
    session: AsyncSession, *, org_name: str | None
) -> list[Contract]:
    query = select(Contract)
    if org_name is not None:
        org = await session.scalar(select(Organization).where(Organization.name == org_name))
        if org is None:
            return []
        query = query.where(Contract.org_id == org.id)
    contracts = list((await session.execute(query)).scalars().all())

    existing = set(
        (await session.execute(select(ContractChunk.contract_id).distinct())).scalars().all()
    )
    return [c for c in contracts if c.id not in existing]


async def _backfill_one(session: AsyncSession, contract: Contract) -> int:
    data = read_contract_file(contract.storage_path)
    file_kind = detect_file_kind(data)
    paragraphs = parse_document(data, file_kind)

    chunks: list[ContractChunk] = []
    candidate_texts: list[str] = []
    candidate_indices: list[int] = []
    for paragraph in paragraphs:
        is_boilerplate, passed_prefilter = classify_chunk(
            section_heading=paragraph.section_heading, raw_text=paragraph.raw_text
        )
        chunk = ContractChunk(
            contract_id=contract.id,
            paragraph_index=paragraph.paragraph_index,
            section_heading=paragraph.section_heading,
            raw_text=paragraph.raw_text,
            is_boilerplate=is_boilerplate,
            passed_prefilter=passed_prefilter,
        )
        chunks.append(chunk)
        if passed_prefilter:
            candidate_indices.append(len(chunks) - 1)
            candidate_texts.append(paragraph.raw_text)

    if candidate_texts:
        embeddings = embed_texts(candidate_texts)
        for chunk_index, embedding in zip(candidate_indices, embeddings, strict=True):
            chunks[chunk_index].embedding = embedding

    session.add_all(chunks)
    return len(chunks)


async def backfill(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as session:
        contracts = await _contracts_missing_chunks(session, org_name=args.org_name)
        if not contracts:
            print("No contracts are missing chunks.")
            return
        print(f"Backfilling chunks for {len(contracts)} contract(s) ...")

        total_chunks = 0
        for i, contract in enumerate(contracts, start=1):
            try:
                count = await _backfill_one(session, contract)
            except FileNotFoundError:
                print(f"  [{i}/{len(contracts)}] {contract.title[:60]!r}: file missing, skipped")
                continue
            await session.commit()
            total_chunks += count
            print(f"  [{i}/{len(contracts)}] {contract.title[:60]!r}: {count} chunks")

        print(f"Done — {total_chunks} chunks across {len(contracts)} contracts.")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    asyncio.run(backfill(args))


if __name__ == "__main__":
    main()
