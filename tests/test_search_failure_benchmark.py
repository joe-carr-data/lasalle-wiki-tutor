"""Search-quality benchmark: queries that returned 0 hits in the
token-overlap baseline must now surface relevant programs in top-3.

These are the failure cases observed when the retrieval pilot was
run against the Phase 3 search. After the BM25 + synonyms upgrade
they should all hit. This benchmark protects against regressions.

Each case lists *expected substring matches* on the title or area —
we don't pin to a specific program slug so the test stays robust to
catalog churn (e.g. new AI programs added).
"""

from __future__ import annotations

import pytest

import catalog_wiki_api as api


@pytest.fixture(scope="session", autouse=True)
def _wiki_present():
    langs = api.list_languages()
    if not any(lang["program_count"] > 0 for lang in langs):
        pytest.skip("Wiki not rendered yet")


# Each tuple: (query, lang, expected_substring_in_top_3)
# Expected substring is matched (case-insensitive) against title OR area.
BENCHMARK = [
    # AI / ML / data
    ("machine learning", "en", ["artificial intelligence", "ai-data-science"]),
    ("deep learning", "en", ["artificial intelligence", "ai-data-science"]),
    ("data analysis", "en", ["data", "analytics"]),
    ("AI", "en", ["artificial intelligence", "ai-data-science"]),
    # Cybersecurity colloquial
    ("hacking", "en", ["cybersecurity"]),
    ("ethical hacking", "en", ["cybersecurity"]),
    # Entrepreneurship colloquial
    ("startup", "en", ["entrepreneur", "innovation", "business"]),
    # Game development
    ("game development", "en", ["videogame", "multimedia", "animation"]),
    ("video games", "en", ["videogame", "multimedia", "animation"]),
    # Programming
    ("programming", "en", ["programming", "computer", "software"]),
    # Spanish queries on EN catalog (mixed-language student behavior)
    ("ciberseguridad", "en", ["cybersecurity"]),
    ("inteligencia artificial", "en", ["artificial intelligence", "ai-data-science"]),
    # ES queries on ES catalog
    ("aprendizaje automático", "es", ["inteligencia artificial", "ai-data-science"]),
    ("ciberseguridad", "es", ["ciberseguridad", "cybersecurity"]),
    ("emprendimiento", "es", ["business-management", "innovaci"]),
]


@pytest.mark.parametrize("query,lang,expected_any", BENCHMARK)
def test_failure_query_top3(query: str, lang: str, expected_any: list[str]) -> None:
    """Each failure-case query should hit ≥ 1 truly-relevant program in top-3."""
    payload = api.search_programs(query, lang=lang, top_k=3)
    assert payload["total"] > 0, f"{query!r} returned 0 results"
    haystack = " ".join(
        f"{p.get('title','').lower()}|{p.get('area','').lower()}"
        for p in payload["results"]
    )
    matched = [needle for needle in expected_any if needle.lower() in haystack]
    assert matched, (
        f"{query!r}: none of {expected_any} hit top-3.\n"
        f"  results: {[p['title'] for p in payload['results']]}"
    )


def test_ai_query_prefers_substantive_program_over_summer():
    """Ranking sanity: the "AI" query should not be dominated by the
    1-week summer immersion — a real degree must be in top-3."""
    payload = api.search_programs("AI", lang="en", top_k=3)
    levels = [p.get("level") for p in payload["results"]]
    # Top-3 must contain at least one bachelor or master, not all summer/specialization.
    has_real_degree = any(lv in ("bachelor", "master", "doctorate") for lv in levels)
    assert has_real_degree, (
        f"top-3 levels: {levels} — AI query should surface a substantive program"
    )


def test_long_degree_intent_demotes_summer():
    """When the query implies long-form study, summer programs should not win."""
    payload = api.search_programs("artificial intelligence bachelor", lang="en", top_k=5)
    assert payload["total"] > 0
    top_level = payload["results"][0].get("level")
    assert top_level == "bachelor", (
        f"top result level is {top_level!r} — long-degree intent should prefer bachelors"
    )
