# 02 – Download plan (salleurl.edu)

Last updated: 2026-05-03
Owner: Joe (decisions) + Claude (execution)
Status: **Approved, all questions resolved. Implementation in progress.**

## Goal

Produce a complete, reproducible local mirror of La Salle Campus
Barcelona's academic offering (`salleurl.edu/en/education/...`), suitable
for converting to markdown and indexing into a wiki for the AI assistant.
Capture every program plus the subject pages they reference. Keep the run
resumable, polite, and re-runnable when the catalog updates.

## Approach in one paragraph

There is no sitemap, so the crawler is **two-phase, breadth-first, and
resumable**. Phase A enumerates every program URL by walking the
category index pages plus the paginated Programme Browser, and writes
them to a `seed_urls.json`. Phase B walks the seeds: for each program
fetch its base URL and the seven known subpages (`/goals`,
`/requirements`, `/syllabus`, `/methodology`, `/academics`,
`/career-opportunities`), tolerate 404s, then extract subject links from
each `/syllabus` page and fetch those too (deduplicated globally). Every
fetch goes through the same polite client (10 s crawl-delay, retry with
backoff, idempotent writes). A `manifest.jsonl` records each URL once,
making re-runs fast.

## Phases

### Phase 1 – Exploration ✅ DONE

See [`01-exploration-findings.md`](./01-exploration-findings.md).

### Phase 2 – Bulk download (this plan)

Implement a single CLI: `scripts/fetch_catalog.py`. Subcommands:

| Subcommand | What it does |
|---|---|
| `enumerate` | Build the seed list by crawling category pages + Programme Browser. Writes `data/seed_urls.json`. Does not fetch program detail. |
| `download` | Walk the seed list. For each program: fetch base + 7 known subpages, save HTML, extract subject links, queue them. Dedupe globally. Append to `manifest.jsonl`. |
| `verify` | Run integrity checks (counts, status codes, expected subpages, broken links). |
| `clean` | Optional: delete files not referenced in the manifest (orphans from earlier runs). |

Recommended stack:

- **Python 3.11+**
- `requests` (HTTP) with a `Session` for connection reuse
- `selectolax` (fast HTML parser; or `lxml` if a richer XPath story is
  needed)
- `tenacity` (retry with exponential backoff)
- `tqdm` (progress)
- `typer` + `rich` (CLI; per the conversation about Python CLIs)
- Stdlib `json`, `pathlib`, `urllib.parse`, `hashlib`, `time`, `logging`

#### Phase 2A – `enumerate`

1. Fetch each category index page once:
   - `/en/education/degrees`
   - `/en/education/masters-postgraduates`
   - `/en/education/doctorate`
   - `/en/education/dual-degrees`
   - `/en/education/specialization-course`
   - `/en/education/online-training`
   - `/en/education/summer-school`
2. Fetch the Programme Browser pages:
   - `/en/education/course-browser?page=0` → `?page=40`
3. From each, extract `<a href="/en/education/<slug>">` links where the
   path has exactly 4 segments and the link text length > 3 chars.
4. Tag each entry with which source(s) it came from (so we can spot a
   program that's only in the Browser and not in any category page, or
   vice versa).
5. Write `data/seed_urls.json` as a list of `{url, title, source[]}`.
   Expected size: 200–400 entries.

#### Phase 2B – `download`

For each seed URL `U`:

1. Fetch `U` itself → save to `data/raw_html/<path>.html`.
2. For each `suffix` in `["goals", "requirements", "syllabus",
   "methodology", "academics", "career-opportunities"]`:
   - Fetch `U + "/" + suffix`. If 200, save. If 404, log and skip
     (shorter programs legitimately omit subpages).
3. After fetching `U/syllabus` (if present), extract subject links of the
   form `/en/<slug>` (NOT under `/en/education/`) and add them to a
   global subject queue, deduplicated by URL.
4. After all programs are processed, walk the subject queue. Each
   subject is fetched once even if referenced by N programs; backlinks
   are recorded in the manifest.
5. Every successful fetch appends one line to `manifest.jsonl` with:
   - `run_id`, `url`, `kind` (program-base | program-subpage | subject |
     category-index), `parent_url` (for subpages and subjects),
     `path`, `status`, `sha256`, `fetched_at`, `lang`,
     `title`, `h1`.

#### Politeness

- **Default 10 s sleep between requests** (matches `Crawl-delay`). Override
  via `--delay-seconds N`. We will not go below 3 seconds without checking
  in with the user first.
- Custom `User-Agent: SalleUrlCatalogMirror/0.1
  (joe.carr.data@gmail.com)`.
- Retry policy via `tenacity`: 3 attempts on 5xx and connection errors,
  exponential backoff starting at 30 seconds. **Stop hard on 429** (rate
  limit) and surface to the operator.
- Idempotent writes: compare sha256 of the new body against the existing
  file before rewriting.

#### Resume support

Every fetch starts by checking `manifest.jsonl` for a previous successful
record of the same URL within `--resume-window` (default 24 hours). If
present, skip. This means a crashed overnight run can be re-launched
with the same command and only does the missing work.

#### Verification (must pass before declaring success)

- ≥ 21 bachelor's-style program URLs are present in `seed_urls.json`
  (sanity check against the known undergraduate count).
- `manifest.jsonl` contains a `program-base` record for every seed URL,
  with HTTP 200.
- For at least 80 % of program-base records, **at least three** of the
  seven program subpages were fetched successfully.
- Subject-page count is between 300 and 3,000 (anything outside this
  range probably means the syllabus extractor is broken).
- Spot-check 5 random programs: open the saved HTML for the base page
  and the syllabus subpage, confirm they look right.

### Phase 3 – HTML → markdown (separate task, not in this plan)

Outline only: per-page parser keyed off Drupal's `field-*` and
`region-*` containers, produce one markdown file per program (with a
section per subpage) and one per subject. YAML front-matter with the
metadata captured in Phase 2.

### Phase 4 – Wiki indexing (separate task)

Out of scope here.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Network allowlist blocks `salleurl.edu` from the sandbox | Run on the user's Mac, or the user adds the host to Cowork's egress allowlist (Settings → Capabilities). |
| Drupal page templates differ between content types (bachelor vs. master vs. specialization course) | Parser is best-effort and per-content-type; Phase 2 saves raw HTML so Phase 3 can re-parse without re-downloading. |
| Crawl-delay turns the run into 8+ hours | Resume support + idempotent writes make multi-session runs cheap. Or: ask user to accept a faster delay. |
| Session-blocked JS in some browsers (we hit this in exploration) | We're using plain `requests` for the actual scrape, so this is only a problem for the Chrome-driven exploration. |
| URLs change between catalog editions | Same-domain URLs at salleurl.edu are stable per academic year. Re-running `enumerate` after a year flip will surface added/removed programs in a manifest diff. |
| Subject slug collision between programs | Already handled: subject pages are deduped by URL globally; `manifest.jsonl` records every program that referenced each subject. |

## Decisions resolved (2026-05-04)

1. **Languages:** `/en/` + `/es/` (English and Spanish; no Catalan).
2. **Program-type scope:** All types (bachelors, masters, PhD,
   specialization, dual, online, summer, executive).
3. **Crawl rate:** 3 s between requests (default `--delay-seconds 3`).
   Resume support mitigates any 429 risk.
4. **Run mode:** One-shot for now. Scheduling can be added later.
5. **Where it runs:** On the user's Mac (unrestricted internet).
