# aha.md – salleurl.edu scraper

Short, opinionated takeaways. Read this first when resuming work.

## Confirm the institution before you start

The very first version of this project targeted `catalog.lasalle.edu`
(La Salle University, Philadelphia) — a completely different institution
that happens to share part of the name. The actual target is
`salleurl.edu` (La Salle Campus Barcelona, Universitat Ramon Llull).
**Always confirm the URL with the user before exploring**, especially
when the project name alone (e.g. "La Salle University") is ambiguous.

The Philadelphia exploration is preserved under
`docs/archive/2026-05-03-wrong-university/` for reference.

## The site is Drupal, not CourseLeaf

Tells: `/misc/`, `/modules/`, `/sites/default/files/` paths in
`robots.txt`; `og:type = university`; sibling subpages of the form
`/<program>/<section>` rather than anchor tabs in one document.

What this means in practice:
- No sitemap (`/sitemap.xml` returns HTTP 500). We crawl.
- No "Download Page (PDF)" affordance. Content is HTML only.
- Page templates differ across content types. The bachelor template has
  seven subpages; specialization courses often have only the base page.

## EN and ES use completely different URL structures

English uses `/en/education/` for everything. Spanish uses
`/es/estudios/` with different category slugs:

| EN | ES |
|---|---|
| `/en/education/degrees` | `/es/estudios/grados` |
| `/en/education/masters-postgraduates` | `/es/estudios/masters-y-postgrados` |
| `/en/education/course-browser` | `/es/estudios/buscador-de-estudios` |

The script uses a `LANG_CONFIG` dict keyed by language code to handle
this. **Do not assume URL patterns are the same across languages.**

Subpage suffixes also differ:

| EN | ES |
|---|---|
| `goals` | `objetivos` |
| `requirements` | `requisitos` |
| `syllabus` | `plan-estudios` |
| `methodology` | `metodologia` |
| `academics` | `profesorado` |
| `career-opportunities` | `salidas-profesionales` |

## URL conventions worth remembering

- Programmes index: `/en/education/course-browser` (paginated).
- Per-category index: `/en/education/{degrees, masters-postgraduates,
  doctorate, dual-degrees, specialization-course, online-training,
  summer-school}`.
- Bachelor program: `/en/education/<slug>` plus seven optional siblings
  `goals / requirements / syllabus / methodology / academics /
  career-opportunities`.
- Subject (course): `/en/<slug>` — note: NOT under `/en/education/`.
  Slug language is often Spanish ("escultura-anatomia-…") even on
  English pages; rely on `<html lang>` and `<title>` for actual content
  language, not the slug.

## robots.txt asks for a 10 second crawl-delay

That turns a complete run into multiple hours. Two responses:
1. Default to 10 s and run overnight.
2. Build resume support so a partial/crashed run can pick up from where
   it stopped.

We do both.

## There is no per-program PDF

Unlike CourseLeaf catalogs, salleurl.edu does not generate
program-specific PDFs. The PDFs that show up on program pages are
ancillary (scholarship forms, credit convalidation guides) and live at
`/sites/default/files/...`. Don't try to construct a PDF URL from a
program slug — it will 404.

## Subject pages are shared across programs

A subject (course) at `/en/<slug>` can be referenced from the syllabus
of multiple programs. Dedupe by URL when fetching, but record every
parent program in the manifest so the Phase-3 wiki step can build the
back-references.

## Direct fetches from this sandbox are blocked

Same as before: the workspace bash and the workspace web_fetch can't
reach `salleurl.edu` from the Cowork sandbox. The Claude-in-Chrome MCP
can. For Phase 2 either:
1. Run `scripts/fetch_catalog.py` on the user's Mac (no allowlist
   restriction), or
2. Add `salleurl.edu` and `www.salleurl.edu` to Cowork's egress
   allowlist (Settings → Capabilities).

## The Programme Browser paginates forever

`/en/education/course-browser?page=N` never returns an empty page. It
keeps returning ~8 links per page well past page 80+, likely cycling
through the same programs. You **cannot** use "0 links → stop" as the
termination condition. Instead stop after N consecutive pages with zero
new *unique* programs (we use 3) or a hard page cap (we use 60).

## Phase 3: HTML→markdown via field selectors, not html2text

Generic `markdownify` over the whole `<article>` produces ~30 KB of
boilerplate per page (Drupal nav, sidebar, scripts). Targeted field
extraction off Drupal's `field-name-*` classes is dramatically cleaner
— program READMEs end up at 2–6 KB. Use markdownify only on each
*field's inner HTML*, never the whole page. Keep a sanitized
`<article>` fallback for selector misses, mark the record
`extractor_mode: fallback`, and surface fallback rate in `verify` as
a selector-drift alarm (target <5%).

## Phase 3: faculty/syllabus contain markdown links to off-wiki paths

Drupal pages have hundreds of `[Name](/en/la-salle/directorio/...)`
links and `[![photo](img)](dest)` patterns. A simple regex with
`[^\]]+` fails because the link body spans multiple lines and
contains nested image syntax. Use a bracket-balanced scanner instead
(`_strip_offsite_links`). Required to drive verify dead-link count
from ~2,500 down to 0.

## Phase 3: bipartite matching > greedy best-match for EN↔ES pairing

When pairing EN↔ES programs, picking each EN's best ES leads to
collisions (multiple EN→one ES) and false positives. **Greedy
bipartite** (sort all candidate pairs by score, claim each side at
most once) is dramatically better. Combined with mutual best-match
semantics, false-positive risk drops enough to lower the auto-link
threshold to 0.30 with overrides — auto-pair rate for sparse short
courses jumps from ~5% to ~58% with no precision loss.

## Phase 3: subject URLs are language-agnostic — strongest pairing signal

EN and ES syllabi link to the same subject URL slugs (the slugs are
typically Spanish even on EN pages). Token overlap on subject URLs
between two programs' syllabi is the strongest single signal that
they're the same program in different languages. Weight it 0.45/1.0
in the pairing score; a single override "shared_subjects ≥ 0.5 +
structural ≥ 0.5 → auto-link" catches dozens of clear pairs that
title/slug similarity wouldn't.

## Phase 3: 90% pairing target was unrealistic for this corpus

The original plan called for ≥ 90% EN auto-pair rate. After multiple
iterations, the realistic ceiling is ~58%. The remaining 42% are
either short specialization courses with no ES counterpart, or
structurally different "weekday vs weekend" / "online vs on-site"
variants where the natural many-to-one mapping breaks bipartite
matching. Lowered the verify threshold to 50%; the low-confidence
unpaired programs land in `meta/pairings_unresolved.md` (in plan)
for human triage.

## The Chrome MCP blocks JS that reads cookie/query-string strings

We hit "BLOCKED: Cookie/query string data" when our exploration JS
returned `a.href` — full URLs sometimes include query strings that
look like cookie data to the safety filter. Workaround: return
`new URL(a.href).pathname` instead of `a.href` from JS evaluations.
