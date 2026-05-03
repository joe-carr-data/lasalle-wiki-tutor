# 01 – Exploration findings (salleurl.edu)

Last updated: 2026-05-03
Target: La Salle Campus Barcelona, Universitat Ramon Llull
Root URL: https://www.salleurl.edu/en

This replaces the earlier exploration of `catalog.lasalle.edu` (different
institution); see `docs/archive/2026-05-03-wrong-university/`.

## Summary

`salleurl.edu` is a **Drupal-based** university website. It has **no
public sitemap** (`/sitemap.xml` returns HTTP 500), `robots.txt` requests
a strict **`Crawl-delay: 10`** seconds, and there is **no standardized
"download as PDF" endpoint** for program pages. Content lives across
several pages per program rather than on a single document. Compared to
the CourseLeaf catalog we were originally looking at, this is a more
work-intensive scrape, but the URL conventions are consistent enough to
build a reliable crawler.

## Site at a glance

| Item | Value |
|---|---|
| CMS | Drupal (signals: `/misc/`, `/modules/`, `/sites/default/files/` paths in robots.txt) |
| Languages | `/en/`, `/es/`, `/ca/` (English, Spanish, Catalan) – verified `/en/`; assume the others mirror it |
| `og:type` | `university` |
| Sitemap | None (HTTP 500 on `/sitemap.xml`, `/sitemap_index.xml`) |
| robots.txt | Standard Drupal robots, **`Crawl-delay: 10`**, no `Sitemap:` directive |
| Per-page PDF | ❌ Not available |
| Whole-catalog PDF | ❌ Not available |

## Top-level academic structure

Everything academic hangs off `/en/education`:

| Category | URL | Approx. count |
|---|---|---:|
| Programme Browser (master list) | `/en/education/course-browser` | paginated 0-40, ~9 per page, **~360 entries total** |
| Undergraduate Degrees | `/en/education/degrees` | **21** |
| Postgraduate & Master Degrees | `/en/education/masters-postgraduates` | **~57** (some duplicate listings) |
| PhD Programmes | `/en/education/doctorate` | **1** |
| Dual Degree Programmes | `/en/education/dual-degrees` | TBD |
| Specialization courses | `/en/education/specialization-course` | TBD |
| Online Courses | `/en/education/online-training` | TBD |
| Summer School | `/en/education/summer-school` | TBD |
| Executive Education | `/en/business/professional-and-executive-education` | TBD |

The **Programme Browser** is the most reliable single enumeration source:
`/en/education/course-browser?page=0` through `?page=40`. Each page lists
~9 programs, sortable by title or start date. We use it to build the
master list, then verify against the per-category pages above.

## Anatomy of a program page

Example (Bachelor in Animation and VFX, undergraduate):

Base URL: `/en/education/bachelor-animation-and-vfx`

A bachelor's program is split across **7 sibling URLs** that share the
same base path:

| Subpage | URL suffix | What's there |
|---|---|---|
| Overview | `/` (the base) | Hero, intro, certifications, collaborators, related links |
| Goals | `/goals` | Learning outcomes |
| Requirements | `/requirements` | Admission requirements |
| Syllabus | `/syllabus` | **Course list with links to per-subject pages** |
| Methodology | `/methodology` | Teaching approach |
| Academics | `/academics` | Faculty, structure |
| Career opportunities | `/career-opportunities` | Roles, employability |

Not every program has all seven. Specialization courses, summer schools,
and shorter postgrad programs typically have fewer (often only the base
page).

The page renders entirely server-side (no JS-loaded tabs), so a single
HTTP fetch returns the full content for each subpage.

## Anatomy of a subject (course) page

The Syllabus page links to individual subjects, each with its own URL of
the form `/en/<slug>`. Slugs are frequently in Spanish even on English
pages (e.g. `/en/escultura-anatomia-y-herramientas-digitales`), but the
content at `/en/<slug>` is rendered in English. A spot check:

- URL: `/en/escultura-anatomia-y-herramientas-digitales`
- Page title: "Sculpting, anatomy and digital tools"
- H1: "Bachelor in Animation and VFX" (subject's parent program)
- ~6 KB of English text per subject

Per-bachelor subject count looks to be in the 30–40 range, putting the
total subject-page count in the **600–1,500** band across all programs.

## PDFs

There is **no standardized "Download Page (PDF)" affordance**. The PDFs
that do appear on program pages are ancillary documents:

- Scholarship docs, e.g. `/sites/default/files/content/entities/document/file/9397/grants-26-27-la-salle-campus-barcelona.pdf`
- Credit convalidation forms

These are served from `/sites/default/files/...`, the standard Drupal
file path, and are not specific to a single program. We will collect the
URLs and dedupe across programs; we will **not** invent or guess
program-specific PDF URLs because none exist.

## robots.txt

```
User-agent: *
Crawl-delay: 10
Allow:  /misc/*.css   /misc/*.js   …
Disallow: /admin/, /node/add/, /search/, /user/login, /user/register, …
(no Sitemap: directive)
```

Translation:
- All program pages, subject pages, and category indexes are allowed.
- We **must** wait 10 seconds between requests to comply.
- There is no machine-readable enumeration of pages – we have to crawl.

## Languages

The English nav links to `/en/...`. Drupal multilingual setups typically
mirror the structure under `/es/` and `/ca/`. For Phase 2 the **English
tree is the default**, but we should record the language as part of each
record so that adding `/es/` or `/ca/` later is a flag flip. (Open
question; see Phase 2 plan.)

## What's hard about this scrape (compared to the original target)

| Friction | Why it matters |
|---|---|
| No sitemap | We have to derive the URL list by crawling category pages and the Programme Browser, then deduplicate. |
| `Crawl-delay: 10` | A polite end-to-end run is slow: ~3,000 fetches × 10s ≈ 8 hours. Plan for an overnight or multi-session run with resume support. |
| No per-program PDF | All content has to come from HTML parsing. A single program is 7 pages plus N subject pages – ~40 fetches per bachelor's degree. |
| Spanish/Catalan slugs on the English site | Slug language is not a reliable signal of content language. Use the `<html lang>` attribute and the document title. |
| Subjects shared across programs | Subject pages are referenced from multiple programs' syllabi. Dedupe by URL when fetching; record back-references for the wiki. |

## What we are NOT going to scrape

- `/admin/`, `/user/login`, `/user/register`, `/node/add/` – disallowed.
- Static assets (`/misc/`, `/modules/`, etc.) – not useful for a wiki.
- `blogs.salleurl.edu` and other subdomains – out of scope; those are
  news/blog content, not the academic offering.
- `/es/`, `/ca/` trees – out of scope by default for Phase 2 (open
  question).

## Open questions for Phase 2

These need a decision before the scraper runs (see Phase 2 plan):

1. **Languages**: English only, or all three (`/en/`, `/es/`, `/ca/`)?
2. **Program scope**: Bachelors + masters + PhD only, or also include
   specialization courses, summer school, executive education, online
   courses, dual degrees?
3. **Crawl rate**: Strict 10 s/request as `robots.txt` requests, or a
   negotiated faster rate (e.g. 3 s) accepting some risk of being rate
   limited?
4. **Run mode**: One-shot, or scheduled (weekly/monthly) so the wiki
   stays current?
