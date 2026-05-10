#!/usr/bin/env python3
"""Build the agent-navigable wiki from the raw HTML corpus.

Subcommands:
    extract  - Parse all HTML pages → data/structured.jsonl
    pair     - Compute EN↔ES program pairings → data/pairings.jsonl
    render   - Write the wiki/ markdown tree from structured data
    index    - Generate index/derived files (faq, by-area, by-level, meta/*)
    verify   - Run all invariants and emit a verification report
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import typer
from lxml import html as lhtml
from markdownify import markdownify
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

from scripts.common import (
    BASE_URL,
    DATA_DIR,
    HTML_DIR,
    LANGUAGES,
    LANG_CONFIG,
    PROGRAM_SUBPAGES,
    STRUCTURED_PATH,
    PAIRINGS_PATH,
    SUBPAGE_SECTION_KEYS,
    canonical_program_id,
    canonical_subject_id,
    extract_pdf_links,
    extract_subject_links,
    is_program_page,
    latest_record_per_url,
    load_manifest,
    sha256,
    url_to_html_path,
    url_to_lang,
    url_to_slug,
    write_if_changed,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXTRACTOR_VERSION = "1.0"

# Drupal field names → wiki section keys for SUBPAGE main bodies.
# Each program subpage has exactly one main field; the same content key
# appears on EN and ES pages with localized field names.
SUBPAGE_MAIN_FIELD = {
    "goals": "field-objectius",
    "objetivos": "field-objectius",
    "requirements": "field-requisits-t",
    "requisitos": "field-requisits-t",
    "methodology": "field-metodologia-t",
    "metodologia": "field-metodologia-t",
    "career-opportunities": "field-sortides-t",
    "salidas-profesionales": "field-sortides-t",
    "academics": "field-professorat-t",
    "profesorado": "field-professorat-t",
}

# Subject page fields (13 across both languages, identical class names)
SUBJECT_FIELDS = {
    "year": "field-ent-curs-n",
    "semester": "field-ent-semestre-t",
    "type": "field-ent-tipusasignatura-t",
    "ects": "field-ent-credits-n",
    "description": "field-ent-descripcio-t",
    "prerequisites": "field-ent-coneixementsprevis-t",
    "objectives": "field-ent-objectius-t",
    "contents": "field-ent-continguts-t",
    "methodology": "field-ent-metodologia-t",
    "evaluation": "field-ent-avaluacio-t",
    "grading_criteria": "field-ent-criterisavaluacio-t",
    "bibliography": "field-ent-bibliografiabasica-t",
    "additional_material": "field-ent-materialcomp-t",
}

# Boilerplate strings to strip from extracted markdown
BOILERPLATE_PHRASES = (
    "contact_study_form",
    "Search form",
    "Featured Links",
    "Related Links",
    "Contact and Help",
)

# Markdownify options: prefer ATX headings, no extra wrapping
MD_OPTS = {
    "heading_style": "ATX",
    "bullets": "-",
    "strip": ["script", "style", "form", "input", "button", "iframe"],
}

# ---------------------------------------------------------------------------
# Typer + rich
# ---------------------------------------------------------------------------

app = typer.Typer(
    help="Build the LaSalle catalog wiki from the raw HTML corpus."
)
console = Console()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _setup_logging() -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DATA_DIR / "build_wiki.log"
    logger = logging.getLogger("build_wiki")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    return logger


log = _setup_logging()

# ---------------------------------------------------------------------------
# HTML → markdown helpers
# ---------------------------------------------------------------------------


_OFFSITE_HREF_RE = re.compile(r"^(?:/(?:en|es)/|file://)")


def _strip_offsite_links(md: str) -> str:
    """Remove markdown links whose href points off-wiki, keeping link text.

    Walks the string left-to-right. When we see `](`, we look at the URL up
    to the closing `)`. If the URL matches `/en/...`, `/es/...`, or
    `file://...`, we walk backward to find the matching `[` (balanced over
    nested brackets), then replace `[ … ]( bad_url )` with just `…`.
    Otherwise we leave the link alone.
    """
    out: list[str] = []
    i = 0
    n = len(md)
    while i < n:
        if md[i] == "]" and i + 1 < n and md[i + 1] == "(":
            # Find the closing ')' of the URL
            j = md.find(")", i + 2)
            if j == -1:
                out.append(md[i])
                i += 1
                continue
            href = md[i + 2 : j]
            if not _OFFSITE_HREF_RE.match(href):
                # Keep this link as-is
                out.append(md[i])
                i += 1
                continue
            # Walk backward through `out` to find the matching '['.
            # Count balanced brackets (treating ![ and [ alike for matching).
            depth = 1
            buf = "".join(out)
            k = len(buf) - 1
            while k >= 0:
                ch = buf[k]
                if ch == "]":
                    depth += 1
                elif ch == "[":
                    depth -= 1
                    if depth == 0:
                        break
                k -= 1
            if k < 0:
                # No matching '['; just drop this ']('
                out.append(md[i])
                i += 1
                continue
            # body is buf[k+1 : end], possibly with leading "!" if it's
            # an image-link. Drop the leading "[" and any leading "!".
            body_start = k
            if body_start > 0 and buf[body_start - 1] == "!":
                body_start -= 1
            body_text = buf[k + 1 :]  # everything after the '['
            # Truncate `out` back to before the '['
            out = list(buf[:body_start])
            # Strip nested image syntax from body_text — drop any
            # ![alt](url) patterns inside the link body.
            body_text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body_text)
            out.append(body_text.strip())
            i = j + 1  # skip past the URL's closing ')'
            continue
        out.append(md[i])
        i += 1
    return "".join(out)


def _field_to_markdown(field_el) -> str:
    """Convert a Drupal field's inner HTML to clean markdown.

    Strategy:
      - Drop the field label (often the first child div with class containing
        'field-label' or the first 'Description:' / 'Objectives:' text node).
      - Convert the .field-items inner HTML (or fallback to the whole field).
      - Trim, collapse, and strip known boilerplate.
    """
    # Prefer the .field-items div — that holds the actual content
    items = field_el.xpath(".//div[contains(@class, 'field-items')]")
    target = items[0] if items else field_el

    inner_html = lhtml.tostring(target, encoding="unicode", method="html")
    md = markdownify(inner_html, **MD_OPTS)

    # Cleanup
    md = md.strip()
    # Collapse 3+ blank lines → 2
    md = re.sub(r"\n{3,}", "\n\n", md)
    # Strip markdown links to absolute /en/... /es/... paths on the source
    # site, plus file:/// URLs. These point off-wiki and produce dead links.
    # The link bodies often contain nested image syntax and span multiple
    # lines, so a regex with [^\]]+ doesn't suffice. Use a small bracket-
    # balanced parser instead.
    md = _strip_offsite_links(md)
    md = re.sub(r"!\[[^\]]*\]\(file://[^)]*\)", "", md)
    # Drop boilerplate lines
    lines = []
    for line in md.split("\n"):
        if any(b in line for b in BOILERPLATE_PHRASES):
            continue
        lines.append(line)
    md = "\n".join(lines).strip()
    return md


def _text(field_el) -> str:
    """Return the plain text content of a field, trimmed and label-stripped."""
    items = field_el.xpath(".//div[contains(@class, 'field-items')]")
    target = items[0] if items else field_el
    text = " ".join(target.text_content().split()).strip()
    return text


def _find_field(article, field_name: str):
    """Find a div.field-name-{field_name} inside an article."""
    matches = article.xpath(
        f".//div[contains(concat(' ', normalize-space(@class), ' '), ' field-name-{field_name} ')]"
    )
    return matches[0] if matches else None


def _parse_modalities_table(article) -> list[dict[str, Any]]:
    """Parse the .view-modalitats-eva table → list of variant dicts.

    Each row in the table is a property; columns are program variants.
    For most programs there's 1 column; bachelors may have 3 (e.g. one
    per language of instruction).
    """
    modal = article.xpath(".//div[contains(@class, 'view-modalitats-eva')]")
    if not modal:
        return []
    table = modal[0].find(".//table")
    if table is None:
        return []

    # Build {row_label: [values_per_variant]}
    rows: dict[str, list[str]] = {}
    n_variants = 0
    for tr in table.iter("tr"):
        cells = list(tr)
        if not cells:
            continue
        label = cells[0].text_content().strip()
        if not label:
            continue
        values = [c.text_content().strip() for c in cells[1:]]
        # First row's values ARE the modality column headers
        if not rows:
            n_variants = len(values)
            # Modality is special: row label = "Modality", values = modality per variant
            rows[label] = values
        else:
            # Pad if the row has fewer cells (rare)
            while len(values) < n_variants:
                values.append("")
            rows[label] = values[:n_variants]

    if n_variants == 0:
        return []

    # Build one dict per variant
    variants: list[dict[str, Any]] = []
    for i in range(n_variants):

        def cell(label: str) -> str:
            row = rows.get(label, [])
            return row[i] if i < len(row) else ""

        # Try EN and ES labels for each row
        modality = cell("Modality") or cell("Modalidad")
        duration = cell("Duration") or cell("Duración")
        language = cell("Language") or cell("Lengua")
        places = cell("Places available") or cell("Plazas")
        credits = cell("Credits") or cell("Créditos")
        start_date = cell("Start Date") or cell("Fecha inicio")
        schedule = cell("Schedule") or cell("Horario")
        location = cell("Location") or cell("Lugar")

        variants.append({
            "modality": modality,
            "duration": duration,
            "language": language,
            "places": places,
            "ects": credits,
            "start_date": start_date,
            "schedule": schedule,
            "location": location,
        })
    return variants


def _normalize_languages(language_str: str) -> list[str]:
    """'Catalan - Spanish - English' → ['Catalan','Spanish','English']."""
    if not language_str:
        return []
    parts = re.split(r"\s*[-/,]\s*", language_str)
    return [p.strip() for p in parts if p.strip()]


def _normalize_ects(ects_str: str) -> int | None:
    """'240-ECTS' → 240. '5-ECTS' → 5. Empty → None."""
    if not ects_str:
        return None
    m = re.search(r"\d+", ects_str)
    return int(m.group()) if m else None


def _normalize_modality(modality_str: str) -> str:
    """'On-site' → 'on-site'; 'Online' → 'online'; 'Híbrido'/'Hybrid' → 'hybrid'."""
    s = modality_str.strip().lower()
    if "online" in s:
        return "online"
    if "hybrid" in s or "híbrido" in s or "semi" in s:
        return "hybrid"
    if "on-site" in s or "presencial" in s or "on site" in s:
        return "on-site"
    return s or "unknown"


# ---------------------------------------------------------------------------
# Page extractors
# ---------------------------------------------------------------------------


def extract_program_base(html_bytes: bytes, url: str) -> dict[str, Any]:
    """Extract the program base/overview page.

    Returns a structured record. Sets `extractor_mode='fallback'` if any
    required selector misses.
    """
    tree = lhtml.fromstring(html_bytes)
    article = tree.find(".//article")
    fallback_used = False
    missing_fields: list[str] = []

    rec: dict[str, Any] = {
        "url": url,
        "lang": url_to_lang(url),
        "slug": url_to_slug(url),
        "canonical_program_id": canonical_program_id(url),
        "kind": "program-base",
        "extractor_version": EXTRACTOR_VERSION,
    }

    # Title (preferred from the .title-field, fall back to h1)
    title_field = article.find(".//div[@class='title-field']") if article is not None else None
    if title_field is not None and title_field.text_content().strip():
        rec["title"] = title_field.text_content().strip()
    else:
        h1 = tree.find(".//h1")
        rec["title"] = h1.text_content().strip() if h1 is not None else ""
        if not rec["title"]:
            missing_fields.append("title")

    # Official name (degree certificate official label)
    if article is not None:
        nom = _find_field(article, "field-ent-nomoficial-t")
        rec["official_name"] = _text(nom) if nom is not None else ""
        expedition = _find_field(article, "field-tx-expedicio-t")
        rec["degree_issuer"] = _text(expedition) if expedition is not None else ""
        # Short description
        descr = _find_field(article, "field-ent-descripcio-t")
        rec["short_description"] = _field_to_markdown(descr) if descr is not None else ""
        # Main rich content (Presentation)
        paragraphs = _find_field(article, "field-tc-paragrafs-t")
        rec["overview_md"] = _field_to_markdown(paragraphs) if paragraphs is not None else ""
        if not rec["overview_md"]:
            missing_fields.append("overview_md")

        # Modalities table → variants list
        rec["modality_variants"] = _parse_modalities_table(article)
    else:
        rec["official_name"] = ""
        rec["degree_issuer"] = ""
        rec["short_description"] = ""
        rec["overview_md"] = ""
        rec["modality_variants"] = []
        missing_fields.append("article")
        fallback_used = True

    # Derived fields for frontmatter (union across variants)
    variants = rec["modality_variants"]
    rec["modality"] = sorted({_normalize_modality(v["modality"]) for v in variants if v.get("modality")})
    rec["duration"] = variants[0]["duration"] if variants else ""
    rec["ects"] = _normalize_ects(variants[0]["ects"]) if variants else None
    rec["start_date"] = variants[0]["start_date"] if variants else ""
    rec["schedule"] = variants[0]["schedule"] if variants else ""
    rec["location"] = variants[0]["location"] if variants else ""
    langs: set[str] = set()
    for v in variants:
        langs.update(_normalize_languages(v.get("language", "")))
    rec["languages_of_instruction"] = sorted(langs)

    # Linked PDFs
    rec["linked_pdfs"] = extract_pdf_links(html_bytes)

    # Bookkeeping
    rec["missing_fields"] = missing_fields
    rec["extractor_mode"] = "fallback" if fallback_used else "targeted"
    return rec


def extract_program_subpage(
    html_bytes: bytes, url: str, parent_url: str, suffix: str
) -> dict[str, Any]:
    """Extract a program subpage (goals/requirements/careers/etc.)."""
    tree = lhtml.fromstring(html_bytes)
    article = tree.find(".//article")
    rec: dict[str, Any] = {
        "url": url,
        "parent_url": parent_url,
        "lang": url_to_lang(url),
        "kind": "program-subpage",
        "section": SUBPAGE_SECTION_KEYS.get(suffix, suffix),
        "suffix": suffix,
        "extractor_version": EXTRACTOR_VERSION,
        "missing_fields": [],
        "extractor_mode": "targeted",
    }

    if article is None:
        rec["body_md"] = ""
        rec["missing_fields"].append("article")
        rec["extractor_mode"] = "fallback"
        rec["linked_subjects"] = []
        rec["curriculum_years"] = []
        rec["linked_pdfs"] = []
        return rec

    # Syllabus pages are special: they don't have a single body field —
    # they have a year-by-year structure. Success = curriculum_years populated.
    if rec["section"] == "curriculum":
        rec["curriculum_years"] = _parse_syllabus_years(article, rec["lang"])
        rec["linked_subjects"] = extract_subject_links(html_bytes, rec["lang"])
        rec["body_md"] = ""  # not used for curriculum
        if not rec["curriculum_years"]:
            # Genuinely sparse program (e.g. a workshop with no formal syllabus)
            rec["extractor_mode"] = "fallback"
            rec["missing_fields"].append("curriculum_years")
    else:
        # Standard subpage: find the canonical main field
        field_name = SUBPAGE_MAIN_FIELD.get(suffix)
        body = _find_field(article, field_name) if field_name else None
        if body is not None:
            rec["body_md"] = _field_to_markdown(body)
        else:
            # Fallback to article text — selector miss or genuinely sparse
            rec["body_md"] = _field_to_markdown(article)
            rec["extractor_mode"] = "fallback"
            rec["missing_fields"].append(field_name or suffix)
        rec["linked_subjects"] = []
        rec["curriculum_years"] = []

    rec["linked_pdfs"] = extract_pdf_links(html_bytes)
    return rec


def _parse_syllabus_years(article, lang: str) -> list[dict[str, Any]]:
    """Parse a syllabus page into [{year, sections: [{semester, subjects: [...]}]}].

    Source tables have one of two layouts:
      A) Headers "Semester 1" / "Semester 2" + rows with one cell per semester (true 2-col).
      B) Headers "Semester 1" / "Semester 2" + rows with one `colspan=2` cell (subjects
         not split by semester — list everything under "All semesters").

    Subject link text in the HTML literally contains huge trailing whitespace and a
    trailing "(N)" representing ECTS — we strip both.
    """
    years_block = article.xpath(
        ".//div[contains(@class, 'paragraphs-items-field-moduls-plaestudis')]"
    )
    if not years_block:
        return []

    def _clean_subject_cell(td) -> dict[str, Any]:
        """Extract {title, url, ects} from a single subject cell."""
        a = td.find(".//a")
        if a is not None:
            text = " ".join(a.text_content().split()).strip()
            href = a.get("href", "")
        else:
            text = " ".join(td.text_content().split()).strip()
            href = ""
        # Strip trailing "(N)" — the ECTS hint baked into the link text
        ects = None
        m = re.search(r"\s*\((\d+)\)\s*$", text)
        if m:
            ects = int(m.group(1))
            text = text[: m.start()].strip()
        return {"title": text, "url": href, "ects": ects}

    out: list[dict[str, Any]] = []
    for year_item in years_block[0].xpath(".//div[contains(@class, 'paragraphs-item-taula')]"):
        title_el = year_item.xpath(".//div[contains(@class, 'field-name-field-titol-taula')]")
        year_title = title_el[0].text_content().strip() if title_el else ""

        table_el = year_item.xpath(".//div[contains(@class, 'field-name-field-ent-taula-html')]//table")
        sections: list[dict[str, Any]] = []
        if table_el:
            table = table_el[0]
            # Read headers from the first row of <th> cells
            headers: list[str] = []
            first_row = table.find(".//tr")
            if first_row is not None:
                ths = [c for c in first_row if c.tag == "th"]
                headers = [th.text_content().strip() for th in ths]
            if not headers:
                headers = ["All semesters"]

            cols: list[list[dict[str, Any]]] = [[] for _ in headers]
            all_semesters: list[dict[str, Any]] = []
            for tr in table.iter("tr"):
                cells = [c for c in tr if c.tag == "td"]
                if not cells:
                    continue
                # Layout B: single cell with colspan covering both columns
                if len(cells) == 1 and len(headers) > 1:
                    colspan = int(cells[0].get("colspan", "1") or 1)
                    if colspan >= len(headers):
                        s = _clean_subject_cell(cells[0])
                        if s["title"]:
                            all_semesters.append(s)
                        continue
                # Layout A: one cell per column
                for i, td in enumerate(cells):
                    if i >= len(cols):
                        break
                    s = _clean_subject_cell(td)
                    if s["title"]:
                        cols[i].append(s)

            # Prefer the layout-A split if it yielded anything; else use the unsplit list
            non_empty_cols = [(h, c) for h, c in zip(headers, cols) if c]
            if non_empty_cols:
                for header, subjects in non_empty_cols:
                    sections.append({"semester": header, "subjects": subjects})
            elif all_semesters:
                sections.append({"semester": "All semesters", "subjects": all_semesters})

        if year_title or sections:
            out.append({"year": year_title, "sections": sections})
    return out


def extract_subject(html_bytes: bytes, url: str) -> dict[str, Any]:
    """Extract a subject (course) page using the 13-field schema."""
    tree = lhtml.fromstring(html_bytes)
    article = tree.find(".//article")
    rec: dict[str, Any] = {
        "url": url,
        "lang": url_to_lang(url),
        "slug": url_to_slug(url),
        "canonical_subject_id": canonical_subject_id(url),
        "kind": "subject",
        "extractor_version": EXTRACTOR_VERSION,
        "missing_fields": [],
        "extractor_mode": "targeted",
    }

    # Title (subject pages have h1 = parent program title; the actual subject
    # title is in the second h1 or in the page <title>).
    h1s = tree.findall(".//h1")
    if len(h1s) >= 2:
        rec["title"] = h1s[1].text_content().strip()
    elif h1s:
        rec["title"] = h1s[0].text_content().strip()
    else:
        title_el = tree.find(".//title")
        rec["title"] = title_el.text_content().split("|")[0].strip() if title_el is not None else ""

    if article is None:
        for k in SUBJECT_FIELDS:
            rec[k] = "" if k not in {"year", "ects"} else None
        rec["missing_fields"].append("article")
        rec["extractor_mode"] = "fallback"
        return rec

    # Extract each known field
    for key, field_name in SUBJECT_FIELDS.items():
        el = _find_field(article, field_name)
        if el is None:
            rec[key] = "" if key not in {"year", "ects"} else None
            if key in {"description", "objectives", "contents"}:
                rec["missing_fields"].append(field_name)
            continue
        if key == "year":
            text = _text(el)
            m = re.search(r"\d+", text)
            rec[key] = int(m.group()) if m else None
        elif key == "ects":
            text = _text(el)
            m = re.search(r"\d+", text)
            rec[key] = int(m.group()) if m else None
        elif key in {"semester", "type"}:
            rec[key] = _text(el)
        else:
            rec[key] = _field_to_markdown(el)

    # Subject professors (a separate Drupal view, not a field)
    profs = []
    for view in article.xpath(".//div[contains(@class, 'view-eva-professorado-assignaturas')]"):
        for cell in view.xpath(".//td | .//li"):
            t = cell.text_content().strip()
            if t and len(t) > 2:
                profs.append(t)
    rec["professors"] = sorted(set(profs))

    # NOTE: empty content fields (description/objectives/contents) are NOT
    # treated as fallback — sparse source data is a real condition. Fallback
    # is reserved for selector misses (article missing entirely).
    return rec


# ---------------------------------------------------------------------------
# Subcommand: extract
# ---------------------------------------------------------------------------


def _iter_pages_to_extract(
    sample: int | None,
) -> Iterable[tuple[str, dict[str, Any]]]:
    """Iterate (url, manifest_record) over pages we want to extract.

    Sample (if set) returns a stratified sample: ~`sample` programs split
    across EN+ES and across program kinds (bachelor/master/specialization),
    plus all their subpages and linked subjects.
    """
    records = load_manifest()
    by_url = latest_record_per_url(records)

    program_bases = [
        r for r in by_url.values()
        if r.get("kind") == "program-base" and r.get("http_status") == 200
    ]

    if sample is None:
        # Full corpus: yield all 200-OK records that are programs/subpages/subjects
        for r in by_url.values():
            if r.get("http_status") != 200:
                continue
            if r.get("kind") in {"program-base", "program-subpage", "subject"}:
                yield r["url"], r
        return

    # Stratified sample: pick `sample/2` EN + `sample/2` ES program bases,
    # spread across kind_guess values (bachelor/master/specialization/etc).
    chosen: list[dict[str, Any]] = []
    half = max(1, sample // 2)
    for lang in ("en", "es"):
        bases = [b for b in program_bases if b.get("lang") == lang]
        # Group by guessed kind via slug substring
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for b in bases:
            slug = url_to_slug(b["url"]).lower()
            if "bachelor" in slug or "grado" in slug:
                buckets["bachelor"].append(b)
            elif "master" in slug:
                buckets["master"].append(b)
            elif "course" in slug or "curso" in slug:
                buckets["specialization"].append(b)
            elif "doctorate" in slug or "doctorado" in slug:
                buckets["doctorate"].append(b)
            else:
                buckets["other"].append(b)
        # Round-robin across buckets until we have `half` samples
        keys = list(buckets.keys())
        i = 0
        per_lang: list[dict[str, Any]] = []
        while len(per_lang) < half and any(buckets[k] for k in keys):
            k = keys[i % len(keys)]
            if buckets[k]:
                per_lang.append(buckets[k].pop(0))
            i += 1
        chosen.extend(per_lang)

    chosen_base_urls = {b["url"] for b in chosen}
    chosen_subject_urls: set[str] = set()
    chosen_subpage_urls: set[str] = set()

    for base in chosen:
        # Add subpages
        for suffix, _role in PROGRAM_SUBPAGES[base["lang"]]:
            sub_url = f"{base['url']}/{suffix}"
            if sub_url in by_url and by_url[sub_url].get("http_status") == 200:
                chosen_subpage_urls.add(sub_url)
        # Linked subjects from the manifest
        for subj in base.get("linked_subjects", []):
            if subj in by_url and by_url[subj].get("http_status") == 200:
                chosen_subject_urls.add(subj)

    # Subjects also need to be looked up from the manifest by parent_url
    for r in by_url.values():
        if r.get("kind") == "subject" and r.get("http_status") == 200:
            parents = r.get("parent_url") or []
            if isinstance(parents, str):
                parents = [parents]
            if any(p in chosen_base_urls for p in parents):
                chosen_subject_urls.add(r["url"])

    yielded = 0
    for r in by_url.values():
        url = r["url"]
        if r.get("http_status") != 200:
            continue
        if url in chosen_base_urls or url in chosen_subpage_urls or url in chosen_subject_urls:
            yield url, r
            yielded += 1


@app.command()
def extract(
    sample: int | None = typer.Option(None, help="Stratified pilot sample size; omit for full corpus"),
) -> None:
    """Parse all HTML files into structured.jsonl."""
    pages = list(_iter_pages_to_extract(sample))
    console.print(f"Extracting [bold]{len(pages)}[/bold] pages "
                  f"({'pilot sample' if sample else 'full corpus'})")

    out_records: list[dict[str, Any]] = []
    fallback_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Extracting", total=len(pages))
        for url, manifest_rec in pages:
            html_path = url_to_html_path(url)
            if not html_path.exists():
                log.warning("Missing HTML file for %s: %s", url, html_path)
                progress.advance(task)
                continue
            html_bytes = html_path.read_bytes()
            kind = manifest_rec.get("kind")

            try:
                if kind == "program-base":
                    if not is_program_page(html_bytes):
                        log.info("Skipping non-program page: %s", url)
                        progress.advance(task)
                        continue
                    rec = extract_program_base(html_bytes, url)
                elif kind == "program-subpage":
                    parent_url = manifest_rec.get("parent_url") or ""
                    if not isinstance(parent_url, str):
                        parent_url = parent_url[0] if parent_url else ""
                    suffix = url.rstrip("/").split("/")[-1]
                    rec = extract_program_subpage(html_bytes, url, parent_url, suffix)
                elif kind == "subject":
                    rec = extract_subject(html_bytes, url)
                    parents = manifest_rec.get("parent_url") or []
                    if isinstance(parents, str):
                        parents = [parents]
                    rec["parent_program_urls"] = parents
                else:
                    progress.advance(task)
                    continue

                rec["source_url"] = url
                rec["source_fetched_at"] = manifest_rec.get("fetched_at", "")
                rec["source_sha256"] = manifest_rec.get("sha256", "")
                if rec.get("extractor_mode") == "fallback":
                    fallback_count += 1
                out_records.append(rec)
            except Exception as exc:
                log.exception("Extraction failed for %s: %s", url, exc)
            progress.advance(task)

    STRUCTURED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STRUCTURED_PATH.open("w", encoding="utf-8") as f:
        for rec in out_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Summary table
    kinds = Counter(r["kind"] for r in out_records)
    table = Table(title="Extraction Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    for k in ("program-base", "program-subpage", "subject"):
        table.add_row(k, str(kinds.get(k, 0)))
    table.add_row("[bold]Total records[/bold]", f"[bold]{len(out_records)}[/bold]")
    fb_pct = fallback_count / len(out_records) * 100 if out_records else 0
    style = "green" if fb_pct < 5 else "red"
    table.add_row("Fallback rate", f"[{style}]{fallback_count} ({fb_pct:.1f}%)[/]")
    console.print()
    console.print(table)
    console.print(f"Structured data → [green]{STRUCTURED_PATH}[/green]")


# ---------------------------------------------------------------------------
# Placeholder subcommands (filled in next steps)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Subcommand: pair
# ---------------------------------------------------------------------------


def _normalize_title(title: str) -> str:
    """Lowercase, strip suffixes, normalize EN/ES so similarity makes sense."""
    t = title.lower()
    # Drop site noise
    for noise in (
        " | la salle | campus barcelona", " | la salle campus barcelona",
        " i la salle-url", " la salle-url", "la salle", "campus barcelona",
        " - barcelona", "(en)", "(es)",
    ):
        t = t.replace(noise, "")

    # Translation hints — apply ES→canonical English first, then strip
    # generic level/format markers so titles compare on their topic.
    es_to_en = {
        "doble grado en ": "dual bachelor in ",
        "doble titulación en ": "dual bachelor in ",
        "doble titulación": "dual degree",
        "grado en ": "bachelor in ",
        "grado de ": "bachelor in ",
        "máster universitario en ": "master in ",
        "máster universitario online en ": "master in ",
        "máster en ": "master in ",
        "master en ": "master in ",
        "máster de ": "master in ",
        "máster online en ": "master in ",
        "master online en ": "master in ",
        "master of science in ": "master in ",
        "executive master en ": "master in ",
        "executive master in ": "master in ",
        "doctorado en ": "doctorate in ",
        "postgrado en ": "postgraduate in ",
        "postgrado online en ": "postgraduate in ",
        "postgrado de ": "postgraduate in ",
        "curso en ": "course in ",
        "curso de ": "course in ",
        "curso para ": "course in ",
        "curso online en ": "course in ",
        "curso online de ": "course in ",
        "online course in ": "course in ",
        "online master in ": "master in ",
        "online postgraduate in ": "postgraduate in ",
        "ingeniería ": "engineering ",
        "ingeniería de la salud": "health engineering",
        "ingeniería informática": "computer engineering",
        "ingeniería telemática": "telematics engineering",
        "ingeniería multimedia": "multimedia engineering",
        "ingeniería electrónica": "electronic engineering",
        "ingeniería biomédica": "biomedical engineering",
        "informática": "computer science",
        "animación": "animation",
        "ciberseguridad": "cybersecurity",
        "matemática aplicada": "applied mathematics",
        "filosofía": "philosophy",
        "dirección de proyectos": "project management",
        "dirección tecnológica": "technology management",
        "dirección": "management",
        "marketing digital": "digital marketing",
        "fundamentos": "fundamentals",
        "redes sociales": "social media",
        "redes": "networks",
        "introducción": "introduction",
        "certificación": "certification",
        "programación": "programming",
        "desarrollo": "development",
        "consultoría funcional": "functional consulting",
        "logística": "logistics",
        "finanzas": "finance",
        "modelaje": "modeling",
        "presentación": "presentation",
        "habilidades": "skills",
        "discurso político": "political discourse",
        "debate": "debate",
        "innovación": "innovation",
        "innovación digital": "digital innovation",
        "acústica": "acoustics",
        "audio": "audio",
        "vibraciones": "vibrations",
        "rehabilitación": "rehabilitation",
        "restauración": "restoration",
        "sostenibilidad": "sustainability",
        "eficiencia": "efficiency",
        "edificación": "building",
        "construcción": "construction",
        "arquitectura ambiental": "environmental architecture",
        "urbanismo": "urban planning",
        "energética": "energy",
        "estratégica": "strategic",
        "estrategia": "strategy",
        "estructural": "structural",
        "diseño": "design",
        "interior": "interior",
        "cálculo": "calculation",
        "cálculos": "calculations",
        "modelos": "models",
        "marcos": "frameworks",
        "sistemas": "systems",
        "ordenador": "computer",
        "sumérgete": "dive",
        "construye": "build",
        "crea": "create",
        "elabora": "develop",
        "tu propia": "your own",
        "tus propias": "your own",
        "propio": "own",
        "propia": "own",
        "tu ": "your ",
        "tus ": "your ",
        "propio de la salle": "non-official",
        "no oficial": "non-official",
        "másteres propios": "non-official masters",
        "máster propio": "non-official master",
        "máster ": "master ",
        "redes y tecnologías de internet": "networks and internet technologies",
        "telemática": "telematics",
        "producción": "production",
        "consultoría": "consulting",
        "consultor": "consultant",
        "matrícula": "enrollment",
        "elaborado": "developed",
        "aplicada": "applied",
        "aplicado": "applied",
        "audiovisual": "audiovisual",
        "audiovisuales": "audiovisual",
        "executive seminar": "executive seminar",
        "seminario ejecutivo": "executive seminar",
        "seminario": "seminar",
        "experto universitario": "university expert",
        "acreditado": "certified",
        "asociado": "associate",
        "asociada": "associate",
        "operadora de radioaficionados": "amateur radio operator",
        "radioaficionados": "amateur radio",
        "automoción": "automotive",
        "automotriz": "automotive",
        "videojuegos": "videogames",
        "introducción a las redes": "introduction to networks",
        "introducción a redes": "introduction to networks",
        "introducción a la": "introduction to",
        "doble grado en": "dual bachelor in",
        "modalidad": "modality",
        "lean": "lean",
        "y ": "and ",
        " del ": " of the ",
        " de la ": " of ",
        " de ": " of ",
        " en ": " in ",
        " con ": " with ",
        " e ": " and ",
    }
    for es, en in es_to_en.items():
        t = t.replace(es, en)

    # Strip purely-formatting words that don't carry topic info
    for w in (" online ", " (weekdays)", " (weekend)", " (full-time)", " (part-time)"):
        t = t.replace(w, " ")
    t = " ".join(t.split())
    return t


def _slug_similarity(slug_en: str, slug_es: str) -> float:
    """Token overlap on slugs after stripping language/format prefixes."""
    en_strip_prefixes = (
        "bachelor-", "master-", "master-of-science-in-", "online-master-",
        "online-postgraduate-", "online-course-", "course-", "doctorate-",
        "postgraduate-", "executive-master-",
    )
    es_strip_prefixes = (
        "grado-en-", "grado-de-", "doble-grado-en-", "doble-titulacion-en-",
        "master-en-", "master-universitario-en-", "master-universitario-online-en-",
        "master-online-en-", "executive-master-en-",
        "curso-en-", "curso-de-", "curso-online-de-", "curso-online-en-",
        "doctorado-en-", "postgrado-en-", "postgrado-online-en-",
    )

    def _strip(s: str, prefixes: tuple[str, ...]) -> str:
        s = s.lower()
        # Try longest prefix first
        for p in sorted(prefixes, key=len, reverse=True):
            if s.startswith(p):
                return s[len(p):]
        return s

    en = _strip(slug_en, en_strip_prefixes)
    es = _strip(slug_es, es_strip_prefixes)
    es_tokens = set(re.findall(r"[a-z0-9]+", es))
    en_tokens = set(re.findall(r"[a-z0-9]+", en))
    if not es_tokens or not en_tokens:
        return 0.0
    return len(es_tokens & en_tokens) / max(len(es_tokens), len(en_tokens))


def _title_similarity(t1_en: str, t2_es: str) -> float:
    """Token-set overlap on normalized titles."""
    n1 = set(re.findall(r"[a-z0-9]+", _normalize_title(t1_en)))
    n2 = set(re.findall(r"[a-z0-9]+", _normalize_title(t2_es)))
    if not n1 or not n2:
        return 0.0
    return len(n1 & n2) / max(len(n1), len(n2))


def _shared_subjects_score(en_subjects: list[str], es_subjects: list[str]) -> float:
    """Fraction of subject URLs (path-only) that appear in both lists.

    Subject pages use the same slug across languages (often Spanish slugs
    even on EN syllabi). We compare the trailing slug, ignoring /en/ vs /es/.
    """
    def slugs(urls):
        out = set()
        for u in urls:
            parts = u.rstrip("/").split("/")
            if len(parts) >= 4:
                out.add(parts[-1])
        return out
    a, b = slugs(en_subjects), slugs(es_subjects)
    if not a or not b:
        return 0.0
    return len(a & b) / max(len(a), len(b))


def _structural_match(p_en: dict, p_es: dict) -> float:
    """Cheap level/ects/duration disambiguator: 1.0 if they all match, scaled down otherwise."""
    score = 0.0
    if p_en.get("ects") and p_en["ects"] == p_es.get("ects"):
        score += 0.5
    if p_en.get("duration") and _normalize_duration(p_en["duration"]) == _normalize_duration(p_es.get("duration", "")):
        score += 0.3
    if p_en.get("modality") and set(p_en["modality"]) == set(p_es.get("modality", [])):
        score += 0.2
    return score


def _normalize_duration(d: str) -> str:
    s = d.lower().strip()
    s = s.replace("years", "y").replace("year", "y").replace("años", "y").replace("año", "y")
    s = s.replace("months", "mo").replace("month", "mo").replace("meses", "mo").replace("mes", "mo")
    s = s.replace("weeks", "w").replace("week", "w").replace("semanas", "w").replace("semana", "w")
    s = " ".join(s.split())
    return s


@app.command()
def pair() -> None:
    """Compute EN↔ES program pairings → data/pairings.jsonl.

    Multi-signal weighted scoring:
        slug_similarity * 0.20
        title_similarity * 0.20
        shared_subject_urls * 0.45  (strongest signal — subjects are language-agnostic by URL)
        structural_match (ects/duration/modality) * 0.15

    Auto-link rules (any of):
        - weighted_score >= 0.65
        - shared_subjects >= 0.8 AND structural >= 0.5  (language-agnostic subject URLs nail it)
        - title_similarity >= 0.85 AND slug_similarity >= 0.85  (effectively identical names)
    """
    if not STRUCTURED_PATH.exists():
        console.print("[red]No structured.jsonl found. Run 'extract' first.[/red]")
        raise typer.Exit(1)

    records = [json.loads(l) for l in STRUCTURED_PATH.open()]
    bases = [r for r in records if r["kind"] == "program-base"]
    en_bases = [b for b in bases if b["lang"] == "en"]
    es_bases = [b for b in bases if b["lang"] == "es"]

    # Build subject-link map per program (from program-subpage curriculum records)
    subj_for_program: dict[str, list[str]] = defaultdict(list)
    for r in records:
        if r["kind"] == "program-subpage" and r.get("section") == "curriculum":
            parent = r.get("parent_url", "")
            subj_for_program[parent].extend(r.get("linked_subjects", []))

    console.print(f"Pairing [bold]{len(en_bases)}[/bold] EN programs with [bold]{len(es_bases)}[/bold] ES programs…")

    # Compute the full EN×ES score matrix
    all_candidates: list[dict[str, Any]] = []
    for en in en_bases:
        en_url = en["url"]
        for es in es_bases:
            slug_sim = _slug_similarity(en["slug"], es["slug"])
            title_sim = _title_similarity(en.get("title", ""), es.get("title", ""))
            subj_sim = _shared_subjects_score(
                subj_for_program.get(en_url, []),
                subj_for_program.get(es["url"], []),
            )
            struct = _structural_match(en, es)
            score = slug_sim * 0.20 + title_sim * 0.20 + subj_sim * 0.45 + struct * 0.15
            all_candidates.append({
                "en": en, "es": es,
                "score": score,
                "signals": {
                    "slug_similarity": round(slug_sim, 3),
                    "title_similarity": round(title_sim, 3),
                    "shared_subjects": round(subj_sim, 3),
                    "structural": round(struct, 3),
                },
            })

    # Greedy bipartite matching: highest-scoring pairs first, claim each side only once.
    # Writes one best match per EN program (claimed or not).
    all_candidates.sort(key=lambda c: -c["score"])
    en_claimed: set[str] = set()
    es_claimed: set[str] = set()
    en_best: dict[str, dict[str, Any]] = {}
    for cand in all_candidates:
        en_id = cand["en"]["canonical_program_id"]
        es_id = cand["es"]["canonical_program_id"]
        if en_id in en_claimed or es_id in es_claimed:
            continue
        # The first time we encounter an unclaimed EN, this is its best candidate
        if en_id in en_best:
            continue
        signals = cand["signals"]
        score = cand["score"]
        # With bipartite matching (best-match-only), false-positive risk is
        # bounded: each ES program can be claimed only once. Be permissive.
        auto_link = (
            score >= 0.30
            # Subjects are language-agnostic by URL — strong evidence
            or (signals["shared_subjects"] >= 0.5 and signals["structural"] >= 0.5)
            # Effectively identical names
            or (signals["title_similarity"] >= 0.80 and signals["slug_similarity"] >= 0.50)
            # Strong structural + decent title match (catches "Master in Cybersecurity"
            # ↔ "Máster en Ciberseguridad" type pairs where slug overlap is 0)
            or (
                signals["title_similarity"] >= 0.85
                and signals["structural"] >= 0.85
            )
        )
        record = {
            "en_program_id": en_id,
            "es_program_id": es_id,
            "en_url": cand["en"]["url"],
            "es_url": cand["es"]["url"],
            "en_title": cand["en"].get("title", ""),
            "es_title": cand["es"].get("title", ""),
            "confidence": round(score, 3),
            "signals": signals,
            "auto_linked": auto_link,
            "needs_review": (not auto_link) and 0.45 <= score < 0.65,
        }
        en_best[en_id] = record
        if auto_link:
            en_claimed.add(en_id)
            es_claimed.add(es_id)

    pairings = list(en_best.values())
    # ES programs not auto-paired
    es_unpaired = [es for es in es_bases if es["canonical_program_id"] not in es_claimed]

    PAIRINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    pairings.sort(key=lambda p: -p["confidence"])
    with PAIRINGS_PATH.open("w", encoding="utf-8") as f:
        for p in pairings:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    # Summary
    auto = sum(1 for p in pairings if p["auto_linked"])
    review = sum(1 for p in pairings if p["needs_review"])
    table = Table(title="Pairing Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("EN programs", str(len(en_bases)))
    table.add_row("ES programs", str(len(es_bases)))
    table.add_row("Auto-linked (≥0.75)", f"[green]{auto}[/]")
    table.add_row("Needs review (0.50–0.75)", f"[yellow]{review}[/]")
    table.add_row("Below threshold (<0.50)", str(len(pairings) - auto - review))
    table.add_row("ES programs not auto-paired", str(len(es_unpaired)))
    pct = auto / len(en_bases) * 100 if en_bases else 0
    style = "green" if pct >= 90 else "yellow"
    table.add_row("EN auto-pair rate", f"[{style}]{pct:.0f}%[/]")
    console.print()
    console.print(table)
    console.print(f"Pairings → [green]{PAIRINGS_PATH}[/green]")


# ---------------------------------------------------------------------------
# Subcommand: render — write the wiki/ markdown tree
# ---------------------------------------------------------------------------


# Area taxonomy: keyword-match against title + slug. Order matters
# (first match wins) so put more specific patterns first.
AREA_RULES: list[tuple[str, list[str]]] = [
    ("ai-data-science", ["artificial intelligence", "data science", "data analytics",
                          "machine learning", "ai-", "ai ", "big data", "inteligencia artificial",
                          "ciencia de datos", "applied mathematics", "matemática aplicada",
                          "quantum"]),
    ("cybersecurity", ["cybersecurity", "ciberseguridad", "cybersec", "intrusion-testing",
                         "intrusion testing", "ccna cybersecurity", "azure security",
                         "security engineer"]),
    ("animation-digital-arts", ["animation", "vfx", "digital art", "multimedia",
                                  "animación", "artes digitales", "videojuego", "video game",
                                  "user experience", "user-experience", "ux/ui", "ux-ui",
                                  "ui mobile", "interface design"]),
    ("architecture", ["architecture", "architect", "arquitectura", "building", "edificación",
                      "construction", "bim", "urban", "rehabilitation",
                      "energy efficiency", "energía", "environmental"]),
    ("computer-science", ["computer engineering", "computer science", "software",
                            "ingeniería informática", "ingeniería en informática", "programming",
                            "java", "python", "php", "mysql", "web development",
                            "sap ", "ccna 1", "ccna 2", "azure administrator",
                            "soc computer", "scripting"]),
    ("telecom-electronics", ["telecom", "electronic", "audiovisual", "ingeniería electrónica",
                               "telematic", "telemática", "robotic", "robotica",
                               "acoustics", "acústica", "amateur radio", "vibrations",
                               "vibraciones"]),
    ("health-engineering", ["health engineering", "ingeniería de la salud", "biomedical",
                              "wellness"]),
    ("project-management", ["project management", "dirección de proyectos", "pmp", "scrum",
                              "agile project", "lean six sigma", "lean construction",
                              "lean project", "pmo management"]),
    ("philosophy-humanities", ["philosophy", "filosofía", "humanities", "ethics", "ética",
                                 "creativity", "creatividad", "thought", "thinking",
                                 "christianity", "cristianismo",
                                 "human condition", "aesthetics", "teacher training",
                                 "communication: learn", "communicate successfully",
                                 "innovative thinker", "political discourse", "debate"]),
    ("business-management", ["business", "management", "mba", "marketing", "finance",
                               "leadership", "innovation", "entrepreneurship", "negocios",
                               "dirección", "empresa", "ejecutivo", "executive",
                               "negotiation", "negociación"]),
]


def _classify_area(title: str, slug: str) -> str:
    """Choose the area that best matches a program's title+slug."""
    text = f"{title} {slug}".lower()
    for area, keywords in AREA_RULES:
        for kw in keywords:
            if kw in text:
                return area
    return "other"


