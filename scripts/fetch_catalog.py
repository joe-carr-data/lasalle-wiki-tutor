#!/usr/bin/env python3
"""Fetch and mirror the La Salle Campus Barcelona academic catalog.

Target: www.salleurl.edu (Drupal site, no sitemap, 10s crawl-delay)

Subcommands:
    enumerate  - Build the seed list by crawling category + browser pages
    download   - Fetch program pages, subpages, and subject pages
    verify     - Check the latest run against success criteria
    clean      - Remove orphan files not in the manifest
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import typer
from lxml import html
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://www.salleurl.edu"
USER_AGENT = "SalleUrlCatalogMirror/0.1 (joe.carr.data@gmail.com)"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SEED_PATH = DATA_DIR / "seed_urls.json"
MANIFEST_PATH = DATA_DIR / "manifest.jsonl"
LOG_PATH = DATA_DIR / "run.log"
HTML_DIR = DATA_DIR / "raw_html"
PDF_DIR = DATA_DIR / "pdf"

LANGUAGES = ("en", "es")

# Per-language configuration: the EN and ES sites use different URL structures.
LANG_CONFIG = {
    "en": {
        "education_prefix": "/en/education/",
        "category_pages": [
            "/en/education/degrees",
            "/en/education/masters-postgraduates",
            "/en/education/doctorate",
            "/en/education/dual-degrees",
            "/en/education/specialization-course",
            "/en/education/online-training",
            "/en/education/summer-school",
        ],
        "browser_url": "/en/education/course-browser",
    },
    "es": {
        "education_prefix": "/es/estudios/",
        "category_pages": [
            "/es/estudios/grados",
            "/es/estudios/masters-y-postgrados",
            "/es/estudios/doctorado",
            "/es/estudios/dobles-titulaciones",
            "/es/estudios/cursos-de-especializacion",
            "/es/estudios/formacion-online",
            "/es/estudios/escuela-de-verano",
        ],
        "browser_url": "/es/estudios/buscador-de-estudios",
    },
}

# Known non-program slugs kept as a pre-filter optimization only.
# The authoritative classification happens via is_program_page() using
# Drupal body classes after fetching the page.
NON_PROGRAM_SLUGS = {
    # EN category slugs
    "degrees", "masters-postgraduates", "doctorate", "dual-degrees",
    "specialization-course", "online-training", "summer-school",
    "course-browser", "undergraduate-degrees",
    # EN area groupings
    "architecture-and-construction", "digital-arts-animation-and-vfx",
    "computer-science", "ict-engineering-and-technology",
    "business-and-management", "project-management",
    "technology-and-health", "mba",
    # ES category slugs
    "grados", "masters-y-postgrados", "doctorado", "dobles-titulaciones",
    "cursos-de-especializacion", "formacion-online", "escuela-de-verano",
    "buscador-de-estudios",
    # ES area groupings
    "arquitectura-y-edificacion", "arte-digital-animacion-y-vfx",
    "informatica", "ingenierias-tic-y-tecnologia",
    "business-y-management", "direccion-de-proyectos",
    "tecnologia-y-salud",
}

PROGRAM_SUBPAGES = (
    "goals",
    "requirements",
    "syllabus",
    "methodology",
    "academics",
    "career-opportunities",
)

# robots.txt disallow prefixes (relevant ones)
DISALLOWED_PREFIXES = (
    "/admin/",
    "/node/add/",
    "/search/",
    "/user/login",
    "/user/register",
)

DEFAULT_DELAY = 3.0
DEFAULT_RESUME_WINDOW_HOURS = 24

# ---------------------------------------------------------------------------
# Typer app + Rich console
# ---------------------------------------------------------------------------

app = typer.Typer(
    help="Fetch and mirror the La Salle Campus Barcelona academic catalog (salleurl.edu)."
)
console = Console()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _setup_logging() -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("fetch_catalog")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    return logger


log = _setup_logging()

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


class RateLimitError(Exception):
    """Raised on HTTP 429 so we can hard-stop."""


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


@retry(
    retry=retry_if_exception_type(requests.ConnectionError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=30, max=120),
    reraise=True,
)
def _fetch_one(session: requests.Session, url: str) -> requests.Response:
    """Single fetch with tenacity retry on connection errors."""
    resp = session.get(url, timeout=30)
    if resp.status_code == 429:
        raise RateLimitError(f"HTTP 429 on {url}")
    if resp.status_code >= 500:
        log.warning("HTTP %d on %s, retrying", resp.status_code, url)
        raise requests.ConnectionError(f"Server error {resp.status_code}")
    return resp


def fetch(
    session: requests.Session,
    url: str,
    *,
    delay: float = DEFAULT_DELAY,
) -> requests.Response | None:
    """Fetch a URL politely. Returns None on permanent failure (not 429)."""
    try:
        resp = _fetch_one(session, url)
        time.sleep(delay)
        return resp
    except RateLimitError:
        console.print(f"[bold red]RATE LIMITED (429) on {url}. Stopping.[/bold red]")
        console.print("Re-run the same command to resume from where you left off.")
        raise SystemExit(1)
    except Exception as exc:
        log.error("Failed to fetch %s: %s", url, exc)
        time.sleep(delay)
        return None


# ---------------------------------------------------------------------------
# URL / path helpers
# ---------------------------------------------------------------------------


def url_to_html_path(url: str) -> Path:
    """Map a URL to its local HTML file path under data/raw_html/.

    - Strip protocol+host, drop trailing slash, append .html
    - Query strings: replace ? and & with _
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        path = "_index"

    # Flatten query string into filename
    if parsed.query:
        path = f"{path}_{parsed.query}"

    return HTML_DIR / f"{path}.html"


