# 02 – Download plan

Last updated: 2026-05-03
Owner: Joe (decisions) + Claude (execution)
Status: **Approved scope (UG + Grad), implementation pending.**

## Goal

Produce a complete, reproducible local mirror of the La Salle academic
catalog suitable for converting to markdown and indexing into a wiki for the
AI assistant. The mirror must cover every undergraduate and graduate program
plus the supporting course and policy pages, in three forms: original HTML,
per-page PDF, and full-catalog PDFs.

## Approach in one paragraph

Pull the sitemap. Filter the URL list down to the sections we care about
(`/undergraduate/*`, `/graduate/*`, `/general-info/*`, plus the two
catalog-wide PDFs). For each URL: fetch the HTML, derive the per-page PDF URL
deterministically, fetch the PDF, write both to disk under a path that
mirrors the URL. Record per-page metadata (URL, title, school, program type,
fetch timestamp, hashes) into a single `manifest.jsonl`. Rate-limit
politely. Re-runnable end to end.

## Phases

### Phase 1 – Exploration ✅ DONE

See [`01-exploration-findings.md`](./01-exploration-findings.md).

### Phase 2 – Bulk download (this plan)

Steps, in order:

1. **Fetch sitemap.** `GET /sitemap.xml`, parse 344 `<loc>` entries, save raw
   sitemap to `data/sitemap.xml` with the fetch timestamp.
2. **Filter URLs.** Keep prefixes `/undergraduate/`, `/graduate/`,
   `/general-info/`, plus the four index pages (`/`, `/programs/`,
   `/azindex/`, `/catalogcontents/`). Expected: ~330 URLs.
3. **Add the two whole-catalog PDFs** by hand:
   - `/pdf/La Salle University Catalog 2023-2024 - Undergraduate.pdf`
   - `/pdf/La Salle University Catalog 2023-2024 - Graduate.pdf`
   (Update slugs once a 2025-2026 version is published — recheck the print
   dialog on a current page to confirm the latest filename.)
4. **For each HTML URL:**
   1. `GET` the page, write the raw response body to
      `data/raw_html/<path-from-url>.html`.
   2. Compute per-page PDF URL by appending `<last-segment>.pdf` to the page
      URL. `HEAD` it; if 200, `GET` and write to
      `data/pdf/<path-from-url>.pdf`. Record the PDF size + sha256.
   3. Extract a small set of fields from the HTML — title, breadcrumb,
      catalog edition, list of tab containers, list of in-page course codes
      — and append a record to `manifest.jsonl`.
5. **Politeness controls:**
   - One request at a time, **1 request/sec** baseline (sleep 1.0s between
     requests). 344 URLs × 2 fetches each ≈ 700 requests ≈ 12 minutes.
   - Custom `User-Agent: LaSalleCatalogMirror/0.1 (joe.carr.data@gmail.com)`
     so the site owner can contact us if needed.
   - Honor `robots.txt`: skip every disallowed prefix.
   - Retry with exponential backoff on 5xx (max 3 retries); on 404, log and
     continue (404 on the per-page PDF is acceptable for index pages).
6. **Idempotency:** before writing, compare sha256 with the existing file —
   if identical, skip rewrite and just refresh the timestamp in the
   manifest. This makes weekly re-runs cheap.
7. **Verification step:**
   - Sitemap count ≥ 340 and ≤ 400.
   - HTML success rate ≥ 99%, log all failures.
   - At least 90% of program pages produced a PDF (some index/policy pages
     legitimately have none).
   - Spot-check 5 random programs visually (open HTML + PDF) before
     declaring success.

### Phase 3 – HTML → markdown conversion (separate task, not in this plan)

High-level approach we'll fill in later: per-page parser keyed on the
CourseLeaf container IDs (`#overviewtextcontainer`,
`#requirementstextcontainer`, etc.), produce one markdown file per program
under `data/markdown/`, plus a YAML front-matter block with the metadata
fields collected in phase 2. Course department pages get one markdown file
per department with one heading per course.

### Phase 4 – Wiki build / indexing (separate task)

Out of scope for this plan, but the storage layout in
[`03-storage-layout.md`](./03-storage-layout.md) is designed so phase 4 can
treat `data/markdown/` as the source of truth and ignore the raw HTML.

## Tools

- **Python 3.11+**
- `requests` for HTTP
- `lxml` (or `selectolax` if speed matters) for parsing
- `tqdm` for progress
- A single script: `scripts/fetch_catalog.py` with subcommands
  `sitemap`, `download`, `verify`, `clean`. Use `argparse`. Tests minimal but
  present (parsing helpers).
- Output: `data/sitemap.xml`, `data/raw_html/...`, `data/pdf/...`,
  `data/manifest.jsonl`, `data/run.log`.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Network allowlist blocks `catalog.lasalle.edu` from the sandbox | Run the script on the user's machine OR through a connected Cowork shell with egress; alternative path documented in `aha.md`. |
| CourseLeaf changes URL conventions in next edition | The scraper is sitemap-driven, so it survives URL changes inside the same domain. The PDF-URL convention is the only hard-coded rule; if it breaks, we fall back to parsing the "Download Page (PDF)" anchor on each HTML page. |
| Course descriptions hidden behind hover ribbits | Phase 3 concern, not phase 2. We capture the page as-is now; descriptions exist on the per-department `/courses-az/<dept>/` pages we already crawl. |
| Quietly losing a program when the catalog updates | Manifest diff: every run writes a new line per URL. A second script `scripts/diff_manifest.py` can compare runs and flag added/removed/modified pages. |

## Decisions already locked in (from user)

- Scope: undergraduate **+** graduate (no archives).
- Captures: HTML, per-page PDF, full-catalog PDF — all three.
- Runtime: Python + `requests` + sitemap, run reproducibly.
- Project layout: `/docs`, `/data`, `/scripts` at the project root.

## Decisions resolved (2026-05-04)

1. **Where the script runs:** On the user's Mac (unrestricted internet).
2. **Cadence:** One-shot for now. Scheduling can be added later once the
   script is proven.
3. **Markdown chunk granularity for phase 3:** TBD before phase 3 begins.
