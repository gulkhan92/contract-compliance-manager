"""Builds the chatbot's clause-benchmark reference corpus
(`cuad_reference_clauses`) from the real, human-annotated CUAD v1 dataset —
not synthetic demo data. See docs/CHATBOT_INTEGRATION_PLAN.md §1/§3.2 and
app/db/models/cuad_reference_clause.py.

CUAD_v1.json is SQuAD-formatted: one "question" per (contract, category)
pair, embedding the category name in a fixed template ("...related to
"{category}" that should be reviewed..."), with zero or more real answer
spans (`is_impossible=false`) pointing at the actual clause text in that
contract. `master_clauses.csv` is deliberately NOT the source here — its
"-Answer" columns hold short extracted values ("Yes", "Nevada"), not the
verbatim clause text a benchmark comparison actually needs.

This is real reference data (CUAD is CC BY 4.0), not synthetic/demo data,
so — unlike scripts/seed_demo_data.py — it carries no --demo flag or
production guard; it's safe to run anywhere the dataset is present. It IS
idempotent-by-default: rerunning without --reset skips straight past an
already-populated corpus rather than duplicating it.

Usage (from backend/, with the venv active and the DB migrated):
    python -m scripts.build_cuad_reference_corpus
    python -m scripts.build_cuad_reference_corpus --limit 500 --reset
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select

from app.db.models import CuadReferenceClause
from app.db.session import AsyncSessionLocal
from app.services.embeddings import embed_texts

DEFAULT_CUAD_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "cuad_v1" / "CUAD_v1" / "CUAD_v1.json"
)

_CATEGORY_PATTERN = re.compile(r'related to "(.+?)"')
_EMBED_BATCH_SIZE = 128
# Below this, a span is a bare name/date/number, not clause text worth benchmarking.
_MIN_CLAUSE_LENGTH = 15


@dataclass(frozen=True)
class ReferenceClauseRow:
    category: str
    source_contract_title: str
    clause_text: str


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--cuad-path", type=Path, default=DEFAULT_CUAD_PATH, help="Path to CUAD_v1.json."
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Cap the number of rows built (default: all)."
    )
    parser.add_argument(
        "--reset", action="store_true", help="Delete any existing reference corpus first."
    )
    return parser.parse_args(argv)


def extract_reference_clauses(cuad_json: dict[str, Any]) -> list[ReferenceClauseRow]:
    """Pure parsing, independent of any DB/embedding call, so it's cheaply
    unit-testable against a small in-memory fixture."""
    seen: set[tuple[str, str]] = set()
    rows: list[ReferenceClauseRow] = []

    data = cuad_json.get("data")
    if not isinstance(data, list):
        return rows

    for contract in data:
        title = contract.get("title", "") if isinstance(contract, dict) else ""
        paragraphs = contract.get("paragraphs", []) if isinstance(contract, dict) else []
        for paragraph in paragraphs:
            for qa in paragraph.get("qas", []):
                if qa.get("is_impossible"):
                    continue
                match = _CATEGORY_PATTERN.search(qa.get("question", ""))
                if match is None:
                    continue
                category = match.group(1)
                for answer in qa.get("answers", []):
                    text = answer.get("text", "").strip()
                    if len(text) < _MIN_CLAUSE_LENGTH:
                        continue
                    key = (category, text)
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(
                        ReferenceClauseRow(
                            category=category, source_contract_title=title, clause_text=text
                        )
                    )
    return rows


async def build(args: argparse.Namespace) -> None:
    print(f"Reading {args.cuad_path} ...")
    with open(args.cuad_path, encoding="utf-8") as f:
        cuad_json = json.load(f)

    rows = extract_reference_clauses(cuad_json)
    if args.limit is not None:
        rows = rows[: args.limit]
    print(f"Extracted {len(rows)} unique (category, clause) reference rows.")

    async with AsyncSessionLocal() as session:
        if args.reset:
            result = await session.execute(delete(CuadReferenceClause))
            await session.commit()
            print(f"Deleted {result.rowcount} existing reference rows.")  # type: ignore[attr-defined]
        else:
            existing = await session.scalar(select(func.count()).select_from(CuadReferenceClause))
            if existing:
                print(
                    f"{existing} reference rows already present; skipping "
                    "(pass --reset to rebuild)."
                )
                return

        total = 0
        for start in range(0, len(rows), _EMBED_BATCH_SIZE):
            batch = rows[start : start + _EMBED_BATCH_SIZE]
            embeddings = embed_texts([row.clause_text for row in batch])
            session.add_all(
                CuadReferenceClause(
                    category=row.category,
                    source_contract_title=row.source_contract_title,
                    clause_text=row.clause_text,
                    embedding=embedding,
                )
                for row, embedding in zip(batch, embeddings, strict=True)
            )
            await session.commit()
            total += len(batch)
            print(f"  embedded + persisted {total}/{len(rows)}")

    print(f"Done — {total} reference clauses across the CUAD taxonomy.")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    asyncio.run(build(args))


if __name__ == "__main__":
    main()
