"""Lazy data store for the catalog wiki.

Reads from the rendered `wiki/` tree and `wiki/meta/*.jsonl` sidecars.
Caches per-process. Pure read-only, deterministic.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# wiki/ lives at the project root, two levels up from this file
_WIKI_DIR = Path(__file__).resolve().parent.parent / "wiki"


def wiki_dir() -> Path:
    return _WIKI_DIR


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown file into (frontmatter_dict, body_str).

    Returns ({}, text) if no frontmatter is present.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    try:
        fm = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        fm = {}
    body = text[end + 4:].lstrip("\n")
    return fm, body


def read_markdown(path: Path) -> tuple[dict[str, Any], str]:
    """Read a markdown file → (frontmatter, body)."""
    if not path.exists():
        return {}, ""
    return _parse_frontmatter(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Cached collections
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _catalog_index(lang: str) -> dict[str, dict[str, Any]]:
    """Map canonical_program_id → frontmatter dict for one language."""
    by_id: dict[str, dict[str, Any]] = {}
    base = _WIKI_DIR / lang / "programs"
    if not base.exists():
        return by_id
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        readme = d / "README.md"
        if not readme.exists():
            continue
        fm, _ = read_markdown(readme)
        pid = fm.get("canonical_program_id")
        if pid:
            by_id[pid] = fm
    return by_id


@lru_cache(maxsize=4)
def _subjects_index(lang: str) -> dict[str, dict[str, Any]]:
    """Map canonical_subject_id → frontmatter dict for one language."""
    by_id: dict[str, dict[str, Any]] = {}
    base = _WIKI_DIR / lang / "subjects"
    if not base.exists():
        return by_id
    for f in sorted(base.glob("*.md")):
        if f.name == "README.md":
            continue
        fm, _ = read_markdown(f)
        sid = fm.get("canonical_subject_id")
        if sid:
            by_id[sid] = fm
    return by_id


def all_programs(lang: str) -> list[dict[str, Any]]:
    """Return all program frontmatter records for a language."""
    return list(_catalog_index(lang).values())


def all_subjects(lang: str) -> list[dict[str, Any]]:
    return list(_subjects_index(lang).values())


def get_program_record(canonical_program_id: str) -> dict[str, Any] | None:
    """Look up a program by canonical_program_id (e.g. 'en/bachelor-foo')."""
    if "/" not in canonical_program_id:
        return None
    lang, _ = canonical_program_id.split("/", 1)
    return _catalog_index(lang).get(canonical_program_id)


def get_subject_record(canonical_subject_id: str) -> dict[str, Any] | None:
    if "/" not in canonical_subject_id:
        return None
    lang, _ = canonical_subject_id.split("/", 1)
    return _subjects_index(lang).get(canonical_subject_id)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def program_folder(canonical_program_id: str) -> Path:
    lang, slug = canonical_program_id.split("/", 1)
    return _WIKI_DIR / lang / "programs" / slug


def subject_file(canonical_subject_id: str) -> Path:
    lang, slug = canonical_subject_id.split("/", 1)
    return _WIKI_DIR / lang / "subjects" / f"{slug}.md"


def program_section_file(canonical_program_id: str, section: str) -> Path:
    return program_folder(canonical_program_id) / f"{section}.md"


# ---------------------------------------------------------------------------
# Pairings sidecar
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _pairings_by_program() -> dict[str, dict[str, Any]]:
    """Map canonical_program_id → pairing record (both EN and ES sides)."""
    out: dict[str, dict[str, Any]] = {}
    p = _WIKI_DIR / "meta" / "pairings.jsonl"
    if not p.exists():
        return out
    for line in p.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        out[rec["en_program_id"]] = rec
        out[rec["es_program_id"]] = rec
    return out


def get_pairing(canonical_program_id: str) -> dict[str, Any] | None:
    return _pairings_by_program().get(canonical_program_id)
