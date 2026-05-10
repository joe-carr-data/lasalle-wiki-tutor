"""Persona simulation tests — answer student questions using ONLY API calls.

Each test scripts one of the six student personas from the wiki plan and
verifies that:
  - the answer uses ≤ 5 API calls
  - meaningful information is retrieved (we assert presence, not exact text)

Tests count API calls by wrapping the public functions with a counter.
"""

from __future__ import annotations

import pytest

import catalog_wiki_api as api


@pytest.fixture
def call_counter(monkeypatch):
    """Return a dict {name: count} that increments on every API call."""
    counter: dict[str, int] = {}

    def wrap(name, fn):
        def wrapped(*args, **kwargs):
            counter[name] = counter.get(name, 0) + 1
            counter["_total"] = counter.get("_total", 0) + 1
            return fn(*args, **kwargs)
        return wrapped

    public = [
        "list_programs", "search_programs", "get_index_facets", "list_languages",
        "get_program", "get_program_section", "get_curriculum", "get_subject",
        "list_subjects_for_program", "get_program_by_slug", "get_equivalent",
        "get_related_programs", "compare_programs", "get_faq", "get_glossary_entry",
    ]
    for name in public:
        original = getattr(api, name)
        monkeypatch.setattr(api, name, wrap(name, original))
    return counter


@pytest.fixture(scope="session", autouse=True)
def _wiki_present():
    langs = api.list_languages()
    if not any(l["program_count"] > 0 for l in langs):
        pytest.skip("Wiki not rendered yet")


# ---------------------------------------------------------------------------
# Persona 1: Explorer — "I'm into tech, what programs do you have?"
# Expected path: facets → list_programs filtered by area
# ---------------------------------------------------------------------------


def test_persona_explorer_ai(call_counter):
    facets = api.get_index_facets("en")
    ai_areas = [f for f in facets["areas"] if "ai" in f["key"]]
    assert ai_areas, "AI area should appear in facets"
    payload = api.list_programs(area=ai_areas[0]["key"], lang="en", limit=20)
    assert payload["total"] > 0
    assert call_counter["_total"] <= 5


# ---------------------------------------------------------------------------
# Persona 2: Comparison shopper — "Compare two AI bachelors"
# Expected path: search → compare_programs
# ---------------------------------------------------------------------------


def test_persona_comparison_shopper(call_counter):
    search = api.search_programs("artificial intelligence", lang="en", top_k=4)
    bachelors = [r for r in search["results"] if r["level"] == "bachelor"][:2]
    if len(bachelors) < 2:
        pytest.skip("not enough AI bachelors to compare")
    comparison = api.compare_programs([b["canonical_program_id"] for b in bachelors])
    assert len(comparison["rows"]) == 2
    assert call_counter["_total"] <= 5


# ---------------------------------------------------------------------------
# Persona 3: Practical decider — "Is the AI bachelor in English? How many ECTS?"
# Expected path: get_program_by_slug → done (frontmatter has it)
# ---------------------------------------------------------------------------


def test_persona_practical_decider(call_counter):
    bachelors = api.list_programs(level="bachelor", area="ai-data-science", lang="en")["programs"]
    if not bachelors:
        pytest.skip("no AI bachelor")
    pid = bachelors[0]["canonical_program_id"]
    detail = api.get_program(pid)
    assert "languages_of_instruction" in detail
    assert "ects" in detail
    assert call_counter["_total"] <= 5


# ---------------------------------------------------------------------------
# Persona 4: Career-oriented — "Jobs after animation degree?"
# Expected path: search → get_program_section(careers)
# ---------------------------------------------------------------------------


def test_persona_career_oriented(call_counter):
    search = api.search_programs("animation", lang="en", top_k=3)
    if not search["results"]:
        pytest.skip("no animation programs")
    pid = search["results"][0]["canonical_program_id"]
    careers = api.get_program_section(pid, "careers")
    assert careers["body_markdown"]
    assert call_counter["_total"] <= 5


# ---------------------------------------------------------------------------
# Persona 5: Curriculum detective — "What courses in year 2 of CS?"
# Expected path: search/list → get_curriculum → get_subject (optional)
# ---------------------------------------------------------------------------


def test_persona_curriculum_detective(call_counter):
    search = api.search_programs("computer engineering", lang="en", top_k=3)
    bachelors = [r for r in search["results"] if r["level"] == "bachelor"]
    if not bachelors:
        pytest.skip("no CS bachelor")
    curr = api.get_curriculum(bachelors[0]["canonical_program_id"])
    # Verify there's structured curriculum data — at least one year with subjects.
    has_subjects = any(
        sec.get("subjects") for y in curr["years"] for sec in y.get("sections", [])
    )
    assert has_subjects, "curriculum should list subjects"
    assert call_counter["_total"] <= 5


# ---------------------------------------------------------------------------
# Persona 6: Specialization seeker — "Short summer programs?"
# Expected path: list_programs filtered by level
# ---------------------------------------------------------------------------


def test_persona_specialization_seeker(call_counter):
    summer = api.list_programs(level="summer", lang="en", limit=20)
    online = api.list_programs(level="online", lang="en", limit=20)
    spec = api.list_programs(level="specialization", lang="en", limit=20)
    assert summer["total"] + online["total"] + spec["total"] > 0
    assert call_counter["_total"] <= 5


# ---------------------------------------------------------------------------
# Pricing-gap question
# ---------------------------------------------------------------------------


def test_pricing_question_routes_to_faq(call_counter):
    faq = api.get_faq("en")
    body = faq["body_markdown"].lower()
    assert "admissions" in body or "tuition" in body or "pricing" in body
    assert call_counter["_total"] <= 5
