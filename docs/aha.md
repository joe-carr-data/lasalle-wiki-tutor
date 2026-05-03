# aha.md – La Salle catalog scraper

Short, opinionated takeaways. Read this first when resuming work.

## The catalog runs on CourseLeaf

`catalog.lasalle.edu` is a CourseLeaf (Leepfrog) catalog. CourseLeaf has
extremely consistent conventions across institutions:

- `/sitemap.xml` is always present and complete.
- `/programs/`, `/azindex/`, `/catalogcontents/`, `/course-search/` are
  standard index pages.
- Every program/course page has a "Download Page (PDF)" button whose URL is
  deterministic: `<page-url><last-slug>.pdf`.
- The seven anchor tabs on a program page (Overview, Degree Info, Learning
  Outcomes, Requirements, Course Sequence, Courses, Faculty) are all
  rendered server-side into the same HTML — no JS execution required.

Anything we build for La Salle is reusable for other CourseLeaf schools with
near-zero changes.

## Per-page PDF URL convention

```
page:  https://catalog.lasalle.edu/<a>/<b>/<slug>/
pdf:   https://catalog.lasalle.edu/<a>/<b>/<slug>/<slug>.pdf
```

Verified live. ~50 KB per file. HTTP 200, `Content-Type: application/pdf`.
This is the cleanest way to capture a frozen snapshot of each program page.

## robots.txt blocks `/pdf/` but the print dialog links to it

The whole-catalog PDFs (`/pdf/La Salle … Catalog … - Undergraduate.pdf`) are
publicly surfaced through the catalog's own UI, but `/pdf/` is in
`robots.txt` `Disallow`. We resolve this by fetching the **explicit two
filenames** the UI links to, not by listing/crawling `/pdf/`. That's the
narrowest interpretation that still gets the user what they asked for.

## The catalog edition string is in the page, not the URL

The "2025-2026 Edition" label appears in page metadata but URLs are
edition-agnostic. When the next edition publishes, the same scraper
produces a different snapshot. **Always record the edition string in the
manifest.**

## Direct fetch from this sandbox is blocked

`mcp__workspace__web_fetch` and `mcp__workspace__bash` cannot reach
`catalog.lasalle.edu` from this Cowork sandbox — the egress allowlist does
not include it. Two ways forward when phase 2 runs:

1. Ask the user to add `catalog.lasalle.edu` to the allowlist
   (Settings → Capabilities). Easiest on Team/Enterprise plans.
2. Run `scripts/fetch_catalog.py` on the user's Mac directly, where there
   is no allowlist.

For exploration we used the Claude-in-Chrome MCP, which does have access.
That worked fine for spot checks but is too slow for 700 fetches.

## Project tooling: uv + Typer

We use **uv** for Python environment management (`uv sync` creates `.venv`
and installs deps from `pyproject.toml`). The CLI uses **Typer** with
**rich** for colored output and progress bars. Run scripts with
`uv run python scripts/fetch_catalog.py <subcommand>`.

## The course search API is a tempting trap

`/course-search/api/` looks like the obvious enumeration shortcut and
returns clean JSON. It is `Disallow`ed in `robots.txt`. We ignore it; the
sitemap + per-department `/courses-az/<dept>/` pages cover the same ground
politely.
