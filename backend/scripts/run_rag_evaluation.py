"""Runs the offline RAG evaluation harness (plan §7.1, §12.7): CUAD-derived
question/ground-truth pairs — sampled from real contracts already present
in a target organization (default: the demo org from
scripts/seed_demo_data.py) — scored against the live retrieval + generation
pipeline using the four metrics in services/chat/evaluation.py.

Skips cleanly (exit 0, no results written) rather than failing the build
when no LLM provider is configured: this project's CI has no Groq/Gemini
secret provisioned (those are the user's own account, not something a
build pipeline can be handed), so a hard failure here would block every
merge for a reason no contributor could fix from the PR alone. Run it
manually with real keys before a release instead. See docs/CHATBOT_EVALUATION.md.

Usage (from backend/, with the venv active, the DB migrated and seeded via
`python -m scripts.seed_demo_data --demo`, and GROQ_API_KEY/GEMINI_API_KEY
set in your .env):
    python -m scripts.run_rag_evaluation
    python -m scripts.run_rag_evaluation --org-name "Demo Legal Ops" --sample-size 30
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.enums import ChatSessionScope
from app.db.models import Contract, Organization
from app.db.session import AsyncSessionLocal
from app.services.chat.evaluation import (
    RagEvalResult,
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
    save_eval_result,
    utcnow,
)
from app.services.chat.pipeline import run_chat_turn
from scripts.build_cuad_reference_corpus import ReferenceClauseRow, extract_reference_clauses

DEFAULT_CUAD_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "cuad_v1" / "CUAD_v1" / "CUAD_v1.json"
)
DEFAULT_ORG_NAME = "Demo Legal Ops"
DEFAULT_SAMPLE_SIZE = 25
# CUAD's raw filenames stay .pdf-suffixed in the CSV column
# scripts/seed_demo_data.py copies into Contract.original_filename;
# CUAD_v1.json's own `title` field for the same contract omits it.
_PDF_SUFFIX = ".pdf"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--org-name", default=DEFAULT_ORG_NAME, help="Org to evaluate against.")
    parser.add_argument("--cuad-path", type=Path, default=DEFAULT_CUAD_PATH)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    return parser.parse_args(argv)


async def _seeded_contract_titles(
    session: AsyncSession, *, org_name: str
) -> tuple[Organization | None, dict[str, str]]:
    """Returns (org, {cuad_title: contract_id}) for every contract in this
    org whose original_filename matches a CUAD document — i.e. only the
    contracts a real question can actually be grounded against."""
    org = await session.scalar(select(Organization).where(Organization.name == org_name))
    if org is None:
        return None, {}
    result = await session.execute(select(Contract).where(Contract.org_id == org.id))
    titles = {}
    for contract in result.scalars().all():
        if contract.original_filename.endswith(_PDF_SUFFIX):
            titles[contract.original_filename[: -len(_PDF_SUFFIX)]] = str(contract.id)
    return org, titles


def _build_eval_questions(
    cuad_json: dict[str, Any], seeded_titles: set[str], sample_size: int
) -> list[tuple[str, str]]:
    """(question, ground_truth_answer) pairs, phrased as natural-language
    questions rather than CUAD's own "Highlight the parts..." template —
    that template is a span-extraction prompt, not how a real user asks;
    using it verbatim would evaluate a task the chatbot doesn't perform.

    Round-robins across CUAD's ~41 categories rather than taking the
    first `sample_size` rows outright — those sort heavily skewed toward
    whichever category happens to come first alphabetically among a
    given org's contracts, which would evaluate "how well does the
    pipeline handle this one category" far more than the rest.
    """
    rows = extract_reference_clauses(cuad_json)
    matched = [row for row in rows if row.source_contract_title in seeded_titles]

    by_category: dict[str, list[ReferenceClauseRow]] = {}
    for row in matched:
        by_category.setdefault(row.category, []).append(row)
    for category_rows in by_category.values():
        category_rows.sort(key=lambda row: row.source_contract_title)

    sampled: list[ReferenceClauseRow] = []
    categories = sorted(by_category)
    round_index = 0
    while len(sampled) < sample_size:
        added_this_round = False
        for category in categories:
            if len(sampled) >= sample_size:
                break
            bucket = by_category[category]
            if round_index < len(bucket):
                sampled.append(bucket[round_index])
                added_this_round = True
        if not added_this_round:
            break  # every category's bucket is exhausted
        round_index += 1

    return [
        (f"What does this contract say about {row.category.lower()}?", row.clause_text)
        for row in sampled
    ]


async def run_evaluation(args: argparse.Namespace) -> RagEvalResult | None:
    async with AsyncSessionLocal() as session:
        org, seeded_titles = await _seeded_contract_titles(session, org_name=args.org_name)
        if org is None:
            print(f"No organization named {args.org_name!r} found — seed demo data first.")
            return None

        print(f"Reading {args.cuad_path} ...")
        with open(args.cuad_path, encoding="utf-8") as f:
            cuad_json = json.load(f)

        questions = _build_eval_questions(cuad_json, set(seeded_titles), args.sample_size)
        if not questions:
            print("No CUAD-derived questions matched this org's seeded contracts.")
            return None
        print(f"Evaluating {len(questions)} questions against {args.org_name!r} ...")

        precisions, recalls, faithfulnesses, relevancies = [], [], [], []
        for i, (question, ground_truth) in enumerate(questions, start=1):
            result = await run_chat_turn(
                session,
                org_id=org.id,
                scope=ChatSessionScope.ORGANIZATION,
                scope_contract_id=None,
                question=question,
                history=[],
            )
            precisions.append(context_precision(result.reference_items, ground_truth))
            recalls.append(context_recall(result.reference_items, ground_truth))
            faithfulnesses.append(faithfulness(result.answer))
            relevancies.append(answer_relevancy(question, result.answer))
            print(f"  [{i}/{len(questions)}] {result.answer.confidence}: {question}")

        n = len(questions)
        eval_result = RagEvalResult(
            run_at=utcnow(),
            faithfulness=sum(faithfulnesses) / n,
            answer_relevancy=sum(relevancies) / n,
            context_precision=sum(precisions) / n,
            context_recall=sum(recalls) / n,
            num_questions=n,
        )
        return eval_result


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if not args.cuad_path.exists():
        print(
            f"{args.cuad_path} not found (data/ is git-ignored — see data/README.md) — "
            "skipping RAG evaluation."
        )
        return
    settings = get_settings()
    if not settings.groq_api_key and not settings.gemini_api_key:
        print(
            "No GROQ_API_KEY or GEMINI_API_KEY configured — skipping RAG evaluation "
            "(this is expected in CI; run manually with real keys before a release)."
        )
        return

    eval_result = asyncio.run(run_evaluation(args))
    if eval_result is None:
        return

    save_eval_result(eval_result)
    print(
        f"\nResults ({eval_result.num_questions} questions):\n"
        f"  context_precision:  {eval_result.context_precision:.3f}\n"
        f"  context_recall:     {eval_result.context_recall:.3f}\n"
        f"  faithfulness:       {eval_result.faithfulness:.3f}\n"
        f"  answer_relevancy:   {eval_result.answer_relevancy:.3f}\n"
    )


if __name__ == "__main__":
    main()
