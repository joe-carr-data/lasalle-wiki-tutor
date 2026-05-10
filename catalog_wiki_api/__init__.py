"""catalog_wiki_api — read-only retrieval API for the LaSalle catalog wiki (v1).

Public surface: a small set of pure functions that read from the rendered
`wiki/` tree and `wiki/meta/*.jsonl` sidecars. No mutation, no LLM calls.

Identifiers: every program is keyed by `canonical_program_id`
(e.g. 'en/bachelor-animation-and-vfx'). Subjects use `canonical_subject_id`.

Errors: a single `CatalogApiError(code=..., message=...)` is raised, where
`code` is one of: 'not_found', 'invalid_filter', 'ambiguous_slug'.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from . import store
from .search import RankerMode, rank_programs
from .types import (
    Curriculum,
    CurriculumSemester,
    CurriculumSubject,
    CurriculumYear,
    Document,
    FacetCount,
    FacetSummary,
    GlossaryEntry,
    LanguageSummary,
    ModalityVariant,
    ProgramComparison,
    ProgramComparisonRow,
    ProgramDetail,
    ProgramListPayload,
    ProgramSearchPayload,
    ProgramSummary,
    SectionContent,
    SectionKey,
    SubjectDetail,
    SubjectSummary,
)

__version__ = "1.0.0"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CatalogApiError(Exception):
    """Raised on lookup / filter errors. Carries a machine-readable `code`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SUPPORTED_LANGS = ("en", "es")
SUPPORTED_LEVELS = (
    "bachelor", "master", "doctorate", "specialization",
    "online", "summer", "other",
)
SUPPORTED_MODALITIES = ("on-site", "online", "hybrid", "unknown")


def _check_lang(lang: str) -> None:
    if lang not in SUPPORTED_LANGS:
        raise CatalogApiError(
            "invalid_filter",
            f"Unsupported lang {lang!r}; expected one of {SUPPORTED_LANGS}",
        )


def _to_summary(p: dict[str, Any]) -> ProgramSummary:
    """Project a full frontmatter dict to the summary shape."""
    return {
        "canonical_program_id": p.get("canonical_program_id", ""),
        "slug": p.get("slug", ""),
        "title": p.get("title", ""),
        "level": p.get("level", ""),
        "area": p.get("area", ""),
        "modality": p.get("modality", []) or [],
        "duration": p.get("duration", ""),
        "ects": p.get("ects"),
        "languages_of_instruction": p.get("languages_of_instruction", []) or [],
        "location": p.get("location", ""),
        "schedule": p.get("schedule", ""),
        "start_date": p.get("start_date", ""),
        "tags": p.get("tags", []) or [],
        "lang": p.get("canonical_program_id", "/").split("/", 1)[0],
        "source_url": p.get("source_url", ""),
        "last_built_at": p.get("last_built_at", ""),
    }


def _to_subject_summary(s: dict[str, Any]) -> SubjectSummary:
    return {
        "canonical_subject_id": s.get("canonical_subject_id", ""),
        "slug": s.get("slug", ""),
        "title": s.get("title", ""),
        "parent_programs": s.get("parent_programs", []) or [],
        "year": s.get("year"),
        "semester": s.get("semester", ""),
        "type": s.get("type", ""),
        "ects": s.get("ects"),
        "lang": s.get("lang", ""),
    }


def _apply_filters(
    programs: list[dict[str, Any]],
    *,
    level: str | None,
    area: str | None,
    modality: str | None,
    language: str | None,
) -> list[dict[str, Any]]:
    out = programs
    if level is not None:
        if level not in SUPPORTED_LEVELS:
            raise CatalogApiError("invalid_filter", f"Unknown level {level!r}")
        out = [p for p in out if p.get("level") == level]
    if area is not None:
        out = [p for p in out if p.get("area") == area]
    if modality is not None:
        if modality not in SUPPORTED_MODALITIES:
            raise CatalogApiError("invalid_filter", f"Unknown modality {modality!r}")
        out = [p for p in out if modality in (p.get("modality") or [])]
    if language is not None:
        out = [p for p in out if language in (p.get("languages_of_instruction") or [])]
    return out


def _last_built_at_global() -> str:
    # Use the first program's timestamp as a proxy
    for lang in SUPPORTED_LANGS:
        for p in store.all_programs(lang):
            ts = p.get("last_built_at")
            if ts:
                return ts
    return ""


# ---------------------------------------------------------------------------
# Public endpoints — discovery & facets
# ---------------------------------------------------------------------------


