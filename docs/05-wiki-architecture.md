# 05 — Wiki architecture (Phase 3)

Last updated: 2026-05-10

This document describes the agent-navigable wiki built from the raw HTML
corpus, plus the `catalog_wiki_api` v1 package that exposes it to Phase 4
agents. It supersedes `04-knowledge-base-map.md` for "what's in the wiki
and how to navigate it"; that doc is still useful as the corpus inventory.

## Goal

Convert 7,099 raw HTML pages (357 programs × ~7 subpages + 4,606 subjects)
into a structured wiki an LLM agent can navigate by file reads in ≤ 5 hops
to answer any common student question. Two principles drive every choice:

1. **High searchability** — small, predictable, well-indexed files.
2. **Amazing student experience** — content organized around real student
   questions, not the source HTML structure.

## On-disk layout

```
wiki/
├── README.md                            # entry point
├── faq.md                               # student-question pointers
├── glossary.md                          # ECTS, modality, official, …
├── meta/
│   ├── catalog.jsonl                    # one line / program — frontmatter dump
│   ├── subjects.jsonl                   # one line / subject
│   ├── pairings.jsonl                   # EN↔ES pair candidates with confidence
│   ├── fallback_report.md               # selector-drift triage
│   └── stats.md                         # corpus health
├── en/
│   ├── README.md
│   ├── INDEX.md                         # all programs + format facets
│   ├── faq.md
│   ├── glossary.md
│   ├── by-area/                         # 11 files (ai-data-science.md, etc.)
│   ├── by-level/                        # 7 files (bachelors.md, etc.)
│   ├── programs/{slug}/
│   │   ├── README.md                    # overview + frontmatter (THE entry)
│   │   ├── goals.md
│   │   ├── requirements.md
│   │   ├── curriculum.md                # year/semester table → subject links
│   │   ├── methodology.md
│   │   ├── faculty.md
│   │   └── careers.md
│   └── subjects/{slug}.md               # 2,314 subject files
└── es/                                  # mirror with /estudios/-style slugs
```

## Frontmatter schema (the search backbone)

Each `programs/*/README.md` opens with YAML the agent can grep or load:

```yaml
title, slug, canonical_program_id, equivalent_program_id, pairing_confidence,
pairing_method, level, area, official, tags, modality, duration, ects,
languages_of_instruction, schedule, location, start_date, tuition_status,
admissions_contact, official_name, degree_issuer, subject_count,
related_programs, source_url, source_fetched_at, extractor_version,
extractor_mode, last_built_at
```

Subjects use a smaller schema (parent_programs, year, semester, type, ects,
canonical_subject_id, …).

## File-size budget

| File type | Target | Hard cap |
|---|---|---|
| Index (INDEX.md, by-*) | one line/item; ≤ 30 KB | 50 KB |
| Program README | 2–6 KB | 10 KB |
| Subpages | 0.5–2 KB | 5 KB |
| curriculum.md | 2–5 KB | 10 KB |
| Subject {slug}.md | 1–2 KB | 5 KB |

## Building the wiki: `scripts/build_wiki.py`

Five subcommands (Typer + rich):

| Subcommand | Input | Output |
|---|---|---|
| `extract` | `data/raw_html/`, `data/manifest.jsonl` | `data/structured.jsonl` |
| `pair` | `data/structured.jsonl` | `data/pairings.jsonl` |
| `render` | `data/structured.jsonl`, `data/pairings.jsonl` | `wiki/` (per-program markdown) |
| `index` | `wiki/` (frontmatter) | `wiki/INDEX.md`, `wiki/by-area/*`, …, `meta/*` |
| `verify` | `wiki/` | console report; nonzero exit on failure |

Run with `--sample N` (extract only) for a stratified pilot.

## HTML → markdown strategy

Targeted extraction off known Drupal field classes (documented in
`docs/04-knowledge-base-map.md`). `markdownify` is run **only** on each
field's inner HTML — never on the whole page. A controlled fallback
captures sanitized `<article>` text when a canonical selector misses;
those records are listed in `meta/fallback_report.md`.

## Cross-language pairing

Multi-signal weighted scoring across all EN×ES program pairs, then
**greedy bipartite matching** (highest-scoring pair first; each side
claimed only once) to prevent collisions:

| Signal | Weight |
|---|---|
| `slug_similarity` (token overlap after stripping prefixes) | 0.20 |
| `title_similarity` (token overlap on EN/ES-normalized titles) | 0.20 |
| `shared_subjects` (subject URLs are language-agnostic by URL) | 0.45 |
| `structural` (ECTS/duration/modality match) | 0.15 |

Auto-link rules (any of):

- weighted score ≥ 0.30 (bipartite matching keeps false-positive risk low)
- shared_subjects ≥ 0.5 + structural ≥ 0.5
- title_similarity ≥ 0.80 + slug_similarity ≥ 0.50
- title_similarity ≥ 0.85 + structural ≥ 0.85

Auto-pair rate on the salleurl.edu corpus: **58 %** (103/179 EN programs).
The remaining 42 % are short specialization courses and "Be a …" workshops
with sparse or absent ES counterparts.

## Verification (the safety net)

`verify` exits non-zero if any required check fails:

- All program seeds produced a wiki folder.
- Frontmatter completeness ≥ 98 % for required keys.
- Fallback rate < 5 % (selector-drift alarm).
- EN auto-pair rate ≥ 50 %.
- Dead links == 0.
- Programs in `area: other` < 10 (taxonomy drift).
- All program READMEs ≤ 25 KB.

## Read-only retrieval API: `catalog_wiki_api` v1

A small importable package the Phase 4 agent will call instead of doing
raw file reads. Pure read-only. Zero LLM calls. Identifiers are
canonical IDs (`en/{slug}`, `es/{slug}`); raw slugs only appear in the
explicit resolver endpoint.

