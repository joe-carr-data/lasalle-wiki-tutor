#!/usr/bin/env python3
"""Fetch and mirror the La Salle University academic catalog.

Subcommands:
    sitemap   - Download and parse the sitemap
    download  - Fetch HTML pages and per-page PDFs
    verify    - Check the latest run against success criteria
    clean     - Remove downloaded data (keeps sitemap)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import requests
import typer
from lxml import etree, html
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://catalog.lasalle.edu"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
USER_AGENT = "LaSalleCatalogMirror/0.1 (joe.carr.data@gmail.com)"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SITEMAP_PATH = DATA_DIR / "sitemap.xml"
MANIFEST_PATH = DATA_DIR / "manifest.jsonl"
LOG_PATH = DATA_DIR / "run.log"
HTML_DIR = DATA_DIR / "raw_html"
PDF_DIR = DATA_DIR / "pdf"

ALLOWED_PREFIXES = (
    "/undergraduate/",
    "/graduate/",
    "/general-info/",
)

ALLOWED_EXACT = {
    "/",
    "/programs/",
    "/azindex/",
    "/catalogcontents/",
}

DISALLOWED_PREFIXES = (
    "/general-info/archives/",
    "/admin/",
    "/cim/",
    "/courseadmin/",
    "/courseleaf/",
    "/course-search/build/",
    "/course-search/api/",
    "/course-search/dashboard/",
    "/pdf/",
    "/search/",
    "/shared/",
    "/tmp/",
    "/js/",
    "/css/",
    "/images/",
    "/fonts/",
    "/styles/",
)

CATALOG_PDFS = [
    f"{BASE_URL}/pdf/La%20Salle%20University%20Catalog%202023-2024%20-%20Undergraduate.pdf",
    f"{BASE_URL}/pdf/La%20Salle%20University%20Catalog%202023-2024%20-%20Graduate.pdf",
]

TAB_IDS = [
    "overviewtextcontainer",
    "degreeinfotextcontainer",
    "learningoutcomestextcontainer",
    "requirementstextcontainer",
    "coursesequencetextcontainer",
    "coursestextcontainer",
    "facultytextcontainer",
]

REQUEST_DELAY = 1.0
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# Typer app + Rich console
# ---------------------------------------------------------------------------

app = typer.Typer(help="Fetch and mirror the La Salle University academic catalog.")
console = Console()

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging() -> logging.Logger:
    """Configure logging to the run log file (DEBUG level)."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("fetch_catalog")
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)

    return logger