def list_programs(
    level: str | None = None,
    area: str | None = None,
    modality: str | None = None,
    language: str | None = None,
    lang: str = "en",
    offset: int = 0,
    limit: int = 50,
) -> ProgramListPayload:
    """List programs with optional filters."""
    _check_lang(lang)
    programs = store.all_programs(lang)
    filtered = _apply_filters(
        programs,
        level=level, area=area, modality=modality, language=language,
    )
    filtered.sort(key=lambda p: p.get("title", ""))
    page = filtered[offset : offset + limit]
    return {
        "programs": [_to_summary(p) for p in page],
        "total": len(filtered),
        "applied_filters": {
            "level": level, "area": area, "modality": modality, "language": language,
        },
        "offset": offset,
        "limit": limit,
        "lang": lang,
    }


def search_programs(
    query: str,
    filters: dict[str, str | None] | None = None,
    top_k: int = 10,
    lang: str = "en",
    *,
    mode: str | None = None,
) -> ProgramSearchPayload:
    """Hybrid (BM25 + cosine) search over the program corpus, with filters.

    This is the primary student-facing retrieval function. The default
    ranker is hybrid; ``LASALLE_RANKER_MODE`` env var sets the process
    default; the per-call ``mode=`` argument overrides it without
    mutating any global state.

    Args:
        query: Free-text query.
        filters: Optional dict {level, area, modality, language}.
        top_k: Max results to return.
        lang: ``"en"`` or ``"es"``.
        mode: Per-call ranker override — ``"hybrid"`` (default),
            ``"lexical"`` / ``"bm25"``, ``"semantic"``, or
            ``"token_overlap"`` (legacy). ``None`` uses the process
            default. Request-scoped: safe under concurrent calls.
    """
    _check_lang(lang)
    filters = filters or {}
    programs = store.all_programs(lang)
    pool = _apply_filters(
        programs,
        level=filters.get("level"),
        area=filters.get("area"),
        modality=filters.get("modality"),
        language=filters.get("language"),
    )
    ranked = rank_programs(query, pool, top_k=top_k, mode=mode)
    return {
        "query": query,
        "results": [_to_summary(p) for _, p in ranked],
        "total": len(ranked),
        "applied_filters": dict(filters),
        "lang": lang,
    }


def retrieve_program_candidates(
    query: str,
    *,
    lang: str = "en",
    filters: dict[str, str | None] | None = None,
    top_k: int = 10,
    mode: str | None = None,
) -> ProgramSearchPayload:
    """Agent-facing retrieval entrypoint (Phase 4).

    Thin alias for :func:`search_programs` with a per-call ``mode``
    override. The Phase 4 agno tool calls this and forwards the typed
    payload to the LLM unchanged. Request-scoped — does not mutate any
    process-global state, so concurrent SSE queries cannot collide.

    Args:
        query:    natural-language student query (e.g. "machine learning bachelor").
        lang:     "en" or "es".
        filters:  optional dict {level, area, modality, language}.
        top_k:    max candidates to return.
        mode:     override the ranker mode for this call only:
                  "hybrid" (default), "lexical", "semantic",
                  "token_overlap" (legacy). When None, uses the
                  ``LASALLE_RANKER_MODE`` env var (also defaulting to
                  "hybrid").
    """
    return search_programs(query, filters=filters, top_k=top_k, lang=lang, mode=mode)


_AREA_LABELS = {
    "ai-data-science": "AI & Data Science",
    "architecture": "Architecture & Building",
    "business-management": "Business & Management",
    "computer-science": "Computer Science",
    "cybersecurity": "Cybersecurity",
    "animation-digital-arts": "Animation & Digital Arts",
    "telecom-electronics": "Telecommunications & Electronics",
    "health-engineering": "Health Engineering",
    "philosophy-humanities": "Philosophy & Humanities",
    "project-management": "Project Management",
    "other": "Other",
}

_LEVEL_LABELS = {
    "bachelor": "Bachelor's degrees",
    "master": "Master's degrees",
    "doctorate": "Doctorates",
    "specialization": "Specialization courses",
    "online": "Online courses",
    "summer": "Summer school",
    "other": "Other programs",
}

_LANGUAGE_LABELS = {"en": "English", "es": "Español"}


