# 03 – Storage layout (salleurl.edu)

Last updated: 2026-05-03

The local mirror mirrors the URL structure of the site 1:1 so mapping a
wiki page back to its source is trivial. There is no per-page PDF on
this site, so we drop the `pdf/` tree entirely; what we save is HTML and
a small set of ancillary PDFs (scholarship docs, etc.) collected along
the way.

## Tree

```
lasalle-catalog/                              # (folder name kept for git history; project is salleurl)
├── docs/
│   ├── INDEX.md
│   ├── 01-exploration-findings.md
│   ├── 02-download-plan.md
│   ├── 03-storage-layout.md                  # ← this file
│   ├── aha.md
│   └── archive/
│       └── 2026-05-03-wrong-university/      # see README inside
├── scripts/
│   ├── fetch_catalog.py                      # Phase 2 – Typer CLI: enumerate / download / verify / clean
│   ├── parse_to_markdown.py                  # Phase 3 – HTML → md (later)
│   └── diff_manifest.py                      # Compare two manifest.jsonl runs
└── data/
    ├── seed_urls.json                        # Phase 2A output
    ├── manifest.jsonl                        # One line per fetched URL
    ├── run.log                               # Append-only log per run
    ├── raw_html/                              # Mirrors URL path
    │   ├── en/
    │   │   ├── education/
    │   │   │   ├── degrees.html               # category index
    │   │   │   ├── masters-postgraduates.html
    │   │   │   ├── doctorate.html
    │   │   │   ├── course-browser_page=0.html # query string flattened to filename
    │   │   │   ├── ...
    │   │   │   ├── bachelor-animation-and-vfx.html
    │   │   │   ├── bachelor-animation-and-vfx/
    │   │   │   │   ├── goals.html
    │   │   │   │   ├── requirements.html
    │   │   │   │   ├── syllabus.html
    │   │   │   │   ├── methodology.html
    │   │   │   │   ├── academics.html
    │   │   │   │   └── career-opportunities.html
    │   │   │   └── master-user-experience.html
    │   │   └── escultura-anatomia-y-herramientas-digitales.html   # subject pages
    │   └── ...
    ├── pdf/                                  # Ad-hoc PDFs (scholarships, credit convalidation, ...)
    │   └── sites/default/files/content/entities/document/file/9397/
    │       └── grants-26-27-la-salle-campus-barcelona.pdf
    └── markdown/                             # Phase 3 output (initially empty)
        └── ...
```

## URL → path rule

1. Strip the protocol and host.
2. If the path ends with `/`, drop the trailing slash and add `.html`.
3. If the URL has a query string, replace `?` and `&` with `_` so it
   lands in a single filename. Example:
   `/en/education/course-browser?page=3` →
   `data/raw_html/en/education/course-browser_page=3.html`.
4. PDFs keep their original path under `data/pdf/`.

## seed_urls.json schema

```json
[
  {
    "url": "https://www.salleurl.edu/en/education/bachelor-animation-and-vfx",
    "title": "Bachelor in Animation and VFX",
    "source": ["course-browser?page=2", "/en/education/degrees"],
    "kind_guess": "bachelor"
  }
]
```

## manifest.jsonl schema

One JSON object per line. Append-only; `run_id` ties records together
for diffing.

```json
{
  "run_id": "2026-05-03T18:22:11Z",
  "url": "https://www.salleurl.edu/en/education/bachelor-animation-and-vfx",
  "kind": "program-base",
  "parent_url": null,
  "path": "data/raw_html/en/education/bachelor-animation-and-vfx.html",
  "lang": "en",
  "title": "Degree in Animation and VFX | La Salle Campus Barcelona",
  "h1": "Bachelor in Animation and VFX",
  "subpages_present": ["goals","requirements","syllabus","methodology","academics","career-opportunities"],
  "linked_subjects": ["/en/escultura-anatomia-y-herramientas-digitales", "/en/proyectos-i-0", "..."],
  "linked_pdfs": ["/sites/default/files/content/entities/document/file/9397/grants-26-27-la-salle-campus-barcelona.pdf"],
  "http_status": 200,
  "sha256": "…",
  "fetched_at": "2026-05-03T18:23:04Z"
}
```

For subject pages, `kind` is `"subject"` and `parent_url` is the
program-base URL that introduced it; if a subject is referenced by
several programs, the manifest gets one record per discovery (or, more
efficiently, one record with a `parent_urls` array — Phase 2
implementer chooses).

## Why this shape

- **Mirrors the URL** so debugging is trivial: paste the URL into the
  address bar, paste it into the file tree, both work.
- **No `pdf/` per program** because the site does not produce them. The
  `data/pdf/` directory only holds the handful of ancillary docs we
  encounter.
- **`seed_urls.json` separate from `manifest.jsonl`** so the
  enumeration phase is cheap to re-run independently of the download
  phase.
- **`docs/archive/`** preserves the wrong-university docs as historical
  context. Per project conventions, we never delete docs; we move them.