### Endpoints

Discovery & facets:
- `list_programs(level=, area=, modality=, language=, lang=, offset=, limit=)`
- `search_programs(query, filters=, top_k=, lang=)`
- `get_index_facets(lang=)` — areas, levels, modalities, instruction
  languages, all in one call.
- `list_languages()`

Detail:
- `get_program(program_id, include_sections=False)`
- `get_program_section(program_id, section)` — sections:
  goals/requirements/curriculum/careers/methodology/faculty
- `get_curriculum(program_id)` — structured year → semester → subjects
- `get_subject(subject_id)`
- `list_subjects_for_program(program_id)`

Resolvers & relations:
- `get_program_by_slug(slug, lang=)`
- `get_equivalent(program_id, target_lang)` — only if pairing
  confidence ≥ 0.75
- `get_related_programs(program_id, top_k=)`
- `compare_programs(program_ids)`

Meta:
- `get_faq(lang=)`
- `get_glossary_entry(term, lang=)`

### Conventions

- Every payload includes `source_url`, `last_built_at`, `lang`.
- Lists include `total`, `applied_filters`, `offset`, `limit`.
- Bodies surface as `body_markdown` (str). Structured fields are
  separate keys; the caller does not parse markdown.
- Errors raise a typed `CatalogApiError(code=...)` with codes
  `not_found`, `invalid_filter`, `ambiguous_slug`.

### Search

Phase 3 shipped a token-overlap baseline. The pilot showed it had
clear failure modes (`"machine learning"` → 0 hits; cute 1-week summer
programs outranking the 4-year AI bachelor on `"AI"`), so Phase 4
upgraded to a **hybrid lexical + semantic ranker** — see the next
section.

### Retrieval (Phase 4 — agent-facing)

For the demo deployment on EC2 t3.micro (1 GB RAM, 2 vCPUs), the
ranker is a two-stage hybrid, all local, all deterministic:

1. **Lexical layer**: BM25-F over weighted fields (`title` 4.0,
   `tags` 3.0, `area` 2.0, `level` 1.5, `body` 1.0, `slug` 0.5) with
   EN+ES query expansion via `catalog_wiki_api/synonyms.py`
   (`machine learning → artificial intelligence`, `hacking →
   cybersecurity`, `startup → entrepreneurship`, …).
2. **Semantic layer**: Model2Vec `potion-base-8M` (~8 MB on disk,
   256-dim, ~5 ms query embed). Embeddings are **precomputed offline**
   by `scripts/build_embeddings.py` and shipped as a versioned sidecar:
   `wiki/meta/embeddings_{en,es}.npz` (~180 KB each, L2-normalised),
   `wiki/meta/embeddings_{en,es}_ids.jsonl`,
   `wiki/meta/embeddings_meta.json` (sidecar version + model name +
   vector dim + per-language corpus hash).
3. **Hybrid blend**: pool-normalised `0.55 * lexical + 0.45 *
   semantic`, multiplied by a level prior (substantive degrees +10 %,
   1-week summer programs −15 %; flipped when the query explicitly
   asks for short courses).

Mode selection (`LASALLE_RANKER_MODE` env var):
- `hybrid` (default)
- `lexical` / `bm25` (BM25 + synonyms, no embeddings)
- `semantic` (cosine only)
- `token_overlap` (legacy; ablation)

The agno tool wraps a single new endpoint:

```python
api.retrieve_program_candidates(
    query, lang="en", filters=None, top_k=10, mode=None,
)
```

Per-call `mode=` overrides the env var and never leaks state. The agno
tool stays thin: the LLM only sees the typed structured payload, never
markdown or vectors directly.

**Operational hardening:**
- `_semantic_meta()` runs a startup compatibility check —
  `sidecar_version`, `model_name`, `vector_dim` must match what the
  running code expects. Mismatch → log a warning and fall back to
  lexical-only.
- Embeddings load lazily on first retrieval call (no penalty if the
  agent only browses indexes).
- Memory ceiling test (`tests/test_search_ops.py`): 100 sequential
  hybrid queries must keep RSS under 700 MB.

### Build pipeline addition

Add to the existing `scripts/build_wiki.py` flow:

```bash
uv run python -m scripts.build_wiki extract     # Phase 3
uv run python -m scripts.build_wiki pair
uv run python -m scripts.build_wiki render
uv run python -m scripts.build_wiki index
uv run python -m scripts.build_embeddings       # Phase 4 (new)
uv run python -m scripts.build_wiki verify
```

### CLI

A thin Typer wrapper for debugging / pilot simulation:

```bash
uv run python -m catalog_wiki_api list-programs --level bachelor
uv run python -m catalog_wiki_api search "artificial intelligence"
uv run python -m catalog_wiki_api curriculum en/bachelor-animation-and-vfx
```

The CLI delegates to the package functions; no duplicated logic.

### Tests

Two suites under `tests/`:

- `test_api_contract.py` — contract tests for every endpoint (return
  shape, error codes, cross-reference consistency).
- `test_personas.py` — six student persona simulations using the API
  only, asserting ≤ 5 calls per scenario.

Run with `uv run pytest`.

## Pricing gap (worth flagging)

The catalog site does **not** publish tuition. Every program's
frontmatter sets `tuition_status: contact-required` and includes an
`admissions_contact` URL. The FAQ explicitly directs students to
admissions. The agent should do the same when pricing is asked about.

## Out of scope (Phase 3)

- The agent itself / RAG / embeddings (Phase 4).
- Faculty bio mining beyond what's in `faculty.md`.
- Ancillary PDFs — kept on disk but not converted.
- SQLite sidecar — JSONL is enough; revisit only if query latency hurts.
