"""Load-test the token-minimization funnel against the full CUAD v1 corpus
(510 real contracts), per docs/CONTRACT_CLM_BUILD_PLAN.md §12 Phase 10:
"log tokens-used-per-contract before/after each filter stage, confirm the
>80% reduction expected from the funnel design in §3."

Runs entirely offline against local CUAD .txt files — no LLM calls, no
database writes. Stage 3 (clause dedup) is simulated in-memory: each
contract's surviving paragraphs are checked against every embedding seen
from *earlier* contracts in this same run (mirroring the real
clause_precedent_cache, which accumulates org-wide across contracts), using
the same cosine-similarity threshold as services/dedup.py.

Token counts are approximated as chars // 4 (no tokenizer dependency) —
labeled as an estimate throughout; the ratios this produces are what the
plan actually cares about, not an exact token count.

Usage (from backend/, with the venv active):
    python -m scripts.measure_token_funnel
    python -m scripts.measure_token_funnel --cuad-txt-dir ../data/cuad_v1/CUAD_v1/full_contract_txt
    python -m scripts.measure_token_funnel --limit 50
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.services.category_reference import passes_semantic_filter
from app.services.dedup import DEFAULT_DEDUP_SIMILARITY_THRESHOLD
from app.services.embeddings import embed_texts
from app.services.prefilter import classify_chunk

DEFAULT_CUAD_TXT_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "cuad_v1" / "CUAD_v1" / "full_contract_txt"
)
_CHARS_PER_TOKEN_ESTIMATE = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


@dataclass
class FunnelStats:
    contracts: int = 0
    raw_paragraphs: int = 0
    raw_tokens: int = 0
    stage1_paragraphs: int = 0
    stage1_tokens: int = 0
    stage2_paragraphs: int = 0
    stage2_tokens: int = 0
    stage3_paragraphs: int = 0
    stage3_tokens: int = 0
    dedup_hits: int = 0


def split_into_paragraphs(text: str) -> list[str]:
    """CUAD's plain-text dumps have no structural markup — blank-line
    separated blocks is the same paragraph granularity the real PDF/DOCX
    parsers produce (see document_parser.py)."""
    blocks = [b.strip() for b in text.split("\n\n")]
    return [b for b in blocks if b and len(b) > 20]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cuad-txt-dir", type=Path, default=DEFAULT_CUAD_TXT_DIR)
    parser.add_argument(
        "--limit", type=int, default=None, help="Only process the first N contracts."
    )
    parser.add_argument(
        "--embed-batch-size",
        type=int,
        default=64,
        help="Paragraphs embedded per model.encode() call.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not args.cuad_txt_dir.exists():
        raise SystemExit(
            f"CUAD text corpus not found at {args.cuad_txt_dir}. "
            "See data/README.md for how to fetch it, or pass --cuad-txt-dir."
        )

    files = sorted(args.cuad_txt_dir.glob("*.txt"))
    if args.limit:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"No .txt files found in {args.cuad_txt_dir}.")

    stats = FunnelStats()
    cached_embeddings: list[np.ndarray] = []
    cache_matrix: np.ndarray | None = None
    max_distance = 1 - DEFAULT_DEDUP_SIMILARITY_THRESHOLD

    started = time.monotonic()
    for i, path in enumerate(files, start=1):
        text = path.read_text(encoding="utf-8", errors="ignore")
        paragraphs = split_into_paragraphs(text)
        stats.contracts += 1
        stats.raw_paragraphs += len(paragraphs)
        stats.raw_tokens += sum(estimate_tokens(p) for p in paragraphs)

        # Stage 1: deterministic regex pre-filter (free).
        stage1 = [p for p in paragraphs if classify_chunk(section_heading=None, raw_text=p)[1]]
        stats.stage1_paragraphs += len(stage1)
        stats.stage1_tokens += sum(estimate_tokens(p) for p in stage1)
        if not stage1:
            continue

        # Stage 2: local semantic-similarity filter against the fixed
        # per-category reference embeddings (still free — local model only).
        embeddings = embed_texts(stage1)
        stage2_texts: list[str] = []
        stage2_vecs: list[np.ndarray] = []
        for text_, vec in zip(stage1, embeddings, strict=True):
            if passes_semantic_filter(vec):
                stage2_texts.append(text_)
                stage2_vecs.append(np.asarray(vec, dtype=np.float32))
        stats.stage2_paragraphs += len(stage2_texts)
        stats.stage2_tokens += sum(estimate_tokens(t) for t in stage2_texts)

        # Stage 3: clause-precedent dedup against every embedding cached
        # from earlier contracts (org-wide, exactly like clause_precedent_cache).
        for text_, stage2_vec in zip(stage2_texts, stage2_vecs, strict=True):
            is_dup = False
            if cache_matrix is not None and cache_matrix.shape[0] > 0:
                # Embeddings are L2-normalized (embeddings.py), so the dot
                # product against the cache is cosine similarity directly.
                similarities = cache_matrix @ stage2_vec
                max_similarity = float(similarities.max())
                is_dup = (1 - max_similarity) <= max_distance
            if is_dup:
                stats.dedup_hits += 1
            else:
                stats.stage3_paragraphs += 1
                stats.stage3_tokens += estimate_tokens(text_)
                cached_embeddings.append(stage2_vec)

        # Rebuild the lookup matrix once per contract, not per paragraph —
        # O(contracts) rebuilds instead of O(paragraphs) is what keeps this
        # tractable across the full 510-contract corpus.
        if cached_embeddings:
            cache_matrix = np.vstack(cached_embeddings)

        if i % 25 == 0 or i == len(files):
            elapsed = time.monotonic() - started
            print(f"  ...{i}/{len(files)} contracts ({elapsed:.0f}s elapsed)", file=sys.stderr)

    elapsed = time.monotonic() - started
    reduction = (
        1 - (stats.stage3_tokens / stats.raw_tokens) if stats.raw_tokens else 0
    )

    print()
    print(f"Token-minimization funnel — {stats.contracts} real CUAD contracts, {elapsed:.0f}s")
    print(f"{'Stage':<45s}{'Paragraphs':>12s}{'Est. tokens':>14s}")
    print(f"{'0. Raw (every paragraph)':<45s}{stats.raw_paragraphs:>12,d}{stats.raw_tokens:>14,d}")
    print(
        f"{'1. + regex pre-filter':<45s}{stats.stage1_paragraphs:>12,d}"
        f"{stats.stage1_tokens:>14,d}"
    )
    print(
        f"{'2. + local semantic-similarity filter':<45s}{stats.stage2_paragraphs:>12,d}"
        f"{stats.stage2_tokens:>14,d}"
    )
    print(
        f"{'3. + clause-precedent dedup (final LLM input)':<45s}{stats.stage3_paragraphs:>12,d}"
        f"{stats.stage3_tokens:>14,d}"
    )
    print(f"\nDedup cache hits avoided re-sending: {stats.dedup_hits:,d} paragraphs")
    print(f"Estimated token reduction vs. sending every paragraph: {reduction:.1%}")


if __name__ == "__main__":
    main()