def get_index_facets(lang: str = "en") -> FacetSummary:
    """Return area/level/modality/language counts for the given catalog language."""
    _check_lang(lang)
    programs = store.all_programs(lang)
    areas: Counter[str] = Counter()
    levels: Counter[str] = Counter()
    modalities: Counter[str] = Counter()
    instr_langs: Counter[str] = Counter()
    for p in programs:
        if p.get("area"):
            areas[p["area"]] += 1
        if p.get("level"):
            levels[p["level"]] += 1
        for m in p.get("modality") or []:
            modalities[m] += 1
        for il in p.get("languages_of_instruction") or []:
            instr_langs[il] += 1

    def _facets(c: Counter[str], labels: dict[str, str]) -> list[FacetCount]:
        return [
            {"key": k, "label": labels.get(k, k), "count": v}
            for k, v in sorted(c.items(), key=lambda kv: -kv[1])
        ]

    return {
        "lang": lang,
        "areas": _facets(areas, _AREA_LABELS),
        "levels": _facets(levels, _LEVEL_LABELS),
        "modalities": _facets(modalities, {}),
        "languages_of_instruction": _facets(instr_langs, {}),
        "last_built_at": _last_built_at_global(),
    }


def list_languages() -> list[LanguageSummary]:
    return [
        {
            "code": lang,
            "name": _LANGUAGE_LABELS.get(lang, lang),
            "program_count": len(store.all_programs(lang)),
        }
        for lang in SUPPORTED_LANGS
    ]


# ---------------------------------------------------------------------------
# Public endpoints — detail retrieval
# ---------------------------------------------------------------------------


def _read_section(canonical_program_id: str, section: str) -> tuple[str, str]:
    """Return (title, body_markdown) for a program's section file."""
    path = store.program_section_file(canonical_program_id, section)
    if not path.exists():
        return "", ""
    fm, body = store.read_markdown(path)
    title = fm.get("title", "")
    # Strip the heading the renderer added ("# {title}\n## Section\n...")
    return title, body.strip()


def get_program(program_id: str, include_sections: bool = False) -> ProgramDetail:
    """Return the full program detail (frontmatter + overview + optional sections)."""
    rec = store.get_program_record(program_id)
    if rec is None:
        raise CatalogApiError("not_found", f"Program {program_id!r} not found")

    folder = store.program_folder(program_id)
    _, readme_body = store.read_markdown(folder / "README.md")
    # Extract the Overview section markdown (between "## Overview" and the next "## ")
    overview_md = ""
    if "## Overview" in readme_body:
        chunk = readme_body.split("## Overview", 1)[1]
        if "\n## " in chunk:
            chunk = chunk.split("\n## ", 1)[0]
        overview_md = chunk.strip()

    detail: ProgramDetail = dict(rec)  # type: ignore[assignment]
    detail["overview_md"] = overview_md
    detail["modality_variants"] = []  # not surfaced in v1; reserved
    if include_sections:
        sections: dict[str, str] = {}
        for s in ("goals", "requirements", "curriculum", "careers", "methodology", "faculty"):
            _, body = _read_section(program_id, s)
            if body:
                sections[s] = body
        detail["sections"] = sections
    return detail


def get_program_section(program_id: str, section: SectionKey) -> SectionContent:
    """Return one section of a program (goals/requirements/curriculum/careers/etc)."""
    rec = store.get_program_record(program_id)
    if rec is None:
        raise CatalogApiError("not_found", f"Program {program_id!r} not found")
    valid = {"goals", "requirements", "curriculum", "careers", "methodology", "faculty"}
    if section not in valid:
        raise CatalogApiError(
            "invalid_filter",
            f"Unknown section {section!r}; expected one of {sorted(valid)}",
        )
    title, body = _read_section(program_id, section)
    if not body:
        raise CatalogApiError(
            "not_found",
            f"Section {section!r} not available for {program_id}",
        )
    lang = program_id.split("/", 1)[0]
    return {
        "canonical_program_id": program_id,
        "section": section,
        "title": title or rec.get("title", ""),
        "body_markdown": body,
        "lang": lang,
        "source_url": rec.get("source_url", ""),
        "last_built_at": rec.get("last_built_at", ""),
    }


