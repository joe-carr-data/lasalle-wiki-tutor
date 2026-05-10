"""Stable v1 payload types for the catalog wiki API.

Plain TypedDicts — JSON-serializable, easy to evolve. Each public payload
includes `source_url`, `last_built_at`, and `lang` for traceability.
"""

from __future__ import annotations

from typing import Literal, TypedDict


# ---------------------------------------------------------------------------
# Lightweight summaries (used in lists)
# ---------------------------------------------------------------------------


class ProgramSummary(TypedDict, total=False):
    canonical_program_id: str
    slug: str
    title: str
    level: str
    area: str
    modality: list[str]
    duration: str
    ects: int | None
    languages_of_instruction: list[str]
    location: str
    schedule: str
    start_date: str
    tags: list[str]
    lang: str
    source_url: str
    last_built_at: str


class SubjectSummary(TypedDict, total=False):
    canonical_subject_id: str
    slug: str
    title: str
    parent_programs: list[str]
    year: int | None
    semester: str
    type: str
    ects: int | None
    lang: str


class LanguageSummary(TypedDict):
    code: str       # 'en' or 'es'
    name: str       # 'English' or 'Español'
    program_count: int


# ---------------------------------------------------------------------------
# Detail payloads
# ---------------------------------------------------------------------------


SectionKey = Literal[
    "goals", "requirements", "curriculum", "careers", "methodology", "faculty"
]


class CurriculumSubject(TypedDict, total=False):
    canonical_subject_id: str | None
    title: str
    ects: int | None
    url: str  # raw URL (relative path on source site, useful for debugging)


class CurriculumSemester(TypedDict):
    semester: str
    subjects: list[CurriculumSubject]


class CurriculumYear(TypedDict):
    year: str
    sections: list[CurriculumSemester]


class Curriculum(TypedDict, total=False):
    canonical_program_id: str
    title: str
    lang: str
    years: list[CurriculumYear]
    source_url: str
    last_built_at: str


class ModalityVariant(TypedDict, total=False):
    modality: str
    duration: str
    language: str
    places: str
    ects: str
    start_date: str
    schedule: str
    location: str


class ProgramDetail(TypedDict, total=False):
    canonical_program_id: str
    slug: str
    title: str
    level: str
    area: str
    official: bool
    tags: list[str]
    modality: list[str]
    duration: str
    ects: int | None
    languages_of_instruction: list[str]
    schedule: str
    location: str
    start_date: str
    tuition_status: str
    admissions_contact: str
    official_name: str
    degree_issuer: str
    subject_count: int
    related_programs: list[str]
    equivalent_program_id: str | None
    pairing_confidence: float | None
    overview_md: str
    sections: dict[str, str]   # SectionKey → markdown body, only when include_sections=True
    modality_variants: list[ModalityVariant]
    lang: str
    source_url: str
    last_built_at: str


class SectionContent(TypedDict, total=False):
    canonical_program_id: str
    section: str
    title: str
    body_markdown: str
    lang: str
    source_url: str
    last_built_at: str


class SubjectDetail(TypedDict, total=False):
    canonical_subject_id: str
    slug: str
    title: str
    parent_programs: list[str]
    year: int | None
    semester: str
    type: str
    ects: int | None
    description: str
    prerequisites: str
    objectives: str
    contents: str
    methodology: str
    evaluation: str
    grading_criteria: str
    bibliography: str
    additional_material: str
    professors: list[str]
    lang: str
    source_url: str
    last_built_at: str


# ---------------------------------------------------------------------------
# Facet / list payloads
# ---------------------------------------------------------------------------


class FacetCount(TypedDict):
    key: str
    label: str
    count: int


class FacetSummary(TypedDict):
    lang: str
    areas: list[FacetCount]
    levels: list[FacetCount]
    modalities: list[FacetCount]
    languages_of_instruction: list[FacetCount]
    last_built_at: str


class ProgramListPayload(TypedDict):
    programs: list[ProgramSummary]
    total: int
    applied_filters: dict[str, str | list[str] | None]
    offset: int
    limit: int
    lang: str


class ProgramSearchPayload(TypedDict):
    query: str
    results: list[ProgramSummary]
    total: int
    applied_filters: dict[str, str | list[str] | None]
    lang: str


class ProgramComparisonRow(TypedDict, total=False):
    canonical_program_id: str
    title: str
    level: str
    area: str
    modality: list[str]
    duration: str
    ects: int | None
    languages_of_instruction: list[str]
    schedule: str
    location: str
    start_date: str
    subject_count: int


class ProgramComparison(TypedDict):
    program_ids: list[str]
    rows: list[ProgramComparisonRow]
    lang: str
    last_built_at: str


# ---------------------------------------------------------------------------
# Generic document / glossary
# ---------------------------------------------------------------------------


class Document(TypedDict):
    title: str
    body_markdown: str
    lang: str
    source_path: str
    last_built_at: str


class GlossaryEntry(TypedDict):
    term: str
    body_markdown: str
    lang: str
