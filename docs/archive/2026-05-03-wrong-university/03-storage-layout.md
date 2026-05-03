# 03 – Storage layout

Last updated: 2026-05-03

The local mirror mirrors the URL structure of the catalog 1:1 so that
mapping a wiki page back to its source is trivial.

## Tree

```
lasalle-catalog/
├── docs/                              # Project documentation (this folder)
│   ├── INDEX.md                       # Always start here
│   ├── 01-exploration-findings.md
│   ├── 02-download-plan.md
│   ├── 03-storage-layout.md           # ← this file
│   ├── aha.md                         # Short, opinionated lessons
│   └── archive/                       # Superseded docs go here
├── scripts/
│   ├── fetch_catalog.py               # Phase 2 – HTML+PDF downloader
│   ├── parse_to_markdown.py           # Phase 3 – HTML → md (later)
│   └── diff_manifest.py               # Compare two manifest.jsonl runs
└── data/
    ├── sitemap.xml                    # Snapshot of /sitemap.xml at fetch time
    ├── manifest.jsonl                 # One line per URL, see schema below
    ├── run.log                        # Append-only log per run
    ├── raw_html/                      # Mirrors URL path
    │   ├── undergraduate/
    │   │   ├── arts-sciences/
    │   │   │   └── accounting-bsba.html
    │   │   ├── business/...
    │   │   └── courses-az/csit.html
    │   ├── graduate/
    │   │   ├── masters/artificial-intelligence-ms.html
    │   │   └── doctorates/...
    │   └── general-info/...
    ├── pdf/                           # Same path shape as raw_html, .pdf extension
    │   ├── undergraduate/...
    │   ├── graduate/...
    │   └── _catalog/                  # Whole-catalog PDFs
    │       ├── 2023-2024-undergraduate.pdf
    │       └── 2023-2024-graduate.pdf
    └── markdown/                      # Phase 3 output (initially empty)
        └── ...
```

## URL → path rule

Strip the protocol and host, drop the trailing slash, then place the file at
that path with the chosen extension. Examples:

- `https://catalog.lasalle.edu/graduate/masters/artificial-intelligence-ms/`
  → `data/raw_html/graduate/masters/artificial-intelligence-ms.html`
  → `data/pdf/graduate/masters/artificial-intelligence-ms.pdf`
- `https://catalog.lasalle.edu/undergraduate/courses-az/csit/`
  → `data/raw_html/undergraduate/courses-az/csit.html`
  → `data/pdf/undergraduate/courses-az/csit.pdf`

Index pages (paths ending with no slug after the section, e.g.
`/undergraduate/`) get the file name `_index.html`.

## manifest.jsonl schema

One JSON object per line. Append-only per run; a `run_id` ties records
together for diffing.

```json
{
  "run_id": "2026-05-03T18:22:11Z",
  "url": "https://catalog.lasalle.edu/graduate/masters/artificial-intelligence-ms/",
  "html_path": "data/raw_html/graduate/masters/artificial-intelligence-ms.html",
  "pdf_url":  "https://catalog.lasalle.edu/graduate/masters/artificial-intelligence-ms/artificial-intelligence-ms.pdf",
  "pdf_path": "data/pdf/graduate/masters/artificial-intelligence-ms.pdf",
  "title": "Artificial Intelligence, M.S.",
  "school": "School of Arts and Sciences",
  "program_type": "masters",
  "level": "graduate",
  "tabs_present": ["overview","degreeinfo","learningoutcomes","requirements","coursesequence","courses","faculty"],
  "course_codes": ["CSC 555","CSC 580","..."],
  "html_sha256": "…",
  "pdf_sha256": "…",
  "html_status": 200,
  "pdf_status": 200,
  "fetched_at": "2026-05-03T18:23:04Z"
}
```

## Why this shape

- **Mirrors the URL** so debugging is trivial: paste the URL into the address
  bar, paste it into the file tree, both work.
- **HTML and PDF kept separate** so the markdown step in phase 3 can ignore
  PDFs entirely (HTML is the easier source).
- **Manifest is line-delimited JSON**, not one big JSON document, so each run
  appends without rewriting the world and `diff_manifest.py` can stream.
- **`docs/archive/`** matches the user's stated documentation conventions —
  superseded docs are preserved, not deleted, and `INDEX.md` always points to
  the current one.