def get_curriculum(program_id: str) -> Curriculum:
    """Return the program's structured curriculum (year → semester → subjects).

    Parses the rendered curriculum.md (markdown bullet structure) and
    re-inflates it into a structured payload.
    """
    rec = store.get_program_record(program_id)
    if rec is None:
        raise CatalogApiError("not_found", f"Program {program_id!r} not found")

    path = store.program_section_file(program_id, "curriculum")
    if not path.exists():
        raise CatalogApiError("not_found", f"No curriculum for {program_id!r}")

    fm, body = store.read_markdown(path)
    years: list[CurriculumYear] = []
    current_year: CurriculumYear | None = None
    current_sem: CurriculumSemester | None = None
    import re as _re
    link_re = _re.compile(r"^\-\s*\[([^\]]+)\]\(([^)]+)\)(?:\s*—\s*(\d+)\s*ECTS)?\s*$")
    plain_re = _re.compile(r"^\-\s*(.+?)(?:\s*—\s*(\d+)\s*ECTS)?\s*$")

    for line in body.splitlines():
        line = line.rstrip()
        if line.startswith("### "):
            if current_year is not None:
                years.append(current_year)
            current_year = {"year": line[4:].strip(), "sections": []}
            current_sem = None
        elif line.startswith("#### "):
            current_sem = {"semester": line[5:].strip(), "subjects": []}
            if current_year is not None:
                current_year["sections"].append(current_sem)
        elif line.startswith("- "):
            if current_year is None:
                current_year = {"year": "Unknown", "sections": []}
            if current_sem is None:
                current_sem = {"semester": "All semesters", "subjects": []}
                current_year["sections"].append(current_sem)
            m = link_re.match(line)
            if m:
                title, target, ects = m.group(1).strip(), m.group(2).strip(), m.group(3)
                # Convert relative wiki link to canonical_subject_id if it points to subjects/
                subj_id = None
                if "subjects/" in target:
                    slug = target.rstrip("/").split("/")[-1]
                    if slug.endswith(".md"):
                        slug = slug[:-3]
                    subj_id = f"{program_id.split('/', 1)[0]}/{slug}"
                current_sem["subjects"].append({
                    "canonical_subject_id": subj_id,
                    "title": title,
                    "ects": int(ects) if ects else None,
                    "url": target,
                })
            else:
                m2 = plain_re.match(line)
                if m2:
                    current_sem["subjects"].append({
                        "canonical_subject_id": None,
                        "title": m2.group(1).strip(),
                        "ects": int(m2.group(2)) if m2.group(2) else None,
                        "url": "",
                    })
    if current_year is not None:
        years.append(current_year)

    return {
        "canonical_program_id": program_id,
        "title": rec.get("title", ""),
        "lang": program_id.split("/", 1)[0],
        "years": years,
        "source_url": fm.get("source_url", ""),
        "last_built_at": fm.get("last_built_at", rec.get("last_built_at", "")),
    }


def get_subject(subject_id: str) -> SubjectDetail:
    rec = store.get_subject_record(subject_id)
    if rec is None:
        raise CatalogApiError("not_found", f"Subject {subject_id!r} not found")
    path = store.subject_file(subject_id)
    fm, body = store.read_markdown(path)
    detail: SubjectDetail = dict(rec)  # type: ignore[assignment]

    # Pull the per-section bodies out of the rendered markdown.
    sections = {}
    current = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower().replace(" ", "_")
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    for k, lines in sections.items():
        text = "\n".join(lines).strip()
        # Map ##-section headings back to TypedDict keys
        key_map = {
            "description": "description",
            "prerequisites": "prerequisites",
            "objectives": "objectives",
            "contents": "contents",
            "methodology": "methodology",
            "evaluation": "evaluation",
            "grading_criteria": "grading_criteria",
            "bibliography": "bibliography",
        }
        if k in key_map and text:
            detail[key_map[k]] = text  # type: ignore[index]
    return detail


def list_subjects_for_program(program_id: str) -> list[SubjectSummary]:
    rec = store.get_program_record(program_id)
    if rec is None:
        raise CatalogApiError("not_found", f"Program {program_id!r} not found")
    lang = program_id.split("/", 1)[0]
    out: list[SubjectSummary] = []
    for s in store.all_subjects(lang):
        if program_id in (s.get("parent_programs") or []):
            out.append(_to_subject_summary(s))
    out.sort(key=lambda s: (s.get("year") or 99, s.get("semester") or "", s.get("title") or ""))
    return out


# ---------------------------------------------------------------------------
# Public endpoints — resolvers & relations
# ---------------------------------------------------------------------------


def get_program_by_slug(slug: str, lang: str = "en") -> ProgramSummary | None:
    _check_lang(lang)
    pid = f"{lang}/{slug}"
    rec = store.get_program_record(pid)
    return _to_summary(rec) if rec else None


