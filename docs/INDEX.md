# SalleURL Catalog Wiki – Documentation Index

Last updated: 2026-05-10

This index points to the most recent and authoritative document for each
topic. Always start here when looking for project context.

## Project status

Phase: **6 – Deployment** (shared-token gate, Docker image, AWS t3.micro
+ Caddy recipe, wiki corpus shipped as a GitHub Release asset)
Next phase: actually-stand-up the EC2 and hand the token to evaluators

## Target

Live site: https://www.salleurl.edu/en
Institution: La Salle Campus Barcelona, Universitat Ramon Llull (Spain)
CMS: Drupal

## Documents

| # | Document | Purpose | Status |
|---|----------|---------|--------|
| 00 | [`00-kickoff-prompt.md`](./00-kickoff-prompt.md) | Ready-to-paste prompt for starting Phase 2 in a fresh Claude Code session | Current |
| 00b | [`00-correction-prompt.md`](./00-correction-prompt.md) | Prompt for redirecting an in-flight Claude Code session away from the wrong-university docs | Current |
| 01 | [`01-exploration-findings.md`](./01-exploration-findings.md) | What we learned about salleurl.edu (URL patterns, page anatomy, robots) | Current |
| 02 | [`02-download-plan.md`](./02-download-plan.md) | Phased plan for downloading HTML + ancillary PDFs and building the wiki source | Current |
| 03 | [`03-storage-layout.md`](./03-storage-layout.md) | On-disk layout for raw HTML, PDFs, manifests | Current |
| 04 | [`04-knowledge-base-map.md`](./04-knowledge-base-map.md) | What's in the corpus, what's useful for students, content tiers | Current |
| 05 | [`05-wiki-architecture.md`](./05-wiki-architecture.md) | Phase 3 wiki layout, build pipeline, and read-only API (`catalog_wiki_api` v1) | Current |
| 06 | [`06-frontend.md`](./06-frontend.md) | Phase 5 frontend chat UI, conversations REST API, prod hardening | Current |
| 07 | [`07-deploy.md`](./07-deploy.md) | Phase 6 — bootstrap a fresh clone, AWS t3.micro + Caddy, wiki release artifact | Current |
| –  | [`aha.md`](./aha.md) | Short list of "aha" moments / lessons learned. Read this first when resuming work. | Current |

## Archive

| When | What | Why |
|---|---|---|
| 2026-05-03 | [`archive/2026-05-03-wrong-university/`](./archive/2026-05-03-wrong-university/) | Initial Phase 1 docs targeted `catalog.lasalle.edu` (Philadelphia) by mistake. Kept for reference; do not use for Phase 2. |

## Conventions

- New documents are named `NN-short-slug.md` so chronological order is
  obvious.
- When a doc is superseded, move the old version to `docs/archive/`
  (grouped by date) and link the new one from this index.
- Every doc starts with a "Last updated" line and a short summary.
- Anything that surprised us or took several tries to figure out goes
  into `aha.md` (kept short).

## Quick links

- Live site: https://www.salleurl.edu/en
- Education root: https://www.salleurl.edu/en/education
- Programme Browser: https://www.salleurl.edu/en/education/course-browser
- robots.txt: https://www.salleurl.edu/robots.txt (Crawl-delay: 10)
