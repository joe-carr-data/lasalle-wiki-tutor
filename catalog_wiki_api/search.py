"""Baseline lexical search for programs.

Phase 3 keeps this intentionally simple: token overlap on
(title + tags + short_description), boosted by area/level keyword hits.
BM25 / semantic search is deferred to Phase 4.
"""

from __future__ import annotations

import re
from typing import Any


_WORD_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9]{2,}")


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(s or "")}


def score_program(query: str, program: dict[str, Any]) -> float:
    """Return a numeric relevance score for a program against a query.

    Components:
      - title token overlap × 1.0
      - tags overlap × 0.6
      - area / level token hit (single boost) × 0.4
      - slug token overlap × 0.3
    """
    qt = _tokens(query)
    if not qt:
        return 0.0

    title_t = _tokens(program.get("title", ""))
    tags_t = {t.lower() for t in (program.get("tags") or [])}
    slug_t = set((program.get("slug", "") or "").lower().split("-"))
    area = (program.get("area") or "").replace("-", " ").lower()
    level = (program.get("level") or "").lower()

    score = 0.0
    score += len(qt & title_t) * 1.0
    score += len(qt & tags_t) * 0.6
    score += len(qt & slug_t) * 0.3
    if any(tok in area for tok in qt):
        score += 0.4
    if level and level in qt:
        score += 0.4

    # Normalize by query size to avoid favoring longer queries
    return score / max(1.0, len(qt))


def rank_programs(
    query: str,
    programs: list[dict[str, Any]],
    top_k: int = 10,
) -> list[tuple[float, dict[str, Any]]]:
    """Return [(score, program), ...] sorted descending, top_k."""
    scored = [(score_program(query, p), p) for p in programs]
    scored = [(s, p) for s, p in scored if s > 0]
    scored.sort(key=lambda x: -x[0])
    return scored[:top_k]