log = setup_logging()

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def fetch(
    session: requests.Session,
    url: str,
    *,
    method: str = "GET",
) -> requests.Response | None:
    """Fetch a URL with retries and exponential backoff on 5xx."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.request(method, url, timeout=30)
            if resp.status_code < 500:
                return resp
            log.warning("HTTP %d on %s (attempt %d/%d)", resp.status_code, url, attempt, MAX_RETRIES)
        except requests.RequestException as exc:
            log.warning("Request error on %s (attempt %d/%d): %s", url, attempt, MAX_RETRIES, exc)
        if attempt < MAX_RETRIES:
            time.sleep(2 ** attempt)
    log.error("Giving up on %s after %d attempts", url, MAX_RETRIES)
    return None


def polite_sleep() -> None:
    time.sleep(REQUEST_DELAY)


# ---------------------------------------------------------------------------
# URL / path helpers
# ---------------------------------------------------------------------------


def url_to_path(url: str) -> str:
    """Strip protocol+host, drop leading/trailing slashes."""
    return urlparse(url).path.strip("/")


def url_to_html_path(url: str) -> Path:
    """Map a catalog URL to its local HTML file path."""
    rel = url_to_path(url)
    if not rel:
        return HTML_DIR / "_index.html"
    parts = rel.split("/")
    if parts[-1]:
        return HTML_DIR / "/".join(parts[:-1]) / f"{parts[-1]}.html"
    return HTML_DIR / "/".join(parts[:-1]) / "_index.html"


def url_to_pdf_path(url: str) -> Path:
    """Map a catalog URL to its local PDF file path."""
    rel = url_to_path(url)
    if not rel:
        return PDF_DIR / "_index.pdf"
    parts = rel.split("/")
    if parts[-1]:
        return PDF_DIR / "/".join(parts[:-1]) / f"{parts[-1]}.pdf"
    return PDF_DIR / "/".join(parts[:-1]) / "_index.pdf"


def derive_page_pdf_url(page_url: str) -> str:
    """Derive the per-page PDF URL: <page-url><last-slug>.pdf."""
    path = urlparse(page_url).path.rstrip("/")
    slug = path.split("/")[-1]
    if not slug:
        return ""
    return f"{page_url.rstrip('/')}/{slug}.pdf"


def is_allowed(path: str) -> bool:
    """Check a URL path against the robots.txt disallow list."""
    return not any(path.startswith(d) for d in DISALLOWED_PREFIXES)


def should_keep(url: str) -> bool:
    """Decide if a sitemap URL belongs in our download set."""
    path = urlparse(url).path
    if path in ALLOWED_EXACT:
        return True
    return any(path.startswith(p) for p in ALLOWED_PREFIXES) and is_allowed(path)


# ---------------------------------------------------------------------------
# Sitemap parsing
# ---------------------------------------------------------------------------


def parse_sitemap(xml_bytes: bytes) -> list[str]:
    """Extract <loc> URLs from sitemap XML."""
    root = etree.fromstring(xml_bytes)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    return [loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text]


# ---------------------------------------------------------------------------
# HTML metadata extraction
# ---------------------------------------------------------------------------


def extract_metadata(html_bytes: bytes, page_url: str) -> dict[str, Any]:
    """Extract structured metadata from a catalog HTML page."""
    tree = html.fromstring(html_bytes)

    # Title
    title_el = tree.find(".//title")
    title = title_el.text_content().strip() if title_el is not None else ""
    title = re.sub(r"\s*[|\-\u2013\u2014]\s*La Salle University.*$", "", title).strip()

    # School / breadcrumb
    school = ""
    breadcrumbs = tree.xpath("//ol[contains(@class,'breadcrumb')]/li")
    if not breadcrumbs:
        breadcrumbs = tree.xpath("//*[contains(@class,'breadcrumb')]//li")
    if len(breadcrumbs) >= 3:
        school = breadcrumbs[2].text_content().strip()

    # Catalog edition
    edition = ""
    text = html.tostring(tree, encoding="unicode")
    m = re.search(r"(20\d{2}[-\u2013]20\d{2})\s*(?:Edition|Catalog|Academic Year)", text)
    if m:
        edition = m.group(1).replace("\u2013", "-")

    # Level and program type from URL
    path = urlparse(page_url).path
    level = ""
    program_type = ""
    if path.startswith("/undergraduate/"):
        level = "undergraduate"
    elif path.startswith("/graduate/"):
        level = "graduate"
    parts = [p for p in path.strip("/").split("/") if p]
    if len(parts) >= 2:
        program_type = parts[1]

    # Tabs present
    tabs_present = [
        tid.replace("textcontainer", "")
        for tid in TAB_IDS
        if tree.get_element_by_id(tid, None) is not None
    ]

    # Course codes
    course_codes = sorted(set(re.findall(r"\b([A-Z]{2,4})\s+(\d{3})\b", text)))
    course_codes = [f"{dept} {num}" for dept, num in course_codes]

    return {
        "title": title,
        "school": school,
        "edition": edition,
        "level": level,
        "program_type": program_type,
        "tabs_present": tabs_present,
        "course_codes": course_codes,
    }


# ---------------------------------------------------------------------------
# File I/O with idempotency
# ---------------------------------------------------------------------------


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_if_changed(path: Path, data: bytes) -> tuple[bool, str]:
    """Write data only if content changed. Returns (changed, hash)."""
    h = sha256(data)
    if path.exists():
        if sha256(path.read_bytes()) == h:
            return False, h
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True, h


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


def _append_manifest(record: dict[str, Any]) -> None:
    """Append a single record to manifest.jsonl."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_manifest() -> list[dict[str, Any]]:
    """Load all records from manifest.jsonl."""
    records: list[dict[str, Any]] = []
    if not MANIFEST_PATH.exists():
        return records
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


# ---------------------------------------------------------------------------
# Page processing
# ---------------------------------------------------------------------------