def url_to_pdf_path(url: str) -> Path:
    """Map a PDF URL to its local path under data/pdf/."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    return PDF_DIR / path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_if_changed(path: Path, data: bytes) -> tuple[bool, str]:
    """Write data only if content changed. Returns (changed, hash)."""
    h = sha256(data)
    if path.exists() and sha256(path.read_bytes()) == h:
        return False, h
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True, h


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def _append_manifest(record: dict[str, Any]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_manifest() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not MANIFEST_PATH.exists():
        return records
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _load_resume_set(resume_window_hours: float) -> set[str]:
    """Load URLs that were successfully fetched within the resume window."""
    records = _load_manifest()
    if not records:
        return set()
    cutoff = datetime.now(timezone.utc).timestamp() - (resume_window_hours * 3600)
    result: set[str] = set()
    for r in records:
        if r.get("http_status") == 200:
            fetched_at = r.get("fetched_at", "")
            try:
                ts = datetime.fromisoformat(fetched_at.replace("Z", "+00:00")).timestamp()
                if ts >= cutoff:
                    result.add(r["url"])
            except (ValueError, KeyError):
                pass
    return result


# ---------------------------------------------------------------------------
# HTML extraction helpers
# ---------------------------------------------------------------------------


def is_program_page(html_bytes: bytes) -> bool:
    """Detect if a page is a program page using Drupal structural signals.

    Program pages have body class 'node-type-estudio' and/or an article
    with class 'node-estudio'. Category/area pages have 'node-type-view-page'.
    """
    tree = html.fromstring(html_bytes)

    # Primary signal: body class
    body = tree.find(".//body")
    if body is not None:
        body_class = body.get("class", "")
        if "node-type-estudio" in body_class:
            return True
        if "node-type-view-page" in body_class:
            return False

    # Secondary signal: article class
    for article in tree.iter("article"):
        article_class = article.get("class", "")
        if "node-estudio" in article_class:
            return True
        if "node-view-page" in article_class:
            return False

    # Tertiary signal: presence of program tabs
    tabs = tree.get_element_by_id("tabs-estudis", None)
    if tabs is not None:
        return True

    # Unknown — default to True so we don't skip legitimate programs
    log.warning("Could not determine page type from structure, treating as program")
    return True


def extract_program_links(html_bytes: bytes, lang: str) -> list[dict[str, str]]:
    """Extract candidate program links from a category or browser page.

    Returns list of {url, title} dicts. Uses NON_PROGRAM_SLUGS as a
    pre-filter optimization; authoritative classification happens via
    is_program_page() after fetching each page.
    """
    tree = html.fromstring(html_bytes)
    results: list[dict[str, str]] = []
    config = LANG_CONFIG[lang]
    prefix = config["education_prefix"]

    for a in tree.iter("a"):
        href = a.get("href", "")
        text = (a.text_content() or "").strip()

        # Must be under the education prefix for this language
        if not href.startswith(prefix):
            continue

        # Skip links with query strings (advanced search filters, etc.)
        if "?" in href:
            continue

        # Strip trailing slash, split into segments
        clean_href = href.rstrip("/")
        segments = clean_href.split("/")

        # Must be exactly /{lang}/{education-word}/{slug} -> 4 segments
        if len(segments) != 4:
            continue

        slug = segments[3]

        # Pre-filter known non-programs (optimization, not correctness)
        if slug in NON_PROGRAM_SLUGS or not slug:
            continue

        # Filter short/empty text
        if len(text) <= 3:
            continue

        full_url = urljoin(BASE_URL, clean_href)
        results.append({"url": full_url, "title": text})

    return results


def extract_subject_links(html_bytes: bytes, lang: str) -> list[str]:
    """Extract subject page links from a syllabus page.

    Scoped to the main content container (view-tabs-estudis or article)
    to avoid picking up nav/footer links. Subject URLs are /{lang}/<slug>
    where slug is NOT under the education prefix.
    """
    tree = html.fromstring(html_bytes)
    prefix = f"/{lang}/"
    edu_prefix = LANG_CONFIG[lang]["education_prefix"]

    # Find the content container — use the article element (which contains
    # the program content). The #tabs-estudis element is just the nav tabs
    # and doesn't contain the subject links themselves.
    content_root = tree.find(".//article")
    if content_root is None:
        log.warning("No content container found for subject extraction, using full page")
        content_root = tree

    subjects: list[str] = []
    for a in content_root.iter("a"):
        href = a.get("href", "")
        if href.startswith(edu_prefix):
            continue
        if href.startswith(prefix) and len(href) > len(prefix) + 3:
            clean = href.rstrip("/")
            segments = clean.split("/")
            # /{lang}/{slug} -> 3 segments: ['', 'en', 'slug']
            if len(segments) == 3:
                full_url = urljoin(BASE_URL, clean)
                subjects.append(full_url)

    return subjects


def extract_pdf_links(html_bytes: bytes) -> list[str]:
    """Extract ancillary PDF links from any page."""
    tree = html.fromstring(html_bytes)
    pdfs: list[str] = []
    for a in tree.iter("a"):
        href = a.get("href", "")
        if "/sites/default/files/" in href and href.endswith(".pdf"):
            full_url = urljoin(BASE_URL, href)
            pdfs.append(full_url)
    return pdfs


def extract_title_and_h1(html_bytes: bytes) -> tuple[str, str]:
    """Extract <title> and <h1> from an HTML page."""
    tree = html.fromstring(html_bytes)
    title_el = tree.find(".//title")
    title = title_el.text_content().strip() if title_el is not None else ""
    h1_el = tree.find(".//h1")
    h1 = h1_el.text_content().strip() if h1_el is not None else ""
    return title, h1


def detect_lang(html_bytes: bytes) -> str:
    """Detect page language from <html lang=...>."""
    tree = html.fromstring(html_bytes)
    return tree.get("lang", "").split("-")[0] or "unknown"


def guess_kind(url: str) -> str:
    """Guess program kind from URL."""
    lower = url.lower()
    if "bachelor" in lower or "degree" in lower or "grado" in lower:
        return "bachelor"
    if "master" in lower or "postgraduate" in lower or "postgrado" in lower:
        return "master"
    if "doctorate" in lower or "phd" in lower or "doctorado" in lower:
        return "doctorate"
    if "dual" in lower or "doble" in lower:
        return "dual"
    if "specialization" in lower or "especializacion" in lower or "course-" in lower or "curso-" in lower:
        return "specialization"
    if "online" in lower:
        return "online"
    if "summer" in lower or "verano" in lower:
        return "summer"
    return "other"


def _rebuild_subject_queue_from_disk() -> dict[str, list[str]]:
    """Rebuild the subject queue from previously saved syllabus HTML files.

    This ensures that subjects are not lost on resume when a prior run
    fetched syllabus pages but crashed before fetching the subjects.
    """
    subject_queue: dict[str, list[str]] = {}
    if not HTML_DIR.exists():
        return subject_queue

    for syllabus_path in HTML_DIR.rglob("**/syllabus.html"):
        # Derive the parent program URL from the file path
        # e.g. data/raw_html/en/education/bachelor-foo/syllabus.html
        #   -> parent is /en/education/bachelor-foo
        rel = syllabus_path.relative_to(HTML_DIR)
        parts = rel.parts  # ('en', 'education', 'bachelor-foo', 'syllabus.html')
        if len(parts) < 3:
            continue
        parent_path = "/" + "/".join(parts[:-1])
        parent_url = f"{BASE_URL}{parent_path}"

        # Determine language from path
        lang = parts[0] if parts[0] in LANGUAGES else "en"

        try:
            html_bytes = syllabus_path.read_bytes()
            subjects = extract_subject_links(html_bytes, lang)
            for subj_url in subjects:
                if subj_url not in subject_queue:
                    subject_queue[subj_url] = []
                if parent_url not in subject_queue[subj_url]:
                    subject_queue[subj_url].append(parent_url)
        except Exception as exc:
            log.warning("Failed to parse saved syllabus %s: %s", syllabus_path, exc)

    return subject_queue


# ---------------------------------------------------------------------------
# Subcommand: enumerate
# ---------------------------------------------------------------------------


@app.command()
def enumerate(
    delay_seconds: float = typer.Option(DEFAULT_DELAY, help="Seconds between requests"),
) -> None:
    """Build the seed list by crawling category pages and the Programme Browser."""
    session = _session()
    seen: dict[str, dict[str, Any]] = {}  # url -> {url, title, source[], kind_guess}

    def _add(entries: list[dict[str, str]], source: str) -> None:
        for entry in entries:
            url = entry["url"]
            if url in seen:
                if source not in seen[url]["source"]:
                    seen[url]["source"].append(source)
            else:
                seen[url] = {
                    "url": url,
                    "title": entry["title"],
                    "source": [source],
                    "kind_guess": guess_kind(url),
                }

    # --- Category index pages ---
    all_cat_pages = [(lang, path) for lang in LANGUAGES for path in LANG_CONFIG[lang]["category_pages"]]
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Category pages", total=len(all_cat_pages))
        for lang, cat_path in all_cat_pages:
            url = f"{BASE_URL}{cat_path}"
            resp = fetch(session, url, delay=delay_seconds)
            if resp and resp.status_code == 200:
                links = extract_program_links(resp.content, lang)
                _add(links, cat_path)
                log.info("Category %s: %d links", url, len(links))
            else:
                status_code = resp.status_code if resp else "no response"
                log.warning("Category page failed: %s (status=%s)", url, status_code)
            progress.advance(task)

    # --- Programme Browser (paginated) ---
    # Stop conditions: stale streak (no new unique programs) OR cycle detection
    # (same page fingerprint seen before, meaning the paginator is cycling).
    STALE_PAGE_LIMIT = 3
    for lang in LANGUAGES:
        browser_base = LANG_CONFIG[lang]["browser_url"]
        page_num = 0
        stale_streak = 0
        seen_fingerprints: set[str] = set()
        cycle_count = 0
        with console.status(f"[bold]Browser /{lang}/ page {page_num}...") as status:
            while True:
                url = f"{BASE_URL}{browser_base}?page={page_num}"
                status.update(f"[bold]Browser /{lang}/ page {page_num} ({len(seen)} programs so far)")
                resp = fetch(session, url, delay=delay_seconds)
                if resp and resp.status_code == 200:
                    links = extract_program_links(resp.content, lang)
                    if not links:
                        log.info("Browser %s page %d: 0 links, stopping", lang, page_num)
                        console.print(f"  /{lang}/ browser: {page_num} pages, no more links")
                        break

                    # Cycle detection: hash the sorted URLs on this page
                    page_urls = sorted(l["url"] for l in links)
                    fp = sha256(",".join(page_urls).encode())
                    if fp in seen_fingerprints:
                        cycle_count += 1
                        log.info("Browser %s page %d: repeated fingerprint (%d)", lang, page_num, cycle_count)
                        if cycle_count >= 2:
                            console.print(f"  /{lang}/ browser: cycle detected at page {page_num}, stopping")
                            break
                    else:
                        seen_fingerprints.add(fp)
                        cycle_count = 0

                    before = len(seen)
                    _add(links, f"course-browser?page={page_num}")
                    new_count = len(seen) - before
                    log.info("Browser %s page %d: %d links (%d new)", lang, page_num, len(links), new_count)

                    # Stale streak: no new unique programs
                    if new_count == 0:
                        stale_streak += 1
                        if stale_streak >= STALE_PAGE_LIMIT:
                            console.print(f"  /{lang}/ browser: {page_num + 1} pages, {STALE_PAGE_LIMIT} consecutive stale pages, stopping")
                            break
                    else:
                        stale_streak = 0

                    page_num += 1
                else:
                    log.warning("Browser page failed: %s", url)
                    console.print(f"  /{lang}/ browser: stopped at page {page_num} (failed)")
                    break

    # --- Write seed file ---
    seeds = sorted(seen.values(), key=lambda s: s["url"])
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SEED_PATH, "w", encoding="utf-8") as f:
        json.dump(seeds, f, indent=2, ensure_ascii=False)

    # --- Summary ---
    table = Table(title="Enumeration Summary")
    table.add_column("Kind", style="bold")
    table.add_column("Count", justify="right")

    kind_counts: dict[str, int] = {}
    for s in seeds:
        k = s["kind_guess"]
        kind_counts[k] = kind_counts.get(k, 0) + 1
    for kind, count in sorted(kind_counts.items()):
        table.add_row(kind, str(count))
    table.add_row("[bold]Total[/bold]", f"[bold]{len(seeds)}[/bold]")

    console.print()
    console.print(table)

    # Cross-reference EN vs ES
    en_urls = {s["url"] for s in seeds if "/en/" in s["url"]}
    es_urls = {s["url"] for s in seeds if "/es/" in s["url"]}
    console.print(f"EN programs: {len(en_urls)}, ES programs: {len(es_urls)}")
    console.print(f"Seed list written to [green]{SEED_PATH}[/green]")


# ---------------------------------------------------------------------------
# Subcommand: download
# ---------------------------------------------------------------------------


@app.command()
def download(
    delay_seconds: float = typer.Option(DEFAULT_DELAY, help="Seconds between requests"),
    resume_window: float = typer.Option(
        DEFAULT_RESUME_WINDOW_HOURS,
        help="Skip URLs successfully fetched within this many hours",
    ),
) -> None:
    """Fetch program pages, subpages, and subject pages."""
    if not SEED_PATH.exists():
        console.print("[red]No seed list found. Run 'enumerate' first.[/red]")
        raise typer.Exit(1)

    with open(SEED_PATH, encoding="utf-8") as f:
        seeds: list[dict[str, Any]] = json.load(f)

    console.print(f"Loaded [bold]{len(seeds)}[/bold] seed URLs")

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session = _session()
    already_done = _load_resume_set(resume_window)
    if already_done:
        console.print(f"Resuming: [green]{len(already_done)}[/green] URLs already fetched within {resume_window}h")

    # Fix #1: Rebuild subject queue from saved syllabus files on disk
    subject_queue: dict[str, list[str]] = _rebuild_subject_queue_from_disk()
    if subject_queue:
        console.print(f"Rebuilt [green]{len(subject_queue)}[/green] subject URLs from saved syllabus files")

    pdf_queue: set[str] = set()
    non_program_count = 0

    # --- Phase 1: Programs + subpages ---
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Programs", total=len(seeds))

        for seed in seeds:
            base_url = seed["url"]
            lang = "es" if "/es/" in base_url else "en"

            # Collect data for the base record (written AFTER subpage loop - Fix #5)
            base_title = ""
            base_h1 = ""
            base_hash = ""
            base_status = 0
            base_is_program = True
            subpages_present: list[str] = []
            linked_subjects: list[str] = []
            linked_pdfs: list[str] = []

            if base_url not in already_done:
                resp = fetch(session, base_url, delay=delay_seconds)
                if resp and resp.status_code == 200:
                    changed, h = write_if_changed(url_to_html_path(base_url), resp.content)
                    base_title, base_h1 = extract_title_and_h1(resp.content)
                    base_hash = h
                    base_status = 200
                    linked_pdfs.extend(extract_pdf_links(resp.content))
                    already_done.add(base_url)

                    # Fix #3: Structural program detection
                    if not is_program_page(resp.content):
                        base_is_program = False
                        non_program_count += 1
                        log.info("Non-program page (skipping subpages): %s", base_url)
                elif resp:
                    base_status = resp.status_code
            else:
                # Already fetched — check if it's a program from saved HTML
                saved_path = url_to_html_path(base_url)
                if saved_path.exists():
                    saved_html = saved_path.read_bytes()
                    base_is_program = is_program_page(saved_html)
                    base_title, base_h1 = extract_title_and_h1(saved_html)
                    base_hash = sha256(saved_html)
                    base_status = 200

            # Only fetch subpages for confirmed program pages
            if base_is_program and base_status == 200:
                for suffix in PROGRAM_SUBPAGES:
                    sub_url = f"{base_url}/{suffix}"
                    if sub_url in already_done:
                        subpages_present.append(suffix)
                        continue

                    resp = fetch(session, sub_url, delay=delay_seconds)
                    if resp and resp.status_code == 200:
                        changed, h = write_if_changed(url_to_html_path(sub_url), resp.content)
                        title, h1 = extract_title_and_h1(resp.content)
                        subpages_present.append(suffix)

                        # Extract subjects from syllabus (Fix #4: scoped to content container)
                        if suffix == "syllabus":
                            subjects = extract_subject_links(resp.content, lang)
                            linked_subjects.extend(subjects)
                            for subj_url in subjects:
                                if subj_url not in subject_queue:
                                    subject_queue[subj_url] = []
                                if base_url not in subject_queue[subj_url]:
                                    subject_queue[subj_url].append(base_url)

                        linked_pdfs.extend(extract_pdf_links(resp.content))

                        _append_manifest({
                            "run_id": run_id,
                            "url": sub_url,
                            "kind": "program-subpage",
                            "parent_url": base_url,
                            "path": str(url_to_html_path(sub_url).relative_to(DATA_DIR.parent)),
                            "lang": lang,
                            "title": title,
                            "h1": h1,
                            "subpages_present": [],
                            "linked_subjects": [],
                            "linked_pdfs": [],
                            "http_status": 200,
                            "sha256": h,
                            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        })
                        already_done.add(sub_url)
                    elif resp and resp.status_code == 404:
                        log.debug("Subpage 404 (expected): %s", sub_url)
                    elif resp:
                        log.warning("Subpage %d: %s", resp.status_code, sub_url)

            # Fix #5: Write base record AFTER subpage loop with populated fields
            kind = "program-base" if base_is_program else "non-program"
            if base_status > 0:
                _append_manifest({
                    "run_id": run_id,
                    "url": base_url,
                    "kind": kind,
                    "parent_url": None,
                    "path": str(url_to_html_path(base_url).relative_to(DATA_DIR.parent)),
                    "lang": lang,
                    "title": base_title,
                    "h1": base_h1,
                    "subpages_present": subpages_present,
                    "linked_subjects": linked_subjects,
                    "linked_pdfs": linked_pdfs,
                    "http_status": base_status,
                    "sha256": base_hash,
                    "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                })

            # Collect PDFs from all pages
            for pdf_url in linked_pdfs:
                pdf_queue.add(pdf_url)

            progress.advance(task)

    if non_program_count:
        console.print(f"Skipped [yellow]{non_program_count}[/yellow] non-program pages (category/area pages)")

    # --- Phase 2: Subject pages ---
    subjects_to_fetch = [u for u in subject_queue if u not in already_done]
    if subjects_to_fetch:
        console.print(f"Fetching [bold]{len(subjects_to_fetch)}[/bold] subject pages "
                       f"({len(subject_queue)} total, {len(subject_queue) - len(subjects_to_fetch)} already done)")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Subjects", total=len(subjects_to_fetch))

            for subj_url in subjects_to_fetch:
                lang = "es" if "/es/" in subj_url else "en"
                resp = fetch(session, subj_url, delay=delay_seconds)
                if resp and resp.status_code == 200:
                    changed, h = write_if_changed(url_to_html_path(subj_url), resp.content)
                    title, h1 = extract_title_and_h1(resp.content)
                    linked_pdfs_here = extract_pdf_links(resp.content)
                    for pdf_url in linked_pdfs_here:
                        pdf_queue.add(pdf_url)

                    _append_manifest({
                        "run_id": run_id,
                        "url": subj_url,
                        "kind": "subject",
                        "parent_url": subject_queue[subj_url],
                        "path": str(url_to_html_path(subj_url).relative_to(DATA_DIR.parent)),
                        "lang": lang,
                        "title": title,
                        "h1": h1,
                        "subpages_present": [],
                        "linked_subjects": [],
                        "linked_pdfs": linked_pdfs_here,
                        "http_status": 200,
                        "sha256": h,
                        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    })
                    already_done.add(subj_url)
                elif resp:
                    _append_manifest({
                        "run_id": run_id,
                        "url": subj_url,
                        "kind": "subject",
                        "parent_url": subject_queue[subj_url],
                        "path": "",
                        "lang": lang,
                        "title": "",
                        "h1": "",
                        "subpages_present": [],
                        "linked_subjects": [],
                        "linked_pdfs": [],
                        "http_status": resp.status_code,
                        "sha256": "",
                        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    })

                progress.advance(task)

    # --- Phase 3: Ancillary PDFs ---
    pdfs_to_fetch = [u for u in pdf_queue if u not in already_done]
    if pdfs_to_fetch:
        console.print(f"Fetching [bold]{len(pdfs_to_fetch)}[/bold] ancillary PDFs")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("PDFs", total=len(pdfs_to_fetch))

            for pdf_url in pdfs_to_fetch:
                resp = fetch(session, pdf_url, delay=delay_seconds)
                if resp and resp.status_code == 200:
                    pdf_path = url_to_pdf_path(pdf_url)
                    changed, h = write_if_changed(pdf_path, resp.content)
                    _append_manifest({
                        "run_id": run_id,
                        "url": pdf_url,
                        "kind": "ancillary-pdf",
                        "parent_url": None,
                        "path": str(pdf_path.relative_to(DATA_DIR.parent)),
                        "lang": "",
                        "title": pdf_url.split("/")[-1],
                        "h1": "",
                        "subpages_present": [],
                        "linked_subjects": [],
                        "linked_pdfs": [],
                        "http_status": 200,
                        "sha256": h,
                        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    })
                    already_done.add(pdf_url)

                progress.advance(task)

    console.print("[green]Download complete.[/green] Run [bold]verify[/bold] to check results.")


# ---------------------------------------------------------------------------
# Subcommand: verify
# ---------------------------------------------------------------------------


@app.command()
def verify() -> None:
    """Verify the latest download run against success criteria."""
    records = _load_manifest()
    if not records:
        console.print("[red]No manifest found. Run 'download' first.[/red]")
        raise typer.Exit(1)

    # Use latest run_id
    latest_run = max(r["run_id"] for r in records)
    run_records = [r for r in records if r["run_id"] == latest_run]

    # Load seeds for cross-reference
    seeds: list[dict[str, Any]] = []
    if SEED_PATH.exists():
        with open(SEED_PATH, encoding="utf-8") as f:
            seeds = json.load(f)

    # Categorize
    bases = [r for r in run_records if r["kind"] == "program-base"]
    non_programs = [r for r in run_records if r["kind"] == "non-program"]
    subpages = [r for r in run_records if r["kind"] == "program-subpage"]
    subjects = [r for r in run_records if r["kind"] == "subject"]
    pdfs = [r for r in run_records if r["kind"] == "ancillary-pdf"]

    # Count bachelors in seeds
    bachelor_seeds = [s for s in seeds if s.get("kind_guess") == "bachelor"]

    # Base page success
    bases_ok = [r for r in bases if r.get("http_status") == 200]

    # Subpage coverage: for each base URL, how many subpages were fetched?
    base_urls = {r["url"] for r in bases_ok}
    subpage_counts: dict[str, int] = {u: 0 for u in base_urls}
    for r in subpages:
        parent = r.get("parent_url", "")
        if parent in subpage_counts and r.get("http_status") == 200:
            subpage_counts[parent] += 1
    programs_with_3plus = sum(1 for c in subpage_counts.values() if c >= 3)
    coverage_pct = programs_with_3plus / len(subpage_counts) * 100 if subpage_counts else 0

    # Build report
    table = Table(title=f"Verification Report - Run {latest_run}")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_column("Expected")

    bachelor_ok = len(bachelor_seeds) >= 21
    table.add_row(
        "Bachelor programs in seeds",
        f"{'[green]' if bachelor_ok else '[red]'}{len(bachelor_seeds)}[/]",
        ">= 21",
    )
    table.add_row("Total seed URLs", str(len(seeds)), "200-400")

    seed_urls = {s["url"] for s in seeds}
    base_fetched = {r["url"] for r in bases_ok}
    non_program_urls = {r["url"] for r in non_programs}
    # Seeds that are neither program-base nor non-program are truly missing
    missing_bases = seed_urls - base_fetched - non_program_urls
    bases_complete = len(missing_bases) == 0
    table.add_row(
        "Program bases fetched",
        f"{'[green]' if bases_complete else '[red]'}{len(bases_ok)}/{len(seeds)}[/]",
        "all program seeds",
    )
    table.add_row(
        "Non-program pages skipped",
        str(len(non_programs)),
        "",
    )

    coverage_ok = coverage_pct >= 80
    table.add_row(
        "Programs with >= 3 subpages",
        f"{'[green]' if coverage_ok else '[red]'}{coverage_pct:.0f}%[/] ({programs_with_3plus}/{len(subpage_counts)})",
        ">= 80%",
    )

    subject_ok = 300 <= len(subjects) <= 3000
    table.add_row(
        "Subject pages fetched",
        f"{'[green]' if subject_ok else '[red]'}{len(subjects)}[/]",
        "300-3,000",
    )
    table.add_row("Ancillary PDFs", str(len(pdfs)), "")
    table.add_row("Total records this run", str(len(run_records)), "")

    console.print()
    console.print(table)

    if missing_bases:
        console.print(f"\n[red]Missing base pages ({len(missing_bases)}):[/red]")
        for url in sorted(missing_bases)[:20]:
            console.print(f"  {url}")
        if len(missing_bases) > 20:
            console.print(f"  ... and {len(missing_bases) - 20} more")

    checks_passed = bachelor_ok and bases_complete and coverage_ok and subject_ok
    if checks_passed:
        console.print("\n[bold green]All checks PASSED.[/bold green]")
    else:
        console.print("\n[bold red]Some checks FAILED.[/bold red] Review the output above.")


# ---------------------------------------------------------------------------
# Subcommand: clean
# ---------------------------------------------------------------------------


@app.command()
def clean() -> None:
    """Remove files not referenced in the manifest (orphans)."""
    records = _load_manifest()
    if not records:
        console.print("No manifest found. Nothing to clean.")
        return

    referenced_paths: set[str] = set()
    for r in records:
        if r.get("path"):
            referenced_paths.add(r["path"])

    removed = 0
    for root_dir in [HTML_DIR, PDF_DIR]:
        if not root_dir.exists():
            continue
        for filepath in root_dir.rglob("*"):
            if filepath.is_file():
                rel = str(filepath.relative_to(DATA_DIR.parent))
                if rel not in referenced_paths:
                    filepath.unlink()
                    removed += 1
                    log.debug("Removed orphan: %s", filepath)

    # Clean empty directories
    for root_dir in [HTML_DIR, PDF_DIR]:
        if not root_dir.exists():
            continue
        for dirpath in sorted(root_dir.rglob("*"), reverse=True):
            if dirpath.is_dir() and not any(dirpath.iterdir()):
                dirpath.rmdir()

    console.print(f"Removed [red]{removed}[/red] orphan files.")


if __name__ == "__main__":
    app()