def get_equivalent(program_id: str, target_lang: str) -> ProgramSummary | None:
    """Return the cross-language equivalent if pairing_confidence ≥ 0.75."""
    _check_lang(target_lang)
    rec = store.get_program_record(program_id)
    if rec is None:
        raise CatalogApiError("not_found", f"Program {program_id!r} not found")
    eq_id = rec.get("equivalent_program_id")
    if not eq_id or not eq_id.startswith(f"{target_lang}/"):
        return None
    confidence = rec.get("pairing_confidence", 0)
    if confidence < 0.75:
        return None
    eq_rec = store.get_program_record(eq_id)
    return _to_summary(eq_rec) if eq_rec else None


def get_related_programs(program_id: str, top_k: int = 5) -> list[ProgramSummary]:
    rec = store.get_program_record(program_id)
    if rec is None:
        raise CatalogApiError("not_found", f"Program {program_id!r} not found")
    lang = program_id.split("/", 1)[0]
    out: list[ProgramSummary] = []
    related_slugs = rec.get("related_programs") or []
    for slug in related_slugs[:top_k]:
        rp = store.get_program_record(f"{lang}/{slug}")
        if rp:
            out.append(_to_summary(rp))
    return out


def compare_programs(program_ids: list[str]) -> ProgramComparison:
    """Return normalized comparable fields for N programs."""
    if not program_ids:
        raise CatalogApiError("invalid_filter", "program_ids is empty")
    rows: list[ProgramComparisonRow] = []
    lang = program_ids[0].split("/", 1)[0] if "/" in program_ids[0] else "en"
    for pid in program_ids:
        rec = store.get_program_record(pid)
        if rec is None:
            raise CatalogApiError("not_found", f"Program {pid!r} not found")
        rows.append({
            "canonical_program_id": pid,
            "title": rec.get("title", ""),
            "level": rec.get("level", ""),
            "area": rec.get("area", ""),
            "modality": rec.get("modality", []) or [],
            "duration": rec.get("duration", ""),
            "ects": rec.get("ects"),
            "languages_of_instruction": rec.get("languages_of_instruction", []) or [],
            "schedule": rec.get("schedule", ""),
            "location": rec.get("location", ""),
            "start_date": rec.get("start_date", ""),
            "subject_count": rec.get("subject_count", 0),
        })
    return {
        "program_ids": program_ids,
        "rows": rows,
        "lang": lang,
        "last_built_at": _last_built_at_global(),
    }


# ---------------------------------------------------------------------------
# Public endpoints — meta / FAQ
# ---------------------------------------------------------------------------


def get_faq(lang: str = "en") -> Document:
    _check_lang(lang)
    path = store.wiki_dir() / lang / "faq.md"
    if not path.exists():
        raise CatalogApiError("not_found", f"No FAQ for lang {lang!r}")
    fm, body = store.read_markdown(path)
    return {
        "title": "FAQ" if lang == "en" else "Preguntas frecuentes",
        "body_markdown": body.strip(),
        "lang": lang,
        "source_path": str(path.relative_to(store.wiki_dir())),
        "last_built_at": fm.get("last_built_at", _last_built_at_global()),
    }


def get_glossary_entry(term: str, lang: str = "en") -> GlossaryEntry | None:
    """Return one glossary entry (h2 section) by case-insensitive term match."""
    _check_lang(lang)
    path = store.wiki_dir() / lang / "glossary.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    # Glossary uses `## Term` headings
    target = term.strip().lower()
    sections: list[tuple[str, list[str]]] = []
    current_term: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current_term is not None:
                sections.append((current_term, buf))
            current_term = line[3:].strip()
            buf = []
        elif current_term is not None:
            buf.append(line)
    if current_term is not None:
        sections.append((current_term, buf))
    for term_key, body in sections:
        if term_key.lower() == target:
            return {
                "term": term_key,
                "body_markdown": "\n".join(body).strip(),
                "lang": lang,
            }
    return None


# Re-export error type for callers
__all__ = [
    "__version__",
    "CatalogApiError",
    "list_programs",
    "search_programs",
    "retrieve_program_candidates",
    "get_index_facets",
    "list_languages",
    "get_program",
    "get_program_section",
    "get_curriculum",
    "get_subject",
    "list_subjects_for_program",
    "get_program_by_slug",
    "get_equivalent",
    "get_related_programs",
    "compare_programs",
    "get_faq",
    "get_glossary_entry",
]
