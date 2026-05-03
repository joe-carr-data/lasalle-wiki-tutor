# La Salle Catalog Wiki – Documentation Index

Last updated: 2026-05-04

This index points to the most recent and authoritative document for each
topic. Always start here when looking for project context.

## Project status

Phase: **2 – Bulk download** (script implemented, ready to run)
Next phase: **3 – HTML to markdown conversion** (not started)

## Documents

| # | Document | Purpose | Status |
|---|----------|---------|--------|
| 00 | [`00-kickoff-prompt.md`](./00-kickoff-prompt.md) | Ready-to-paste prompt for starting Phase 2 in a fresh Claude Code session | Current |
| 01 | [`01-exploration-findings.md`](./01-exploration-findings.md) | What we learned about the catalog site (URL patterns, page anatomy, PDF endpoints, robots.txt, scale) | Current |
| 02 | [`02-download-plan.md`](./02-download-plan.md) | Phased plan for downloading HTML + PDFs + building the wiki source | Current |
| 03 | [`03-storage-layout.md`](./03-storage-layout.md) | On-disk layout for raw HTML, PDFs, markdown, and metadata | Current |
| –  | [`aha.md`](./aha.md) | Short list of "aha" moments / lessons learned. Read this first when resuming work. | Current |

## Conventions

- New documents are named `NN-short-slug.md` so chronological order is obvious.
- When a doc is superseded, move the old version to `docs/archive/` and link
  the new one from this index.
- Every doc starts with a "Last updated" line and a short summary.
- Anything that surprised us or took several tries to figure out goes into
  `aha.md` (kept short).

## Quick links

- Live catalog (current edition): https://catalog.lasalle.edu/
- Sitemap: https://catalog.lasalle.edu/sitemap.xml (344 URLs)
- robots.txt: https://catalog.lasalle.edu/robots.txt
- CMS: CourseLeaf (Leepfrog) — standard pattern, important for reuse