def _process_page(session: requests.Session, url: str, run_id: str) -> dict[str, Any]:
    """Fetch one HTML page and its associated PDF, return a manifest record."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    html_path = url_to_html_path(url)
    record: dict[str, Any] = {
        "run_id": run_id,
        "url": url,
        "html_path": str(html_path.relative_to(DATA_DIR.parent)),
        "pdf_url": "",
        "pdf_path": "",
        "title": "",
        "school": "",
        "program_type": "",
        "level": "",
        "tabs_present": [],
        "course_codes": [],
        "html_sha256": "",
        "pdf_sha256": "",
        "html_status": 0,
        "pdf_status": 0,
        "fetched_at": now,
    }

    # Fetch HTML
    resp = fetch(session, url)
    if resp is None:
        log.error("Failed to fetch HTML: %s", url)
        return record

    record["html_status"] = resp.status_code
    if resp.status_code == 200:
        changed, h = write_if_changed(html_path, resp.content)
        record["html_sha256"] = h
        log.debug("%s HTML: %s", "Wrote" if changed else "Unchanged", html_path)

        meta = extract_metadata(resp.content, url)
        record.update({
            "title": meta["title"],
            "school": meta["school"],
            "program_type": meta["program_type"],
            "level": meta["level"],
            "tabs_present": meta["tabs_present"],
            "course_codes": meta["course_codes"],
        })
    else:
        log.warning("HTTP %d for HTML: %s", resp.status_code, url)

    polite_sleep()

    # Fetch per-page PDF
    pdf_url = derive_page_pdf_url(url)
    if pdf_url:
        record["pdf_url"] = pdf_url
        pdf_path = url_to_pdf_path(url)
        record["pdf_path"] = str(pdf_path.relative_to(DATA_DIR.parent))

        head_resp = fetch(session, pdf_url, method="HEAD")
        if head_resp and head_resp.status_code == 200:
            polite_sleep()
            pdf_resp = fetch(session, pdf_url)
            if pdf_resp and pdf_resp.status_code == 200:
                changed, h = write_if_changed(pdf_path, pdf_resp.content)
                record["pdf_sha256"] = h
                record["pdf_status"] = 200
                log.debug("PDF %s: %s", "wrote" if changed else "unchanged", pdf_path)
            else:
                record["pdf_status"] = pdf_resp.status_code if pdf_resp else 0
                log.warning("PDF GET failed for %s", pdf_url)
        elif head_resp and head_resp.status_code == 404:
            record["pdf_status"] = 404
            log.debug("No PDF (404): %s", pdf_url)
        else:
            record["pdf_status"] = head_resp.status_code if head_resp else 0
            log.warning("PDF HEAD failed for %s", pdf_url)

    return record


def _fetch_catalog_pdf(session: requests.Session, pdf_url: str, run_id: str) -> None:
    """Fetch one of the whole-catalog PDFs."""
    filename = unquote(urlparse(pdf_url).path.split("/")[-1])
    if "Undergraduate" in filename:
        local_name = "2023-2024-undergraduate.pdf"
    elif "Graduate" in filename:
        local_name = "2023-2024-graduate.pdf"
    else:
        local_name = filename.replace(" ", "-").lower()

    local_path = PDF_DIR / "_catalog" / local_name
    local_path.parent.mkdir(parents=True, exist_ok=True)

    resp = fetch(session, pdf_url)
    if resp and resp.status_code == 200:
        changed, h = write_if_changed(local_path, resp.content)
        log.info("Catalog PDF %s: %s (%s)", local_name, "wrote" if changed else "unchanged", h[:12])

        record = {
            "run_id": run_id,
            "url": pdf_url,
            "html_path": "",
            "pdf_url": pdf_url,
            "pdf_path": str(local_path.relative_to(DATA_DIR.parent)),
            "title": f"Full Catalog PDF - {'Undergraduate' if 'Undergraduate' in filename else 'Graduate'}",
            "school": "",
            "program_type": "catalog-pdf",
            "level": "undergraduate" if "Undergraduate" in filename else "graduate",
            "tabs_present": [],
            "course_codes": [],
            "html_sha256": "",
            "pdf_sha256": h,
            "html_status": 0,
            "pdf_status": 200,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _append_manifest(record)
    else:
        log.error("Failed to fetch catalog PDF: %s (status=%s)", pdf_url, resp.status_code if resp else "none")


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@app.command()
def sitemap() -> None:
    """Download and parse the catalog sitemap."""
    session = _session()
    console.print(f"Fetching sitemap from [bold]{SITEMAP_URL}[/bold]")

    resp = fetch(session, SITEMAP_URL)
    if resp is None or resp.status_code != 200:
        console.print("[red]Failed to fetch sitemap.[/red]")
        raise typer.Exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SITEMAP_PATH.write_bytes(resp.content)

    urls = parse_sitemap(resp.content)
    kept = [u for u in urls if should_keep(u)]

    console.print(f"Sitemap saved to [green]{SITEMAP_PATH}[/green]")
    console.print(f"Total URLs in sitemap: [bold]{len(urls)}[/bold]")
    console.print(f"URLs matching our filter: [bold]{len(kept)}[/bold]")


@app.command()
def download() -> None:
    """Fetch HTML pages and per-page PDFs for all filtered URLs."""
    if not SITEMAP_PATH.exists():
        console.print("[red]No sitemap found. Run 'sitemap' first.[/red]")
        raise typer.Exit(1)

    urls = parse_sitemap(SITEMAP_PATH.read_bytes())
    urls = [u for u in urls if should_keep(u)]
    console.print(
        f"Downloading [bold]{len(urls)}[/bold] pages "
        f"(+ per-page PDFs + {len(CATALOG_PDFS)} catalog PDFs)"
    )

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session = _session()

    HTML_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching pages", total=len(urls))
        for url in urls:
            record = _process_page(session, url, run_id)
            _append_manifest(record)
            progress.advance(task)
            polite_sleep()

        pdf_task = progress.add_task("Catalog PDFs", total=len(CATALOG_PDFS))
        for pdf_url in CATALOG_PDFS:
            _fetch_catalog_pdf(session, pdf_url, run_id)
            progress.advance(pdf_task)
            polite_sleep()

    console.print("[green]Download complete.[/green] Run [bold]verify[/bold] to check results.")


@app.command()
def verify() -> None:
    """Verify the latest download run against success criteria."""
    records = _load_manifest()
    if not records:
        console.print("[red]No manifest found. Run 'download' first.[/red]")
        raise typer.Exit(1)

    latest_run = max(r["run_id"] for r in records)
    run_records = [r for r in records if r["run_id"] == latest_run]
    page_records = [r for r in run_records if r["program_type"] != "catalog-pdf"]
    catalog_records = [r for r in run_records if r["program_type"] == "catalog-pdf"]

    # Sitemap count
    sitemap_count = len(parse_sitemap(SITEMAP_PATH.read_bytes())) if SITEMAP_PATH.exists() else 0

    # HTML stats
    html_ok = sum(1 for r in page_records if r.get("html_status") == 200)
    html_total = len(page_records)
    html_rate = html_ok / html_total * 100 if html_total else 0

    # PDF stats
    pdf_attempted = [r for r in page_records if r.get("pdf_url")]
    pdf_ok = sum(1 for r in pdf_attempted if r.get("pdf_status") == 200)
    pdf_404 = sum(1 for r in pdf_attempted if r.get("pdf_status") == 404)
    pdf_rate = pdf_ok / len(pdf_attempted) * 100 if pdf_attempted else 0

    html_failures = [r for r in page_records if r.get("html_status") != 200]
    pdf_failures = [r for r in pdf_attempted if r.get("pdf_status") not in (200, 404)]

    # Build report table
    table = Table(title=f"Verification Report - Run {latest_run}")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_column("Expected")

    sitemap_ok = 340 <= sitemap_count <= 400
    table.add_row(
        "Sitemap URLs",
        f"{'[green]' if sitemap_ok else '[red]'}{sitemap_count}[/]",
        "340-400",
    )
    table.add_row("Pages downloaded", str(html_total), "")

    html_ok_style = "[green]" if html_rate >= 99 else "[red]"
    table.add_row("HTML success rate", f"{html_ok_style}{html_rate:.1f}%[/] ({html_ok}/{html_total})", ">= 99%")

    pdf_ok_style = "[green]" if pdf_rate >= 90 else "[red]"
    table.add_row("PDF success rate", f"{pdf_ok_style}{pdf_rate:.1f}%[/] ({pdf_ok}/{len(pdf_attempted)})", ">= 90%")
    table.add_row("PDF not found (404)", str(pdf_404), "(expected for index pages)")
    table.add_row("PDF other failures", str(len(pdf_failures)), "0")
    table.add_row("Catalog PDFs", str(len(catalog_records)), "2")

    console.print()
    console.print(table)

    # Failures detail
    if html_failures:
        console.print("\n[red]HTML failures:[/red]")
        for r in html_failures:
            console.print(f"  {r['html_status']:>3d}  {r['url']}")

    if pdf_failures:
        console.print("\n[red]PDF failures (non-404):[/red]")
        for r in pdf_failures:
            console.print(f"  {r['pdf_status']:>3d}  {r['pdf_url']}")

    # Overall verdict
    checks_passed = (
        340 <= sitemap_count <= 400
        and html_rate >= 99
        and pdf_rate >= 90
    )
    if checks_passed:
        console.print("\n[bold green]All checks PASSED.[/bold green]")
    else:
        console.print("\n[bold red]Some checks FAILED.[/bold red] Review the output above.")


@app.command()
def clean() -> None:
    """Remove downloaded data. Keeps sitemap.xml."""
    removed: list[str] = []
    for d in [HTML_DIR, PDF_DIR]:
        if d.exists():
            shutil.rmtree(d)
            removed.append(d.name)
    for f in [MANIFEST_PATH, LOG_PATH]:
        if f.exists():
            f.unlink()
            removed.append(f.name)
    if removed:
        console.print(f"Removed: [red]{', '.join(removed)}[/red]")
    else:
        console.print("Nothing to clean.")
    console.print(f"Kept: [green]{SITEMAP_PATH}[/green]")


if __name__ == "__main__":
    app()
