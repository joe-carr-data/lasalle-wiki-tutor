# 01 – Exploration findings

Last updated: 2026-05-03
Source of truth: live browse of `catalog.lasalle.edu` performed 2026-05-03.

## Summary

`catalog.lasalle.edu` is a CourseLeaf (Leepfrog) academic catalog. CourseLeaf
catalogs across institutions share the same conventions, so most of the
patterns below are reusable. The current edition is **2025-2026**. There is a
clean, public `sitemap.xml` that enumerates every catalog page (344 URLs), and
every program/course page exposes a downloadable per-page PDF at a
predictable URL. There is no public JSON API we are allowed to scrape (the
course-search API is blocked by `robots.txt`), but we don't need one — the
sitemap + per-page HTML covers everything.

## Top-level structure

The catalog is split into three trees plus general info:

| Section | URL | What's there |
|---|---|---|
| Undergraduate | `/undergraduate/` | Majors, minors/electives, school overviews, courses A–Z |
| Graduate | `/graduate/` | Masters, certificates/endorsements, doctorates, courses A–Z |
| General info | `/general-info/` | Faculty list, financial info, policies, student resources |
| Programs index | `/programs/` | Filterable list of every program (UG + Grad) on one page |
| Courses A–Z | `/course-search/` | Filterable list of every course |
| Catalog A–Z | `/azindex/` | Alphabetical index of every page |
| Archives | `/archives/` | One prior edition: `2023-2024` |

## Sitemap (the easy enumeration)

`https://catalog.lasalle.edu/sitemap.xml` returns 344 `<loc>` entries. Bucketed by
URL prefix:

| Prefix | Count |
|---|---:|
| `undergraduate/arts-sciences/` | 94 |
| `undergraduate/courses-az/` | 80 (one page per department) |
| `undergraduate/business/` | 28 |
| `undergraduate/nursing-health-sciences/` | 19 |
| `graduate/courses-az/` | 40 |
| `graduate/certificates-endorsements-preparatory-programs/` | 32 |
| `graduate/masters/` | 25 |
| `graduate/doctorates/` | 5 |
| `general-info/*` | 5 |
| Other (indexes, policy pages, school overviews) | ~16 |

The sitemap is the single best entry point for enumeration — drop in a
`requests.get(...)`, parse the XML, and you have the full URL list.

## Anatomy of a program page

Example: `https://catalog.lasalle.edu/graduate/masters/artificial-intelligence-ms/`

Each program is a single HTML page with seven anchor-tabs (all rendered into
the same DOM, so one fetch gets everything):

1. **Overview** – `#overviewtextcontainer`
2. **Degree Info** – `#degreeinfotextcontainer`
3. **Learning Outcomes** – `#learningoutcomestextcontainer`
4. **Requirements** – `#requirementstextcontainer` (tables of required courses)
5. **Course Sequence** – `#coursesequencetextcontainer`
6. **Courses** – `#coursestextcontainer` (linked or full course descriptions)
7. **Faculty** – `#facultytextcontainer`

Not every program has all seven; minors and certificates often have fewer.
The HTML structure is consistent enough that a single parser keyed off these
container IDs handles every program in the catalog.

## Anatomy of a course department page

Example: `https://catalog.lasalle.edu/undergraduate/courses-az/csit/`

One HTML page per department, containing many `.courseblock` elements. Each
courseblock has:

- `.courseblocktitle` – e.g. `CSIT 150 - Introduction to Computer Programming`
- `.courseblockdesc` – description, prereqs, credits

The CSIT page contains 27 courses; total course count across the catalog is
in the low thousands. There is no individual per-course URL — the department
page is the canonical source.

## PDF endpoints (the important discovery)

Every program and course page has a "Download Page (PDF)" button that points
to a deterministic URL:

```
<page-url><last-slug>.pdf
```

Examples:

- `…/graduate/masters/artificial-intelligence-ms/` → `…/artificial-intelligence-ms.pdf`
- `…/undergraduate/courses-az/csit/`               → `…/csit.pdf`
- `…/undergraduate/business/accounting-bsba/`      → `…/accounting-bsba.pdf`

Verified live: HTTP 200, `Content-Type: application/pdf`, ~50 KB per page.

There are also **whole-catalog PDFs** under `/pdf/`:

- `…/pdf/La%20Salle%20University%20Catalog%202023-2024%20-%20Undergraduate.pdf`
- `…/pdf/La%20Salle%20University%20Catalog%202023-2024%20-%20Graduate.pdf`

These are linked from the print dialog and are publicly accessible (note:
`/pdf/` is `Disallow`ed in `robots.txt`, so we will only fetch the two
catalog-wide files — not crawl the directory — and we will respect that
constraint by using the explicit URL surfaced through the print dialog).

## robots.txt — what we may and may not crawl

```
User-agent: *
Disallow: /general-info/archives/
Disallow: /admin/, /cim/, /courseadmin/, /courseleaf/
Disallow: /course-search/build/, /course-search/api/, /course-search/dashboard/
Disallow: /pdf/        ← see note above
Disallow: /search/, /shared/, /tmp/, /js/, /css/, /images/, /fonts/, /styles/
Sitemap: https://catalog.lasalle.edu/sitemap.xml
```

Translation: every URL we care about (everything in the sitemap, plus the
per-page `.pdf` URLs that live alongside the HTML pages) is explicitly
allowed. The blocked paths are admin tooling and asset directories. The only
gray-area items are the two whole-catalog PDFs in `/pdf/`. We will fetch
exactly those two, since they are publicly surfaced through the UI and the
user has approved capturing them.

## What we are NOT going to scrape

- `/course-search/api/` – blocked by robots, and we don't need it.
- The CourseLeaf admin UIs.
- Asset directories (CSS, JS, fonts, images).
- Archived editions (per user decision: current 2025-2026 only).

## Open questions / risks

- **Course descriptions inside requirements tables**: the Requirements tab
  often lists courses by code with hover-tooltips that load full descriptions
  asynchronously (CourseLeaf "ribbits"). Our parser must either follow the
  course code to the matching A–Z page, or fetch the ribbit endpoint —
  decided in phase 2.
- **Faculty links**: the Faculty tab references `/general-info/faculty/`,
  which we already have on the crawl list, so faculty bios resolve naturally.
- **Catalog year rollover**: the `2025-2026` slug is in page metadata, not in
  URLs. When the next edition publishes (~July 2026) URLs stay the same but
  content changes. The scraper needs to record the catalog edition string.

## What this means for the wiki

The catalog is small (~340 pages), highly structured, and the URL conventions
are stable. A single Python scraper using `requests` + `lxml` against the
sitemap will produce a clean, complete corpus suitable for chunking into
markdown wiki pages. See [`02-download-plan.md`](./02-download-plan.md) for
the phased plan.