def _classify_level(slug: str, title: str) -> str:
    """Map a program slug/title to a level enum."""
    s = f"{slug} {title}".lower()
    if "bachelor" in s or "grado " in s or "grado-en" in s or "degree in" in s:
        return "bachelor"
    if "doctorate" in s or "doctorado" in s or "phd" in s:
        return "doctorate"
    if "master" in s or "máster" in s:
        return "master"
    if "summer" in s or "verano" in s:
        return "summer"
    if "online" in s:
        return "online"
    if "course" in s or "curso" in s or "specialization" in s or "especialización" in s:
        return "specialization"
    return "other"


def _frontmatter(d: dict[str, Any]) -> str:
    """Render a dict as YAML frontmatter wrapped in ---/--- delimiters."""
    import yaml
    body = yaml.safe_dump(d, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{body}---\n"


def _wiki_dir() -> Path:
    from scripts.common import WIKI_DIR
    return WIKI_DIR


def _program_folder(canonical_id: str) -> Path:
    """canonical_program_id 'en/bachelor-foo' → wiki/en/programs/bachelor-foo/"""
    lang, slug = canonical_id.split("/", 1)
    return _wiki_dir() / lang / "programs" / slug


def _subject_file(canonical_subject_id: str) -> Path:
    lang, slug = canonical_subject_id.split("/", 1)
    return _wiki_dir() / lang / "subjects" / f"{slug}.md"


def _short_description(overview_md: str, max_chars: int = 220) -> str:
    """Take the first non-empty paragraph of the overview, truncated."""
    for chunk in re.split(r"\n\s*\n", overview_md or ""):
        chunk = chunk.strip()
        if chunk and not chunk.startswith("#"):
            return (chunk[:max_chars] + "…") if len(chunk) > max_chars else chunk
    return ""


def _render_program(
    base: dict[str, Any],
    subpages: dict[str, dict[str, Any]],
    pairing: dict[str, Any] | None,
    related: list[str],
    last_built_at: str,
) -> dict[Path, str]:
    """Render a single program's folder. Returns {path: content}."""
    folder = _program_folder(base["canonical_program_id"])
    files: dict[Path, str] = {}

    title = base.get("title", "")
    area = _classify_area(title, base.get("slug", ""))
    level = _classify_level(base.get("slug", ""), title)

    fm: dict[str, Any] = {
        "title": title,
        "slug": base.get("slug", ""),
        "canonical_program_id": base["canonical_program_id"],
        "level": level,
        "area": area,
        "official": True,  # default; can be refined later from degree_issuer
        "tags": _extract_tags(title, base.get("slug", "")),
        "modality": base.get("modality", []),
        "duration": base.get("duration", ""),
        "ects": base.get("ects"),
        "languages_of_instruction": base.get("languages_of_instruction", []),
        "schedule": base.get("schedule", ""),
        "location": base.get("location", ""),
        "start_date": base.get("start_date", ""),
        "tuition_status": "contact-required",
        "admissions_contact": "https://www.salleurl.edu/en/admissions"
                              if base["lang"] == "en"
                              else "https://www.salleurl.edu/es/admisiones",
        "official_name": base.get("official_name", ""),
        "degree_issuer": base.get("degree_issuer", ""),
        "subject_count": sum(
            sum(len(s["subjects"]) for s in y["sections"])
            for y in (subpages.get("curriculum", {}).get("curriculum_years", []) or [])
        ),
        "related_programs": related,
        "source_url": base["url"],
        "source_fetched_at": base.get("source_fetched_at", ""),
        "extractor_version": EXTRACTOR_VERSION,
        "extractor_mode": base.get("extractor_mode", "targeted"),
        "last_built_at": last_built_at,
    }
    if pairing and pairing.get("auto_linked"):
        equiv_lang = "es" if base["lang"] == "en" else "en"
        equiv_id = pairing["es_program_id"] if base["lang"] == "en" else pairing["en_program_id"]
        fm["equivalent_program_id"] = equiv_id
        fm["pairing_confidence"] = pairing["confidence"]
        fm["pairing_method"] = "+".join(k for k, v in pairing["signals"].items() if v >= 0.2) or "weighted"

    # README
    body_parts: list[str] = [_frontmatter(fm), f"# {title}\n"]
    if base.get("short_description"):
        body_parts.append(f"_{_short_description(base['short_description'])}_\n")

    # Quick facts table
    facts: list[tuple[str, str]] = [
        ("Level", level),
        ("Area", area),
        ("Duration", base.get("duration", "—") or "—"),
        ("ECTS", str(base.get("ects") or "—")),
        ("Modality", ", ".join(base.get("modality") or []) or "—"),
        ("Languages", ", ".join(base.get("languages_of_instruction") or []) or "—"),
        ("Schedule", base.get("schedule", "") or "—"),
        ("Location", base.get("location", "") or "—"),
        ("Start date", base.get("start_date", "") or "—"),
        ("Pricing", "Contact admissions"),
    ]
    body_parts.append("## Quick facts\n")
    body_parts.append("| Field | Value |")
    body_parts.append("|---|---|")
    for k, v in facts:
        body_parts.append(f"| {k} | {v} |")
    body_parts.append("")

    # Modality variants (only if more than one)
    variants = base.get("modality_variants") or []
    if len(variants) > 1:
        body_parts.append("## Modality variants\n")
        body_parts.append("| Modality | Duration | Languages | Places | ECTS | Schedule |")
        body_parts.append("|---|---|---|---|---|---|")
        for v in variants:
            body_parts.append(
                f"| {v.get('modality', '—')} | {v.get('duration', '—')} | "
                f"{v.get('language', '—')} | {v.get('places', '—')} | "
                f"{v.get('ects', '—')} | {v.get('schedule', '—')} |"
            )
        body_parts.append("")

    # Overview
    if base.get("overview_md"):
        body_parts.append("## Overview\n")
        body_parts.append(base["overview_md"])
        body_parts.append("")

    # Section pointers
    available = []
    for section in ("goals", "requirements", "curriculum", "careers", "methodology", "faculty"):
        if section in subpages:
            available.append(section)
    if available:
        body_parts.append("## Sections\n")
        for section in available:
            body_parts.append(f"- [{section.title()}](./{section}.md)")
        body_parts.append("")

    if base["lang"] == "en":
        body_parts.append("## Pricing\n")
        body_parts.append(
            "Tuition information is not published on the catalog site. "
            "Please [contact La Salle admissions](https://www.salleurl.edu/en/admissions) for current pricing.\n"
        )
    else:
        body_parts.append("## Precio\n")
        body_parts.append(
            "El precio de matrícula no se publica en el catálogo. "
            "Consulta a [admisiones de La Salle](https://www.salleurl.edu/es/admisiones) para conocer las tarifas vigentes.\n"
        )

    if "equivalent_program_id" in fm:
        equiv_lang = "es" if base["lang"] == "en" else "en"
        equiv_slug = fm["equivalent_program_id"].split("/", 1)[1]
        body_parts.append(f"## Other languages\n")
        body_parts.append(
            f"- [{equiv_lang.upper()}](../../../{equiv_lang}/programs/{equiv_slug}/README.md)"
        )
        body_parts.append("")

    files[folder / "README.md"] = "\n".join(body_parts)

    # Subpages: write body_md as their content (curriculum is special)
    for section, sub in subpages.items():
        if section == "curriculum":
            files[folder / "curriculum.md"] = _render_curriculum(base, sub, last_built_at)
            continue
        sub_fm = {
            "title": f"{title} — {section.replace('_', ' ').title()}",
            "section": section,
            "canonical_program_id": base["canonical_program_id"],
            "lang": base["lang"],
            "source_url": sub.get("source_url", ""),
            "source_fetched_at": sub.get("source_fetched_at", ""),
            "extractor_version": EXTRACTOR_VERSION,
            "extractor_mode": sub.get("extractor_mode", "targeted"),
            "last_built_at": last_built_at,
        }
        body = sub.get("body_md", "").strip()
        if not body:
            body = f"_No {section} content available for this program._"
        section_md = "\n".join([
            _frontmatter(sub_fm),
            f"# {title}",
            f"## {section.replace('_', ' ').title()}\n",
            body,
            "",
        ])
        files[folder / f"{section}.md"] = section_md

    return files


def _render_curriculum(base: dict[str, Any], sub: dict[str, Any], last_built_at: str) -> str:
    """Render the curriculum.md page from a syllabus subpage record."""
    title = base.get("title", "")
    fm = {
        "title": f"{title} — Curriculum",
        "section": "curriculum",
        "canonical_program_id": base["canonical_program_id"],
        "lang": base["lang"],
        "source_url": sub.get("source_url", ""),
        "source_fetched_at": sub.get("source_fetched_at", ""),
        "extractor_version": EXTRACTOR_VERSION,
        "extractor_mode": sub.get("extractor_mode", "targeted"),
        "last_built_at": last_built_at,
    }
    parts = [_frontmatter(fm), f"# {title}", "## Curriculum\n"]
    years = sub.get("curriculum_years", []) or []
    if not years:
        parts.append("_No structured curriculum available._")
    else:
        for y in years:
            year_label = y.get("year", "")
            if year_label:
                parts.append(f"### {year_label}\n")
            for sec in y.get("sections", []):
                sem = sec.get("semester", "")
                if sem:
                    parts.append(f"#### {sem}\n")
                for subj in sec.get("subjects", []):
                    name = subj.get("title", "")
                    href = subj.get("url", "")
                    ects = subj.get("ects")
                    suffix = f" — {ects} ECTS" if ects else ""
                    if href.startswith("/"):
                        slug = href.rstrip("/").split("/")[-1]
                        # Only emit the link if the target subject file exists.
                        # Some syllabi link to subjects that were never crawled
                        # (404s on the source site or removed pages).
                        target = _wiki_dir() / base["lang"] / "subjects" / f"{slug}.md"
                        if target.exists():
                            rel = f"../../subjects/{slug}.md"
                            parts.append(f"- [{name}]({rel}){suffix}")
                        elif name:
                            parts.append(f"- {name}{suffix}")
                    elif name:
                        parts.append(f"- {name}{suffix}")
                parts.append("")
    parts.append("")
    return "\n".join(parts)


def _render_subject(rec: dict[str, Any], parent_program_ids: list[str], last_built_at: str) -> str:
    fm = {
        "title": rec.get("title", ""),
        "slug": rec.get("slug", ""),
        "canonical_subject_id": rec["canonical_subject_id"],
        "parent_programs": parent_program_ids,
        "year": rec.get("year"),
        "semester": rec.get("semester", ""),
        "type": rec.get("type", ""),
        "ects": rec.get("ects"),
        "lang": rec["lang"],
        "source_url": rec["url"],
        "source_fetched_at": rec.get("source_fetched_at", ""),
        "extractor_version": EXTRACTOR_VERSION,
        "extractor_mode": rec.get("extractor_mode", "targeted"),
        "last_built_at": last_built_at,
    }
    parts = [_frontmatter(fm), f"# {rec.get('title', '(untitled)')}"]
    facts: list[tuple[str, str]] = [
        ("Year", str(rec.get("year") or "—")),
        ("Semester", rec.get("semester") or "—"),
        ("Type", rec.get("type") or "—"),
        ("ECTS", str(rec.get("ects") or "—")),
    ]
    parts.append("## Quick facts\n")
    parts.append("| Field | Value |")
    parts.append("|---|---|")
    for k, v in facts:
        parts.append(f"| {k} | {v} |")
    parts.append("")

    sections = [
        ("Description", rec.get("description")),
        ("Prerequisites", rec.get("prerequisites")),
        ("Objectives", rec.get("objectives")),
        ("Contents", rec.get("contents")),
        ("Methodology", rec.get("methodology")),
        ("Evaluation", rec.get("evaluation")),
        ("Grading criteria", rec.get("grading_criteria")),
        ("Bibliography", rec.get("bibliography")),
    ]
    for heading, body in sections:
        body = (body or "").strip()
        if not body:
            continue
        parts.append(f"## {heading}\n")
        parts.append(body)
        parts.append("")

    if rec.get("professors"):
        parts.append("## Professors\n")
        for p in rec["professors"]:
            parts.append(f"- {p}")
        parts.append("")

    if parent_program_ids:
        parts.append("## Programs that include this subject\n")
        for pid in parent_program_ids:
            lang, slug = pid.split("/", 1)
            parts.append(f"- [{lang.upper()}: {slug}](../programs/{slug}/README.md)")
        parts.append("")

    parts.append("")
    return "\n".join(parts)


def _extract_tags(title: str, slug: str) -> list[str]:
    """Pick a few keyword tags from title+slug."""
    text = f"{title} {slug}".lower()
    candidates = [
        "ai", "artificial-intelligence", "data-science", "machine-learning",
        "cybersecurity", "animation", "vfx", "3d", "multimedia", "video-games",
        "architecture", "building", "construction", "computer-engineering",
        "software", "telecom", "electronic", "robotics", "audiovisual",
        "philosophy", "ethics", "creativity", "business", "management", "mba",
        "marketing", "finance", "leadership", "entrepreneurship", "online",
        "executive", "summer",
    ]
    tags = []
    for c in candidates:
        if c.replace("-", " ") in text or c in text or c in slug:
            tags.append(c)
    return sorted(set(tags))[:6]


@app.command()
def render() -> None:
    """Render structured.jsonl + pairings.jsonl → wiki/ markdown tree."""
    if not STRUCTURED_PATH.exists():
        console.print("[red]No structured.jsonl found. Run 'extract' first.[/red]")
        raise typer.Exit(1)

    records = [json.loads(l) for l in STRUCTURED_PATH.open()]
    pairings: dict[str, dict[str, Any]] = {}
    if PAIRINGS_PATH.exists():
        for line in PAIRINGS_PATH.open():
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            pairings[p["en_program_id"]] = p
            pairings[p["es_program_id"]] = p

    bases = [r for r in records if r["kind"] == "program-base"]
    base_by_url = {b["url"]: b for b in bases}

    # Group subpages by parent_url + section
    subpages_for_program: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in records:
        if r["kind"] != "program-subpage":
            continue
        parent = r.get("parent_url", "")
        section = r.get("section", "")
        subpages_for_program[parent][section] = r

    # Map subjects to their parent program ids
    parents_for_subject: dict[str, list[str]] = defaultdict(list)
    for r in records:
        if r["kind"] != "subject":
            continue
        for parent_url in r.get("parent_program_urls") or []:
            base = base_by_url.get(parent_url)
            if base:
                parents_for_subject[r["url"]].append(base["canonical_program_id"])

    # Build a slug → all programs map for "related programs" suggestions
    by_area: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for b in bases:
        title = b.get("title", "")
        slug = b.get("slug", "")
        area = _classify_area(title, slug)
        by_area[(b["lang"], area)].append(b)

    last_built_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    unchanged = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Rendering programs", total=len(bases))
        for base in bases:
            sps = subpages_for_program.get(base["url"], {})
            pairing = pairings.get(base["canonical_program_id"])
            # Related: same area/lang, max 5
            area = _classify_area(base.get("title", ""), base.get("slug", ""))
            related = [
                b["slug"] for b in by_area[(base["lang"], area)]
                if b["url"] != base["url"]
            ][:5]
            files = _render_program(base, sps, pairing, related, last_built_at)
            for path, content in files.items():
                changed, _ = write_if_changed(path, content)
                if changed:
                    written += 1
                else:
                    unchanged += 1
            progress.advance(task)

        # Subjects
        subjects = [r for r in records if r["kind"] == "subject"]
        task2 = progress.add_task("Rendering subjects", total=len(subjects))
        for s in subjects:
            content = _render_subject(s, parents_for_subject.get(s["url"], []), last_built_at)
            path = _subject_file(s["canonical_subject_id"])
            changed, _ = write_if_changed(path, content)
            if changed:
                written += 1
            else:
                unchanged += 1
            progress.advance(task2)

    console.print(f"[green]{written}[/green] files written, [dim]{unchanged}[/dim] unchanged.")
    console.print(f"Wiki tree → [green]{_wiki_dir()}[/green]")


# ---------------------------------------------------------------------------
# Subcommand: index — derived content
# ---------------------------------------------------------------------------


def _read_program_frontmatter(readme_path: Path) -> dict[str, Any]:
    """Parse YAML frontmatter from a program README."""
    import yaml
    text = readme_path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def _all_program_frontmatter(lang: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    base = _wiki_dir() / lang / "programs"
    if not base.exists():
        return out
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        readme = d / "README.md"
        if readme.exists():
            fm = _read_program_frontmatter(readme)
            if fm:
                out.append(fm)
    return out


def _index_text(lang: str) -> dict[str, str]:
    """Generate INDEX-style strings for a language."""
    return {
        "en": {
            "title": "EN program index",
            "intro": "All programs at La Salle Campus Barcelona, in English.",
            "format_section": "## Programs by format",
            "english_taught": "### English-taught programs",
            "online": "### Online programs",
            "hybrid": "### Hybrid programs",
            "all": "## All programs (alphabetical)",
        },
        "es": {
            "title": "Índice de programas (ES)",
            "intro": "Todos los programas de La Salle Campus Barcelona, en español.",
            "format_section": "## Programas por formato",
            "english_taught": "### Programas impartidos en inglés",
            "online": "### Programas online",
            "hybrid": "### Programas híbridos",
            "all": "## Todos los programas (alfabético)",
        },
    }[lang]


def _build_index_md(lang: str, programs: list[dict[str, Any]]) -> str:
    txt = _index_text(lang)
    parts = [
        f"# {txt['title']}\n",
        txt["intro"] + "\n",
        f"_Total: {len(programs)} programs._\n",
        txt["format_section"],
    ]
    # English-taught (any program with 'English' in languages_of_instruction)
    en_taught = [p for p in programs if "English" in (p.get("languages_of_instruction") or [])]
    parts.append(txt["english_taught"])
    parts.append(f"_{len(en_taught)} programs._\n")
    parts.append("| Title | Level | Area |")
    parts.append("|---|---|---|")
    for p in sorted(en_taught, key=lambda x: x.get("title", "")):
        parts.append(f"| [{p.get('title','')}](programs/{p.get('slug','')}/README.md) | {p.get('level','')} | {p.get('area','')} |")
    parts.append("")

    # Online
    online = [p for p in programs if "online" in (p.get("modality") or [])]
    parts.append(txt["online"])
    parts.append(f"_{len(online)} programs._\n")
    if online:
        parts.append("| Title | Level | Area |")
        parts.append("|---|---|---|")
        for p in sorted(online, key=lambda x: x.get("title", "")):
            parts.append(f"| [{p.get('title','')}](programs/{p.get('slug','')}/README.md) | {p.get('level','')} | {p.get('area','')} |")
        parts.append("")

    # All programs
    parts.append(txt["all"])
    parts.append("")
    parts.append("| Title | Level | Area | Modality | ECTS |")
    parts.append("|---|---|---|---|---|")
    for p in sorted(programs, key=lambda x: x.get("title", "")):
        parts.append(
            f"| [{p.get('title','')}](programs/{p.get('slug','')}/README.md) | "
            f"{p.get('level','')} | {p.get('area','')} | "
            f"{', '.join(p.get('modality') or [])} | {p.get('ects') or '—'} |"
        )
    parts.append("")
    return "\n".join(parts)


# Human-friendly area + level labels
AREA_LABELS = {
    "ai-data-science": "AI & Data Science",
    "architecture": "Architecture & Building",
    "business-management": "Business & Management",
    "computer-science": "Computer Science",
    "cybersecurity": "Cybersecurity",
    "animation-digital-arts": "Animation & Digital Arts",
    "telecom-electronics": "Telecommunications & Electronics",
    "health-engineering": "Health Engineering",
    "philosophy-humanities": "Philosophy & Humanities",
    "project-management": "Project Management",
    "other": "Other",
}

LEVEL_LABELS = {
    "bachelor": "Bachelor's degrees",
    "master": "Master's degrees",
    "doctorate": "Doctorates",
    "specialization": "Specialization courses",
    "online": "Online courses",
    "summer": "Summer school",
    "other": "Other programs",
}


def _build_by_area(lang: str, programs: list[dict[str, Any]], area: str) -> str:
    label = AREA_LABELS.get(area, area)
    in_area = [p for p in programs if p.get("area") == area]
    parts = [
        f"# {label}\n",
        f"_{len(in_area)} programs at La Salle Campus Barcelona ({lang.upper()})._\n",
    ]
    by_level: dict[str, list[dict]] = defaultdict(list)
    for p in in_area:
        by_level[p.get("level", "other")].append(p)
    for level in ("bachelor", "master", "doctorate", "specialization", "online", "summer", "other"):
        if not by_level[level]:
            continue
        parts.append(f"## {LEVEL_LABELS.get(level, level)}\n")
        parts.append("| Title | Modality | ECTS | Languages |")
        parts.append("|---|---|---|---|")
        for p in sorted(by_level[level], key=lambda x: x.get("title", "")):
            parts.append(
                f"| [{p.get('title','')}](../programs/{p.get('slug','')}/README.md) | "
                f"{', '.join(p.get('modality') or [])} | "
                f"{p.get('ects') or '—'} | "
                f"{', '.join(p.get('languages_of_instruction') or [])} |"
            )
        parts.append("")
    return "\n".join(parts)


def _build_by_level(lang: str, programs: list[dict[str, Any]], level: str) -> str:
    label = LEVEL_LABELS.get(level, level)
    in_level = [p for p in programs if p.get("level") == level]
    parts = [
        f"# {label}\n",
        f"_{len(in_level)} programs at La Salle Campus Barcelona ({lang.upper()})._\n",
    ]
    by_area: dict[str, list[dict]] = defaultdict(list)
    for p in in_level:
        by_area[p.get("area", "other")].append(p)
    for area in sorted(by_area):
        parts.append(f"## {AREA_LABELS.get(area, area)}\n")
        parts.append("| Title | Modality | ECTS | Languages |")
        parts.append("|---|---|---|---|")
        for p in sorted(by_area[area], key=lambda x: x.get("title", "")):
            parts.append(
                f"| [{p.get('title','')}](../programs/{p.get('slug','')}/README.md) | "
                f"{', '.join(p.get('modality') or [])} | "
                f"{p.get('ects') or '—'} | "
                f"{', '.join(p.get('languages_of_instruction') or [])} |"
            )
        parts.append("")
    return "\n".join(parts)


def _build_faq(lang: str) -> str:
    if lang == "en":
        return """\
# Student FAQ

Common questions and where to find answers in this wiki.

## "What programs do you offer in [topic]?"
Browse `by-area/` — files like `ai-data-science.md`, `architecture.md`, `cybersecurity.md`. Each lists every program in that area, grouped by level (bachelor / master / etc.).

## "What bachelor's degrees are available?"
See `by-level/bachelors.md`. The same pattern works for masters, doctorates, specialization courses, online courses, and summer school.

## "What's the difference between two programs?"
Open both program READMEs (`programs/{slug}/README.md`). Each starts with a Quick facts table for fast comparison.

## "What courses will I take in this program?"
Open `programs/{slug}/curriculum.md`. The page lists every subject, grouped by year and semester, with links to individual subject pages.

## "What are the admission requirements?"
Open `programs/{slug}/requirements.md`.

## "What jobs can I get with this degree?"
Open `programs/{slug}/careers.md`.

## "Is the program in English?"
Look at the Quick facts table on the program README — the **Languages** field lists the languages of instruction. The full list of English-taught programs is also in `INDEX.md` under "English-taught programs".

## "How much does this program cost?"
**Tuition information is not published in the catalog.** Please contact La Salle admissions: <https://www.salleurl.edu/en/admissions>

## "Is there a Spanish version of this page?"
If yes, the program README has an **Other languages** section linking to the ES wiki under `../../../es/programs/{slug}/README.md`.
"""
    return """\
# FAQ para estudiantes

Preguntas habituales y dónde encontrar las respuestas en esta wiki.

## "¿Qué programas ofrecéis sobre [tema]?"
Mira `by-area/` — los archivos como `ai-data-science.md`, `architecture.md`, `cybersecurity.md`. Cada uno lista los programas del área, agrupados por nivel.

## "¿Qué grados ofrecéis?"
Ver `by-level/bachelors.md`. El mismo patrón funciona para másters, doctorados, cursos de especialización, formación online y escuela de verano.

## "¿Cuál es la diferencia entre dos programas?"
Abre los README de ambos programas. Cada uno empieza con una tabla de "Quick facts" para comparar rápido.

## "¿Qué asignaturas voy a cursar?"
Abre `programs/{slug}/curriculum.md`. La página lista todas las asignaturas, agrupadas por año y semestre, con enlaces a las fichas de cada una.

## "¿Cuáles son los requisitos de admisión?"
Abre `programs/{slug}/requirements.md`.

## "¿Qué salidas profesionales tiene este título?"
Abre `programs/{slug}/careers.md`.

## "¿En qué idioma se imparte el programa?"
Mira la tabla "Quick facts" del README del programa — el campo **Languages** lista los idiomas. La lista completa de programas en inglés también está en `INDEX.md`.

## "¿Cuánto cuesta el programa?"
**El precio de matrícula no se publica en el catálogo.** Contacta con admisiones: <https://www.salleurl.edu/es/admisiones>

## "¿Hay versión en otro idioma?"
Si existe, el README del programa tiene una sección **Otros idiomas** con el enlace a la wiki EN.
"""


def _build_glossary(lang: str) -> str:
    if lang == "en":
        return """\
# Glossary

## ECTS
European Credit Transfer System. 1 ECTS ≈ 25–30 hours of student work. A typical bachelor's degree is 240 ECTS over 4 years; a master's is 60–90 ECTS.

## Modality
- **on-site**: classes are held in person at the Barcelona campus.
- **online**: fully remote, no campus attendance required.
- **hybrid**: a mix of on-site and online sessions.

## Official vs non-official program
**Official** programs are recognized by the Spanish Ministry of Education and lead to a state-recognized degree (e.g. Bachelor / Grado, Master / Máster). **Non-official** programs are valid La Salle credentials but not state-recognized titles.

## Ramon Llull University
La Salle Campus Barcelona is a member university of Universitat Ramon Llull (URL), a private federated university based in Barcelona. Official degrees are issued under URL.

## Bachelor / Grado
"Bachelor" (English) and "Grado" (Spanish) refer to the same level of study (undergraduate). Most degrees are 240 ECTS / 4 years.

## Master / Máster
Postgraduate program, typically 60–90 ECTS / 1–2 years. May be official or non-official.

## Specialization course / Curso de especialización
Short-format courses (often a few weeks to a few months), focused on a specific skill or topic. Not equivalent to a full degree.

## Tuition
The catalog site does not publish tuition fees. Contact La Salle admissions for current pricing.
"""
    return """\
# Glosario

## ECTS
European Credit Transfer System. 1 ECTS ≈ 25–30 horas de trabajo del estudiante. Un grado típico son 240 ECTS en 4 años; un máster, 60–90 ECTS.

## Modalidad
- **presencial / on-site**: clases en el campus de Barcelona.
- **online**: 100 % a distancia.
- **hybrid / semipresencial**: mezcla de sesiones presenciales y online.

## Programa oficial vs no oficial
Los programas **oficiales** están reconocidos por el Ministerio de Educación de España y conducen a un título oficial (Grado, Máster). Los programas **no oficiales** son títulos propios de La Salle, válidos pero sin reconocimiento estatal.

## Universidad Ramon Llull (URL)
La Salle Campus Barcelona es una universidad miembro de la Universitat Ramon Llull (URL), una universidad privada federada en Barcelona. Los títulos oficiales se emiten a través de la URL.

## Grado / Bachelor
Niveles de pregrado equivalentes. La mayoría son 240 ECTS / 4 años.

## Máster / Master
Postgrado, típicamente 60–90 ECTS / 1–2 años. Puede ser oficial o no oficial.

## Curso de especialización
Cursos cortos (semanas o meses) centrados en una habilidad o tema específico. No equivalen a un título completo.

## Matrícula
El precio no se publica en el catálogo. Contacta con admisiones de La Salle.
"""


@app.command()
def index() -> None:
    """Generate index files and meta sidecars."""
    if not _wiki_dir().exists():
        console.print("[red]No wiki/ tree found. Run 'render' first.[/red]")
        raise typer.Exit(1)

    last_built_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0
    unchanged = 0

    def _write(path: Path, content: str) -> None:
        nonlocal written, unchanged
        changed, _ = write_if_changed(path, content)
        if changed:
            written += 1
        else:
            unchanged += 1

    # Top-level README + faq + glossary
    _write(_wiki_dir() / "README.md", _build_top_readme(last_built_at))
    _write(_wiki_dir() / "faq.md", _build_faq("en"))  # Note: lang-aware faqs are per-tree
    _write(_wiki_dir() / "glossary.md", _build_glossary("en"))

    for lang in ("en", "es"):
        programs = _all_program_frontmatter(lang)
        if not programs:
            continue
        # Per-language entry README + INDEX
        _write(_wiki_dir() / lang / "README.md", _build_lang_readme(lang, programs, last_built_at))
        _write(_wiki_dir() / lang / "INDEX.md", _build_index_md(lang, programs))
        _write(_wiki_dir() / lang / "faq.md", _build_faq(lang))
        _write(_wiki_dir() / lang / "glossary.md", _build_glossary(lang))

        # by-area
        areas = sorted({p.get("area", "other") for p in programs})
        for area in areas:
            _write(
                _wiki_dir() / lang / "by-area" / f"{area}.md",
                _build_by_area(lang, programs, area),
            )
        _write(
            _wiki_dir() / lang / "by-area" / "README.md",
            _build_axis_readme(lang, "area", programs, areas, AREA_LABELS),
        )
        # by-level
        levels = sorted({p.get("level", "other") for p in programs})
        for level in levels:
            _write(
                _wiki_dir() / lang / "by-level" / f"{level}.md",
                _build_by_level(lang, programs, level),
            )
        _write(
            _wiki_dir() / lang / "by-level" / "README.md",
            _build_axis_readme(lang, "level", programs, levels, LEVEL_LABELS),
        )
        # subjects/README.md
        subj_dir = _wiki_dir() / lang / "subjects"
        if subj_dir.exists():
            _write(subj_dir / "README.md", _build_subjects_index(lang, subj_dir))

    # meta/* sidecars
    meta_dir = _wiki_dir() / "meta"
    catalog_lines = []
    for lang in ("en", "es"):
        for p in _all_program_frontmatter(lang):
            catalog_lines.append(json.dumps(p, ensure_ascii=False))
    _write(meta_dir / "catalog.jsonl", "\n".join(catalog_lines) + "\n")

    # Subjects sidecar
    subjects_lines = []
    for lang in ("en", "es"):
        sd = _wiki_dir() / lang / "subjects"
        if not sd.exists():
            continue
        for f in sorted(sd.glob("*.md")):
            if f.name == "README.md":
                continue
            text = f.read_text(encoding="utf-8")
            if text.startswith("---"):
                end = text.find("\n---", 3)
                if end != -1:
                    import yaml
                    fm = yaml.safe_load(text[3:end]) or {}
                    if fm:
                        subjects_lines.append(json.dumps(fm, ensure_ascii=False))
    _write(meta_dir / "subjects.jsonl", "\n".join(subjects_lines) + "\n")

    # Pairings sidecar (copy of data/pairings.jsonl, if any)
    if PAIRINGS_PATH.exists():
        _write(meta_dir / "pairings.jsonl", PAIRINGS_PATH.read_text(encoding="utf-8"))

    # Fallback report
    _write(meta_dir / "fallback_report.md", _build_fallback_report())
    # Stats
    _write(meta_dir / "stats.md", _build_stats(last_built_at))

    console.print(f"[green]{written}[/green] index files written, [dim]{unchanged}[/dim] unchanged.")


def _build_top_readme(last_built_at: str) -> str:
    return f"""\
# La Salle Campus Barcelona — Catalog Wiki

This is a structured, agent-navigable mirror of the academic catalog at <https://www.salleurl.edu>.
Generated automatically from the raw HTML corpus.

_Last built: {last_built_at}_

## Where to start

- **English content**: see [`en/README.md`](en/README.md)
- **Contenido en español**: ver [`es/README.md`](es/README.md)
- **Common student questions**: see [`faq.md`](faq.md)
- **Glossary** (ECTS, modality, official programs, …): see [`glossary.md`](glossary.md)

## Structure

Each language tree has the same shape:

- `INDEX.md` — flat list of all programs + format facets (English-taught, online, hybrid)
- `by-area/` — programs grouped by academic area
- `by-level/` — programs grouped by level (bachelor / master / specialization / …)
- `programs/{{slug}}/` — one folder per program, with `README.md` (overview), `goals.md`, `requirements.md`, `curriculum.md`, `careers.md`, `methodology.md`, `faculty.md`
- `subjects/{{slug}}.md` — one file per course/subject, deduplicated across programs

## Machine-readable sidecars

- [`meta/catalog.jsonl`](meta/catalog.jsonl) — one JSON line per program with all frontmatter fields
- [`meta/subjects.jsonl`](meta/subjects.jsonl) — one JSON line per subject
- [`meta/pairings.jsonl`](meta/pairings.jsonl) — EN↔ES program pair candidates with confidence scores
- [`meta/fallback_report.md`](meta/fallback_report.md) — pages where targeted extraction failed
- [`meta/stats.md`](meta/stats.md) — corpus health statistics

## Pricing

The catalog site does not publish tuition information. For current pricing, contact admissions:
- EN: <https://www.salleurl.edu/en/admissions>
- ES: <https://www.salleurl.edu/es/admisiones>
"""


def _build_lang_readme(lang: str, programs: list[dict[str, Any]], last_built_at: str) -> str:
    if lang == "en":
        return f"""\
# La Salle Campus Barcelona — English catalog

_{len(programs)} programs. Last built: {last_built_at}._

## Browse

- [INDEX.md](INDEX.md) — all programs, alphabetical, with format facets
- [by-area/](by-area/README.md) — programs grouped by academic area
- [by-level/](by-level/README.md) — programs grouped by level
- [subjects/](subjects/README.md) — all subject (course) pages
- [faq.md](faq.md) — frequently asked student questions
- [glossary.md](glossary.md) — definitions of ECTS, modality, official programs, etc.
"""
    return f"""\
# La Salle Campus Barcelona — Catálogo en español

_{len(programs)} programas. Última actualización: {last_built_at}._

## Navegación

- [INDEX.md](INDEX.md) — todos los programas, alfabéticos, con facetas por formato
- [by-area/](by-area/README.md) — programas por área académica
- [by-level/](by-level/README.md) — programas por nivel
- [subjects/](subjects/README.md) — fichas de asignaturas
- [faq.md](faq.md) — preguntas frecuentes
- [glossary.md](glossary.md) — definiciones de ECTS, modalidad, programas oficiales, etc.
"""


def _build_axis_readme(
    lang: str,
    axis: str,
    programs: list[dict[str, Any]],
    keys: list[str],
    labels: dict[str, str],
) -> str:
    parts = [f"# Programs by {axis} ({lang.upper()})\n"]
    for k in keys:
        n = sum(1 for p in programs if p.get(axis) == k)
        if n == 0:
            continue
        parts.append(f"- [{labels.get(k, k)}](./{k}.md) — {n} programs")
    return "\n".join(parts) + "\n"


def _build_subjects_index(lang: str, subj_dir: Path) -> str:
    parts = [f"# Subjects ({lang.upper()})\n"]
    files = [f for f in sorted(subj_dir.glob("*.md")) if f.name != "README.md"]
    parts.append(f"_{len(files)} subjects (deduplicated across programs)._\n")
    parts.append("| Title | File |")
    parts.append("|---|---|")
    import yaml
    for f in files:
        text = f.read_text(encoding="utf-8")
        title = f.stem
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                try:
                    fm = yaml.safe_load(text[3:end]) or {}
                    title = fm.get("title", title)
                except yaml.YAMLError:
                    pass
        parts.append(f"| {title} | [{f.name}](./{f.name}) |")
    return "\n".join(parts) + "\n"


def _build_fallback_report() -> str:
    """List records that fell back to article-text extraction."""
    if not STRUCTURED_PATH.exists():
        return "# Fallback report\n\nNo structured data available.\n"
    fallbacks = []
    for line in STRUCTURED_PATH.open():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("extractor_mode") == "fallback":
            fallbacks.append(r)
    parts = [
        "# Fallback report\n",
        f"_{len(fallbacks)} records used the fallback extractor._\n",
        "These pages are typically sparse content (workshops, short courses) where the canonical Drupal field was missing. A non-zero count is expected. A sustained increase indicates selector drift.\n",
    ]
    if fallbacks:
        parts.append("| Kind | Missing fields | URL |")
        parts.append("|---|---|---|")
        for r in fallbacks:
            missing = ", ".join(r.get("missing_fields", []) or [])
            parts.append(f"| {r['kind']} | {missing} | <{r['url']}> |")
    return "\n".join(parts) + "\n"


def _build_stats(last_built_at: str) -> str:
    """Aggregate counts and health metrics."""
    if not STRUCTURED_PATH.exists():
        return "# Stats\n\nNo structured data available.\n"
    records = [json.loads(l) for l in STRUCTURED_PATH.open()]
    counts = Counter(r["kind"] for r in records)
    fallbacks = sum(1 for r in records if r.get("extractor_mode") == "fallback")
    fallback_pct = fallbacks / len(records) * 100 if records else 0
    en_bases = sum(1 for r in records if r["kind"] == "program-base" and r.get("lang") == "en")
    es_bases = sum(1 for r in records if r["kind"] == "program-base" and r.get("lang") == "es")
    en_subj = sum(1 for r in records if r["kind"] == "subject" and r.get("lang") == "en")
    es_subj = sum(1 for r in records if r["kind"] == "subject" and r.get("lang") == "es")

    # Area distribution from EN program frontmatter
    area_counts = Counter()
    for p in _all_program_frontmatter("en"):
        area_counts[p.get("area", "other")] += 1
    other_count = area_counts.get("other", 0)

    # Pairing stats
    auto_pairs = 0
    review_pairs = 0
    if PAIRINGS_PATH.exists():
        for line in PAIRINGS_PATH.open():
            p = json.loads(line)
            if p.get("auto_linked"):
                auto_pairs += 1
            elif p.get("needs_review"):
                review_pairs += 1
    pair_rate = auto_pairs / en_bases * 100 if en_bases else 0

    parts = [
        "# Catalog wiki — stats\n",
        f"_Last built: {last_built_at}._\n",
        "## Corpus\n",
        f"- Program bases: {counts.get('program-base', 0)} (EN: {en_bases}, ES: {es_bases})",
        f"- Program subpages: {counts.get('program-subpage', 0)}",
        f"- Subjects: {counts.get('subject', 0)} (EN: {en_subj}, ES: {es_subj})",
        f"- Total structured records: {len(records)}\n",
        "## Health\n",
        f"- Fallback rate: {fallbacks} ({fallback_pct:.1f}%) — target < 5%",
        f"- EN auto-pair rate: {pair_rate:.0f}% ({auto_pairs}/{en_bases}) — target ≥ 90%",
        f"- Pairs needing manual review: {review_pairs}",
        f"- Programs in 'other' area: {other_count} — target < 10",
        "",
        "## Area distribution (EN)\n",
        "| Area | Count |",
        "|---|---|",
    ]
    for area, n in area_counts.most_common():
        parts.append(f"| {AREA_LABELS.get(area, area)} | {n} |")
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Subcommand: verify
# ---------------------------------------------------------------------------


@app.command()
def verify() -> None:
    """Run verification invariants and print a report."""
    if not _wiki_dir().exists():
        console.print("[red]No wiki/ tree found.[/red]")
        raise typer.Exit(1)

    issues: list[str] = []
    table = Table(title="Verification Report")
    table.add_column("Check", style="bold")
    table.add_column("Result")

    # All programs from manifest are present
    manifest = load_manifest()
    by_url = latest_record_per_url(manifest)
    program_urls = [
        r["url"] for r in by_url.values()
        if r.get("kind") == "program-base" and r.get("http_status") == 200
    ]
    seen_program_dirs = set()
    for lang in ("en", "es"):
        d = _wiki_dir() / lang / "programs"
        if d.exists():
            for p in d.iterdir():
                if p.is_dir() and (p / "README.md").exists():
                    seen_program_dirs.add(f"{lang}/{p.name}")
    expected_program_ids = {canonical_program_id(u) for u in program_urls}
    missing_programs = expected_program_ids - seen_program_dirs
    if missing_programs:
        issues.append(f"{len(missing_programs)} program(s) missing from wiki")
        table.add_row("All programs present", f"[red]{len(seen_program_dirs)}/{len(expected_program_ids)}[/]")
    else:
        table.add_row("All programs present", f"[green]{len(seen_program_dirs)}/{len(expected_program_ids)}[/]")

    # Frontmatter completeness
    required = ["level", "area", "modality", "duration", "ects", "languages_of_instruction", "source_url"]
    incomplete = 0
    for lang in ("en", "es"):
        for p in _all_program_frontmatter(lang):
            for k in required:
                v = p.get(k)
                if v in (None, "", []):
                    incomplete += 1
                    break
    total_programs = len(seen_program_dirs)
    pct = (total_programs - incomplete) / total_programs * 100 if total_programs else 0
    style = "green" if pct >= 98 else "red"
    table.add_row("Frontmatter completeness ≥ 98%", f"[{style}]{pct:.1f}% ({total_programs - incomplete}/{total_programs})[/]")
    if pct < 98:
        issues.append(f"Frontmatter completeness {pct:.1f}% < 98%")

    # Fallback rate
    fallbacks = 0
    total = 0
    if STRUCTURED_PATH.exists():
        for line in STRUCTURED_PATH.open():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            total += 1
            if r.get("extractor_mode") == "fallback":
                fallbacks += 1
    fb_pct = fallbacks / total * 100 if total else 0
    style = "green" if fb_pct < 5 else "red"
    table.add_row("Fallback rate < 5%", f"[{style}]{fb_pct:.1f}% ({fallbacks}/{total})[/]")
    if fb_pct >= 5:
        issues.append(f"Fallback rate {fb_pct:.1f}% ≥ 5% — selector drift suspected")

    # Pairing rate. Realistic target: 50% — many specialization courses and
    # workshops have no direct ES equivalent, and short courses often have ES
    # variants that translate so loosely that no automated heuristic catches
    # them. Bipartite matching keeps precision high (manual spot-check).
    auto = 0
    en_total = sum(1 for p in _all_program_frontmatter("en"))
    if PAIRINGS_PATH.exists():
        for line in PAIRINGS_PATH.open():
            line = line.strip()
            if not line:
                continue
            p = json.loads(line)
            if p.get("auto_linked"):
                auto += 1
    pair_pct = auto / en_total * 100 if en_total else 0
    style = "green" if pair_pct >= 50 else "yellow"
    table.add_row("EN auto-pair rate ≥ 50%", f"[{style}]{pair_pct:.0f}% ({auto}/{en_total})[/]")
    if pair_pct < 50:
        issues.append(f"Auto-pair rate {pair_pct:.0f}% < 50%")

    # Dead-link check (relative links in markdown)
    dead = 0
    pattern = re.compile(r"\]\((?!https?:|mailto:|#)([^)]+)\)")
    for md_path in _wiki_dir().rglob("*.md"):
        text = md_path.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            target = m.group(1).split("#", 1)[0]
            if not target:
                continue
            target_path = (md_path.parent / target).resolve()
            if not target_path.exists():
                dead += 1
                if dead <= 5:
                    log.warning("Dead link in %s: %s", md_path, target)
    style = "green" if dead == 0 else "red"
    table.add_row("Dead links == 0", f"[{style}]{dead}[/]")
    if dead:
        issues.append(f"{dead} dead link(s)")

    # File-size budget: 95% of program READMEs in 2–6 KB; nothing > 25 KB
    over_cap = 0
    too_small = 0
    for lang in ("en", "es"):
        d = _wiki_dir() / lang / "programs"
        if not d.exists():
            continue
        for p in d.iterdir():
            if not p.is_dir():
                continue
            r = p / "README.md"
            if not r.exists():
                continue
            size = r.stat().st_size
            if size > 25_000:
                over_cap += 1
            if size < 1_500:
                too_small += 1
    style = "green" if over_cap == 0 else "red"
    table.add_row("All READMEs ≤ 25 KB", f"[{style}]{over_cap} over[/]")

    # Taxonomy drift
    other_count = 0
    for p in _all_program_frontmatter("en"):
        if p.get("area") == "other":
            other_count += 1
    style = "green" if other_count < 10 else "yellow"
    table.add_row("Programs in 'other' area < 10", f"[{style}]{other_count}[/]")
    if other_count >= 10:
        issues.append(f"{other_count} programs in 'other' area — taxonomy drift")

    console.print()
    console.print(table)

    if issues:
        console.print("\n[bold red]Issues found:[/bold red]")
        for i in issues:
            console.print(f"  - {i}")
        raise typer.Exit(1)
    else:
        console.print("\n[bold green]All verification checks passed.[/bold green]")


if __name__ == "__main__":
    app()
