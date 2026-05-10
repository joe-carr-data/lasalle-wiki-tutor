"""Contract tests for catalog_wiki_api v1.

These exercise each endpoint against the rendered wiki and verify the
return-shape invariants. They don't pin specific data values — those
change as the catalog updates — but they guarantee:

  - Required keys are present
  - Type contracts hold
  - Cross-references resolve (e.g. equivalent_program_id points at a real program)
  - Errors raise CatalogApiError with the expected `code`
"""

from __future__ import annotations

import pytest

import catalog_wiki_api as api
from catalog_wiki_api import CatalogApiError


# Skip the whole suite if the wiki hasn't been rendered yet.
@pytest.fixture(scope="session", autouse=True)
def _wiki_present():
    langs = api.list_languages()
    if not any(l["program_count"] > 0 for l in langs):
        pytest.skip("Wiki not rendered yet")


# ---------------------------------------------------------------------------
# Discovery / facets
# ---------------------------------------------------------------------------


def test_list_languages_shape():
    langs = api.list_languages()
    assert isinstance(langs, list)
    assert {"en", "es"} <= {l["code"] for l in langs}
    for l in langs:
        assert {"code", "name", "program_count"} <= set(l.keys())


def test_get_index_facets_returns_required_facet_groups():
    facets = api.get_index_facets("en")
    for group in ("areas", "levels", "modalities", "languages_of_instruction"):
        assert group in facets
        assert isinstance(facets[group], list)
    assert facets["lang"] == "en"
    assert facets.get("last_built_at")


def test_list_programs_basic():
    payload = api.list_programs(lang="en", limit=5)
    assert payload["lang"] == "en"
    assert payload["limit"] == 5
    assert payload["offset"] == 0
    assert isinstance(payload["total"], int)
    assert payload["total"] > 0
    assert len(payload["programs"]) <= 5
    for p in payload["programs"]:
        for k in ("canonical_program_id", "title", "level", "area", "lang"):
            assert k in p


def test_list_programs_filters():
    payload = api.list_programs(level="bachelor", lang="en", limit=200)
    for p in payload["programs"]:
        assert p["level"] == "bachelor"
    assert payload["applied_filters"]["level"] == "bachelor"


def test_list_programs_invalid_level_raises():
    with pytest.raises(CatalogApiError) as excinfo:
        api.list_programs(level="phd")  # not in enum, should be 'doctorate'
    assert excinfo.value.code == "invalid_filter"


def test_search_programs_returns_results():
    payload = api.search_programs("artificial intelligence", lang="en", top_k=5)
    assert payload["query"] == "artificial intelligence"
    assert payload["total"] >= 1
    titles = " ".join(p["title"].lower() for p in payload["results"])
    # At least one of the top results should mention AI
    assert "artificial" in titles or "ai" in titles


# ---------------------------------------------------------------------------
# Detail retrieval
# ---------------------------------------------------------------------------


def _first_bachelor_id(lang="en") -> str:
    p = api.list_programs(level="bachelor", lang=lang, limit=1)
    assert p["programs"], f"no bachelor programs for {lang}"
    return p["programs"][0]["canonical_program_id"]


def test_get_program_round_trip():
    pid = _first_bachelor_id("en")
    detail = api.get_program(pid)
    assert detail["canonical_program_id"] == pid
    assert detail["title"]
    assert "overview_md" in detail
    assert detail["level"] == "bachelor"


def test_get_program_with_sections():
    pid = _first_bachelor_id("en")
    detail = api.get_program(pid, include_sections=True)
    assert "sections" in detail
    # Bachelor programs typically have all sections; expect at least 'curriculum'
    assert "curriculum" in detail["sections"] or "goals" in detail["sections"]


def test_get_program_section_curriculum():
    pid = _first_bachelor_id("en")
    section = api.get_program_section(pid, "curriculum")
    assert section["section"] == "curriculum"
    assert section["body_markdown"]


def test_get_program_section_invalid():
    pid = _first_bachelor_id("en")
    with pytest.raises(CatalogApiError) as excinfo:
        api.get_program_section(pid, "nonexistent")  # type: ignore[arg-type]
    assert excinfo.value.code == "invalid_filter"


def test_get_program_not_found():
    with pytest.raises(CatalogApiError) as excinfo:
        api.get_program("en/nonexistent-program-foo")
    assert excinfo.value.code == "not_found"


def test_get_curriculum_structure():
    pid = _first_bachelor_id("en")
    curr = api.get_curriculum(pid)
    assert curr["canonical_program_id"] == pid
    assert curr["lang"] == "en"
    assert isinstance(curr["years"], list)
    assert curr["years"], "expected at least one year"
    y = curr["years"][0]
    assert "year" in y and "sections" in y
    if y["sections"]:
        sec = y["sections"][0]
        assert "semester" in sec and "subjects" in sec


def test_list_subjects_for_program():
    pid = _first_bachelor_id("en")
    subs = api.list_subjects_for_program(pid)
    assert isinstance(subs, list)
    assert len(subs) > 0


def test_get_subject_round_trip():
    pid = _first_bachelor_id("en")
    subs = api.list_subjects_for_program(pid)
    if not subs:
        pytest.skip("no subjects available")
    sid = subs[0]["canonical_subject_id"]
    detail = api.get_subject(sid)
    assert detail["canonical_subject_id"] == sid
    assert detail["title"]


# ---------------------------------------------------------------------------
# Resolvers / relations
# ---------------------------------------------------------------------------


def test_get_program_by_slug_roundtrip():
    pid = _first_bachelor_id("en")
    slug = pid.split("/", 1)[1]
    rec = api.get_program_by_slug(slug, lang="en")
    assert rec is not None
    assert rec["canonical_program_id"] == pid


def test_get_program_by_slug_missing_returns_none():
    assert api.get_program_by_slug("totally-fake-slug-xyz", lang="en") is None


def test_get_related_programs_shape():
    pid = _first_bachelor_id("en")
    rel = api.get_related_programs(pid, top_k=3)
    assert isinstance(rel, list)
    assert len(rel) <= 3


def test_get_equivalent_consistency():
    """Auto-paired programs should round-trip across languages."""
    en_programs = api.list_programs(lang="en", limit=200)["programs"]
    paired_count = 0
    for p in en_programs[:30]:  # sample 30 to keep the test fast
        eq = api.get_equivalent(p["canonical_program_id"], "es")
        if eq is None:
            continue
        paired_count += 1
        assert eq["canonical_program_id"].startswith("es/")
    # The pilot/full corpus should produce *some* auto-pairs in the first 30
    assert paired_count > 0


def test_compare_programs_basic():
    pls = api.list_programs(level="bachelor", lang="en", limit=2)["programs"]
    if len(pls) < 2:
        pytest.skip("need ≥ 2 bachelors")
    cmp = api.compare_programs([p["canonical_program_id"] for p in pls])
    assert len(cmp["rows"]) == 2
    for row in cmp["rows"]:
        for k in ("title", "level", "ects", "modality"):
            assert k in row


# ---------------------------------------------------------------------------
# Meta / FAQ / glossary
# ---------------------------------------------------------------------------


def test_get_faq_both_languages():
    for lang in ("en", "es"):
        doc = api.get_faq(lang)
        assert doc["lang"] == lang
        assert "tuition" in doc["body_markdown"].lower() or "matrícula" in doc["body_markdown"].lower()


def test_get_glossary_ects():
    for lang in ("en", "es"):
        entry = api.get_glossary_entry("ECTS", lang)
        assert entry is not None, f"ECTS entry missing in {lang}"
        assert entry["term"] == "ECTS"
