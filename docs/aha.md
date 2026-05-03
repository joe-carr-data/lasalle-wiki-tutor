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

## URL conventions worth remembering

- Programmes index: `/en/education/course-browser` (paginated 0–40).
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

## The Chrome MCP blocks JS that reads cookie/query-string strings

We hit "BLOCKED: Cookie/query string data" when our exploration JS
returned `a.href` — full URLs sometimes include query strings that
look like cookie data to the safety filter. Workaround: return
`new URL(a.href).pathname` instead of `a.href` from JS evaluations.
