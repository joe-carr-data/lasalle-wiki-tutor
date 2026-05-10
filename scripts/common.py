"""Shared primitives for the LaSalle catalog scripts.

These constants and helpers were originally defined inline in
`scripts/fetch_catalog.py`. They are duplicated here so that
`scripts/build_wiki.py` and `catalog_wiki_api/` can import them
without depending on the fetch script. The fetch script keeps its
copy intact to avoid disrupting the working Phase 2 implementation.

Single source of truth for: URL conventions, path mapping, language
config, file I/O helpers, and HTML structural classifiers.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from lxml import html

# ---------------------------------------------------------------------------
# Project paths and constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.salleurl.edu"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
HTML_DIR = DATA_DIR / "raw_html"
PDF_DIR = DATA_DIR / "pdf"
MANIFEST_PATH = DATA_DIR / "manifest.jsonl"
WIKI_DIR = PROJECT_ROOT / "wiki"
STRUCTURED_PATH = DATA_DIR / "structured.jsonl"
PAIRINGS_PATH = DATA_DIR / "pairings.jsonl"

LANGUAGES = ("en", "es")

# ---------------------------------------------------------------------------
# Per-language URL configuration
# ---------------------------------------------------------------------------

LANG_CONFIG: dict[str, dict[str, Any]] = {
    "en": {
        "education_prefix": "/en/education/",
        "browser_url": "/en/education/course-browser",
    },
    "es": {
        "education_prefix": "/es/estudios/",
        "browser_url": "/es/estudios/buscador-de-estudios",
    },
}

# Suffix → role; role="syllabus" means subject links should be extracted
PROGRAM_SUBPAGES: dict[str, tuple[tuple[str, str | None], ...]] = {
    "en": (
        ("goals", None),
        ("requirements", None),
        ("syllabus", "syllabus"),
        ("methodology", None),
        ("academics", None),
        ("career-opportunities", None),
    ),
    "es": (
        ("objetivos", None),
        ("requisitos", None),
        ("plan-estudios", "syllabus"),
        ("metodologia", None),
        ("profesorado", None),
        ("salidas-profesionales", None),
    ),
}

# Map English subpage label → canonical section key used in the wiki
SUBPAGE_SECTION_KEYS = {
    "goals": "goals",
    "objetivos": "goals",
    "requirements": "requirements",
    "requisitos": "requirements",
    "syllabus": "curriculum",
    "plan-estudios": "curriculum",
    "methodology": "methodology",
    "metodologia": "methodology",
    "academics": "faculty",
    "profesorado": "faculty",
    "career-opportunities": "careers",
    "salidas-profesionales": "careers",
}

# ---------------------------------------------------------------------------
# Path mapping
# ---------------------------------------------------------------------------


def url_to_html_path(url: str) -> Path:
    """Map a catalog URL to its local HTML path under data/raw_html/."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        path = "_index"
    if parsed.query:
        path = f"{path}_{parsed.query}"
    return HTML_DIR / f"{path}.html"


def url_to_slug(url: str) -> str:
    """Return the last path segment of a URL (no language prefix)."""
    return urlparse(url).path.rstrip("/").split("/")[-1]


def url_to_lang(url: str) -> str:
    """Return 'en' or 'es' from a salleurl.edu URL."""
    return "es" if "/es/" in url else "en"


def canonical_program_id(url: str) -> str:
    """Build the canonical_program_id used as the API primary key.

    Format: '<lang>/<slug>', e.g. 'en/bachelor-animation-and-vfx'.
    """
    return f"{url_to_lang(url)}/{url_to_slug(url)}"


def canonical_subject_id(url: str) -> str:
    """Build the canonical_subject_id (same shape as program id)."""
    return f"{url_to_lang(url)}/{url_to_slug(url)}"


# ---------------------------------------------------------------------------
# Hashing and idempotent writes
# ---------------------------------------------------------------------------


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_if_changed(path: Path, data: bytes | str) -> tuple[bool, str]:
    """Write data to path only if the content changed.

    Returns (changed, sha256_hash).
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    h = sha256(data)
    if path.exists() and sha256(path.read_bytes()) == h:
        return False, h
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True, h


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def load_manifest() -> list[dict[str, Any]]:
    """Load all records from data/manifest.jsonl."""
    records: list[dict[str, Any]] = []
    if not MANIFEST_PATH.exists():
        return records
    with MANIFEST_PATH.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def latest_record_per_url(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return {url: latest_record} keeping the last occurrence per URL.

    The manifest is append-only, so the last record per URL is the most
    recent. Useful for deduplicating across multiple runs.
    """
    by_url: dict[str, dict[str, Any]] = {}
    for r in records:
        by_url[r["url"]] = r
    return by_url


# ---------------------------------------------------------------------------
# HTML structural classifiers
# ---------------------------------------------------------------------------


def is_program_page(html_bytes: bytes) -> bool:
    """Detect a program page via Drupal body/article classes.

    Program pages have body class 'node-type-estudio' or article class
    'node-estudio'. Category/area pages have 'node-type-view-page'.
    """
    tree = html.fromstring(html_bytes)

    body = tree.find(".//body")
    if body is not None:
        body_class = body.get("class", "")
        if "node-type-estudio" in body_class:
            return True
        if "node-type-view-page" in body_class:
            return False

    for article in tree.iter("article"):
        article_class = article.get("class", "")
        if "node-estudio" in article_class:
            return True
        if "node-view-page" in article_class:
            return False

    if tree.get_element_by_id("tabs-estudis", None) is not None:
        return True

    return True  # unknown — be permissive


# ---------------------------------------------------------------------------
# Link extraction (subject and PDF) — used by build_wiki for cross-refs
# ---------------------------------------------------------------------------


def extract_subject_links(html_bytes: bytes, lang: str) -> list[str]:
    """Extract subject page links from a syllabus page.

    Scoped to the <article> element to avoid nav/footer noise.
    Subject URLs are /{lang}/<slug> (3 segments), NOT under
    `/en/education/` or `/es/estudios/`.
    """
    tree = html.fromstring(html_bytes)
    prefix = f"/{lang}/"
    edu_prefix = LANG_CONFIG[lang]["education_prefix"]

    content_root = tree.find(".//article")
    if content_root is None:
        content_root = tree

    subjects: list[str] = []
    for a in content_root.iter("a"):
        href = a.get("href", "")
        if href.startswith(edu_prefix):
            continue
        if href.startswith(prefix) and len(href) > len(prefix) + 3:
            clean = href.rstrip("/")
            segments = clean.split("/")
            if len(segments) == 3:
                full_url = urljoin(BASE_URL, clean)
                subjects.append(full_url)
    return subjects


def extract_pdf_links(html_bytes: bytes) -> list[str]:
    """Extract ancillary PDF links from a page (Drupal /sites/default/files/...)."""
    tree = html.fromstring(html_bytes)
    pdfs: list[str] = []
    for a in tree.iter("a"):
        href = a.get("href", "")
        if "/sites/default/files/" in href and href.endswith(".pdf"):
            pdfs.append(urljoin(BASE_URL, href))
    return pdfs
