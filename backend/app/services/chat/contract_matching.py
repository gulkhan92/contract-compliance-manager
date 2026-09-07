"""Conservative contract-name matching for org-wide chat sessions (plan
§3.4: "counterparty_name... parsed from phrases like 'our NDAs with
Acme'"). Deliberately never a hard restriction on its own — pipeline.py
tries a search narrowed to the matched contract(s) first and falls back
to the full org-wide search if nothing clears the relevance bar, so a
spurious or overly-broad match can only ever degrade to today's
unscoped behavior, never produce a worse or wrong-contract answer.

Matching is title-substring-based, not an LLM call: strip a small set of
words that carry no discriminating signal on their own (every contract's
title contains "agreement"), then require *every* remaining significant
word to appear in the query. Two contracts can legitimately share an
identical title (this project's own demo data has two both literally
named "CO-BRANDING AGREEMENT") — the result is the *set* of every
contract that matches, never a single arbitrarily-chosen one.
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Contract

_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "our", "on",
    "with", "agreement", "contract",
}
_MIN_WORD_LENGTH = 3


def _significant_words(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) >= _MIN_WORD_LENGTH}


async def resolve_mentioned_contract_ids(
    session: AsyncSession, *, org_id: uuid.UUID, query_text: str
) -> list[uuid.UUID]:
    """Every contract in the org whose title is confidently named in the
    query — every one of that title's significant words must appear in
    the query text. Returns an empty list when nothing matches, which
    callers must treat as "no confident mention, search everything," not
    as "matched zero contracts, search nothing.\""""
    lowered_query = query_text.lower()
    result = await session.execute(
        select(Contract.id, Contract.title).where(Contract.org_id == org_id)
    )

    matched: list[uuid.UUID] = []
    for contract_id, title in result.all():
        significant = _significant_words(title)
        if not significant:
            continue  # a title with no significant words can't be named specifically
        if all(word in lowered_query for word in significant):
            matched.append(contract_id)
    return matched
