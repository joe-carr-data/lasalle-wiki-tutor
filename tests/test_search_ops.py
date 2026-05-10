"""Operational tests for the retrieval layer.

Covers:
  - Mode override on retrieve_program_candidates
  - Graceful degradation when the semantic sidecar is missing
  - Memory ceiling: process stays under a reasonable RSS through 100 sequential queries
"""

from __future__ import annotations

import os
import resource
from pathlib import Path

import pytest

import catalog_wiki_api as api
from catalog_wiki_api import search as search_mod


@pytest.fixture(scope="session", autouse=True)
def _wiki_present():
    if not any(l["program_count"] > 0 for l in api.list_languages()):
        pytest.skip("Wiki not rendered yet")


# ---------------------------------------------------------------------------
# Mode override
# ---------------------------------------------------------------------------


def test_retrieve_modes_return_results():
    for mode in ("hybrid", "lexical", "semantic", "bm25"):
        r = api.retrieve_program_candidates(
            "artificial intelligence", lang="en", top_k=3, mode=mode,
        )
        assert r["total"] > 0, f"mode={mode} returned 0 results"
        assert all("canonical_program_id" in p for p in r["results"])


def test_retrieve_token_overlap_legacy_mode():
    r = api.retrieve_program_candidates(
        "artificial intelligence", lang="en", top_k=3, mode="token_overlap",
    )
    # Legacy mode: should still return some hits for an exact-keyword query
    assert r["total"] > 0


def test_mode_override_does_not_leak_env(monkeypatch):
    """A `mode=` override must not leave LASALLE_RANKER_MODE set after the call."""
    monkeypatch.delenv("LASALLE_RANKER_MODE", raising=False)
    api.retrieve_program_candidates("AI", lang="en", top_k=1, mode="lexical")
    assert "LASALLE_RANKER_MODE" not in os.environ


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_semantic_metadata_compatibility_check():
    """A sidecar with the wrong model name must be rejected, not crash."""
    # Build a fake meta dict that looks valid in shape but wrong on identity
    bad = {
        "sidecar_version": "1.0",
        "model_name": "totally-unknown-model",
        "vector_dim": search_mod.EXPECTED_VECTOR_DIM,
        "languages": {},
    }
    # Patch the cached loader: force a return of the bad meta and assert the
    # downstream loader treats it as missing.
    search_mod._semantic_meta.cache_clear()
    search_mod._semantic_matrix_for.cache_clear()

    real_meta_path = search_mod.store.wiki_dir() / "meta" / "embeddings_meta.json"
    backup = real_meta_path.read_text(encoding="utf-8") if real_meta_path.exists() else None
    try:
        import json as _json
        real_meta_path.write_text(_json.dumps(bad), encoding="utf-8")
        search_mod._semantic_meta.cache_clear()
        search_mod._semantic_matrix_for.cache_clear()
        assert search_mod._semantic_meta() is None
        assert search_mod._semantic_matrix_for("en") is None

        # Hybrid query should still work (degrades to lexical)
        r = api.retrieve_program_candidates("artificial intelligence", lang="en", top_k=3, mode="hybrid")
        assert r["total"] > 0
    finally:
        if backup is not None:
            real_meta_path.write_text(backup, encoding="utf-8")
        search_mod._semantic_meta.cache_clear()
        search_mod._semantic_matrix_for.cache_clear()


def test_missing_sidecar_falls_back(tmp_path, monkeypatch):
    """If the sidecar files don't exist, hybrid mode must still return results."""
    search_mod._semantic_meta.cache_clear()
    search_mod._semantic_matrix_for.cache_clear()
    real_meta_path = search_mod.store.wiki_dir() / "meta" / "embeddings_meta.json"
    backup_target = tmp_path / "embeddings_meta.json.bak"
    if real_meta_path.exists():
        backup_target.write_text(real_meta_path.read_text(encoding="utf-8"), encoding="utf-8")
        real_meta_path.unlink()
    try:
        search_mod._semantic_meta.cache_clear()
        search_mod._semantic_matrix_for.cache_clear()
        r = api.retrieve_program_candidates("cybersecurity", lang="en", top_k=3)
        assert r["total"] > 0
    finally:
        if backup_target.exists():
            real_meta_path.write_text(backup_target.read_text(encoding="utf-8"), encoding="utf-8")
        search_mod._semantic_meta.cache_clear()
        search_mod._semantic_matrix_for.cache_clear()


# ---------------------------------------------------------------------------
# Memory ceiling
# ---------------------------------------------------------------------------


def test_memory_under_limit_through_100_queries():
    """100 sequential hybrid queries should stay well under the t3.micro budget.

    We use ru_maxrss (peak resident set size). On macOS this is in bytes;
    on Linux it's in kilobytes. We cap at 700 MB on either platform — far
    above what we need but a safety net against runaway growth.
    """
    queries = [
        "artificial intelligence", "cybersecurity", "MBA", "animation",
        "data science", "robotics", "marketing", "philosophy",
        "Spanish business", "online master", "summer", "architecture",
        "user experience", "telecom", "biomedical", "health",
        "lean six sigma", "azure", "finance", "lean construction",
    ]
    for i in range(100):
        api.retrieve_program_candidates(queries[i % len(queries)], lang="en", top_k=5)

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Convert to bytes regardless of platform
    import sys
    if sys.platform == "darwin":
        rss_bytes = rss
    else:
        rss_bytes = rss * 1024
    rss_mb = rss_bytes / (1024 * 1024)
    # Generous cap; t3.micro has 1 GB total. We want to verify retrieval
    # itself doesn't balloon; the ~700 MB ceiling allows for the full
    # FastAPI + agno + Python stack still to fit beside us.
    assert rss_mb < 700, f"Process RSS {rss_mb:.0f} MB exceeded 700 MB budget"
