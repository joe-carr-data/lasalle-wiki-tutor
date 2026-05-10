#!/usr/bin/env python3
"""Build the semantic-layer sidecar for the catalog wiki.

Reads the rendered wiki under ``wiki/<lang>/programs/*/`` plus
``data/structured.jsonl``, concatenates the right text per program
(title + tags + area + overview + goals + careers + curriculum subject
titles), embeds with Model2Vec ``potion-base-8M``, and writes:

    wiki/meta/embeddings_{lang}.npz             — float32 matrix [N x dim]
    wiki/meta/embeddings_{lang}_ids.jsonl       — {"row": i, "canonical_program_id": "..."}
    wiki/meta/embeddings_meta.json              — model name + version + dim + corpus_hash

The sidecar is loaded lazily by ``catalog_wiki_api.search`` at first
retrieval call. A startup-time health check verifies the metadata
matches the running code's expectations and falls back to lexical-only
on mismatch.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import typer
import yaml
from model2vec import StaticModel
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from scripts.common import STRUCTURED_PATH, WIKI_DIR

app = typer.Typer(
    help="Build the semantic-layer sidecar (Model2Vec embeddings) for the wiki.",
    add_completion=False,
)
console = Console()

DEFAULT_MODEL = "minishlab/potion-base-8M"
META_DIR = WIKI_DIR / "meta"
SIDECAR_VERSION = "1.0"

# Maximum text per program — trim to keep embeddings consistent across program types.
MAX_TEXT_CHARS = 4000


def _load_program_records() -> dict[str, dict[str, Any]]:
    """Load program-base records from data/structured.jsonl, keyed by URL."""
    records: dict[str, dict[str, Any]] = {}
    if not STRUCTURED_PATH.exists():
        return records
    for line in STRUCTURED_PATH.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("kind") == "program-base":
            records[rec["url"]] = rec
    return records


def _load_subpage_bodies(parent_url: str) -> dict[str, str]:
    """Pull goals/careers body_md from data/structured.jsonl for one parent."""
    out: dict[str, str] = {}
    if not STRUCTURED_PATH.exists():
        return out
    for line in STRUCTURED_PATH.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("kind") == "program-subpage" and rec.get("parent_url") == parent_url:
            section = rec.get("section", "")
            if section in {"goals", "careers"}:
                out[section] = rec.get("body_md", "") or ""
            elif section == "curriculum":
                # Use only the linked subject titles (not full body markdown)
                titles = []
                for year in rec.get("curriculum_years", []) or []:
                    for sec in year.get("sections", []):
                        for s in sec.get("subjects", []):
                            t = (s.get("title") or "").strip()
                            if t:
                                titles.append(t)
                if titles:
                    out["curriculum_subjects"] = " ".join(titles)
    return out


def _read_program_frontmatter(readme_path: Path) -> dict[str, Any]:
    if not readme_path.exists():
        return {}
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


def _build_text_for_program(fm: dict[str, Any], extras: dict[str, str]) -> str:
    """Concatenate fields into the text we'll embed for this program.

    Ordering matters less for static embeddings (Model2Vec averages
    token vectors), but we still front-load high-signal fields so the
    truncation cap doesn't drop them.
    """
    parts: list[str] = [
        fm.get("title", ""),
        fm.get("official_name", ""),
        " ".join(fm.get("tags") or []),
        (fm.get("area") or "").replace("-", " "),
        (fm.get("level") or ""),
        " ".join(fm.get("languages_of_instruction") or []),
        extras.get("goals", ""),
        extras.get("careers", ""),
        extras.get("curriculum_subjects", ""),
    ]
    text = " ".join(p for p in parts if p)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TEXT_CHARS]


def _identity_signature(canonical_program_ids: list[str], model_name: str) -> str:
    """Cheap, stable signature of (program identity set + model name).

    Captures program presence and model identity but **not** the body
    content — so minor markdown edits to a program don't invalidate the
    sidecar. Catching content drift is the responsibility of
    ``extractor_version`` / a separate content hash if we ever need it.

    Used at sidecar build time and validated at runtime. If the runtime
    catalog has different program ids than the sidecar was built from,
    the signature mismatches and the semantic layer falls back to lexical.
    """
    h = hashlib.sha256()
    h.update(model_name.encode("utf-8"))
    h.update(b"\x00")
    for pid in sorted(canonical_program_ids):
        h.update(b"\x00")
        h.update(pid.encode("utf-8"))
    return h.hexdigest()


@app.command()
def build(
    model_name: str = typer.Option(DEFAULT_MODEL, help="Model2Vec model id"),
    languages: str = typer.Option("en,es", help="Comma-separated language codes"),
) -> None:
    """Build embedding sidecars under wiki/meta/."""
    if not WIKI_DIR.exists():
        console.print("[red]No wiki/ tree found. Run build_wiki render+index first.[/red]")
        raise typer.Exit(1)

    META_DIR.mkdir(parents=True, exist_ok=True)
    program_records = _load_program_records()

    console.print(f"Loading model [bold]{model_name}[/bold]…")
    model = StaticModel.from_pretrained(model_name)
    dim = model.dim

    meta: dict[str, Any] = {
        "sidecar_version": SIDECAR_VERSION,
        "model_name": model_name,
        "vector_dim": dim,
        "languages": {},
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    for lang in [l.strip() for l in languages.split(",") if l.strip()]:
        program_dir = WIKI_DIR / lang / "programs"
        if not program_dir.exists():
            console.print(f"[yellow]No programs for lang={lang}; skipping[/yellow]")
            continue

        # Collect (program_id, text) pairs in deterministic order
        pairs: list[tuple[str, str, str]] = []  # (canonical_program_id, source_url, text)
        for d in sorted(program_dir.iterdir()):
            if not d.is_dir():
                continue
            readme = d / "README.md"
            fm = _read_program_frontmatter(readme)
            pid = fm.get("canonical_program_id")
            if not pid:
                continue
            source_url = fm.get("source_url", "")
            extras = _load_subpage_bodies(source_url) if source_url in program_records else {}
            text = _build_text_for_program(fm, extras)
            pairs.append((pid, source_url, text))

        if not pairs:
            console.print(f"[yellow]No programs to embed for lang={lang}[/yellow]")
            continue

        ids = [p[0] for p in pairs]
        texts = [p[2] for p in pairs]
        chash = _identity_signature(ids, model_name)

        console.print(f"  /{lang}/: embedding [bold]{len(texts)}[/bold] programs…")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(f"  encoding /{lang}/", total=1)
            vectors = np.asarray(model.encode(texts), dtype=np.float32)
            progress.advance(task)

        # L2-normalize so cosine similarity is just a dot product later
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms

        npz_path = META_DIR / f"embeddings_{lang}.npz"
        np.savez(npz_path, vectors=vectors)
        ids_path = META_DIR / f"embeddings_{lang}_ids.jsonl"
        with ids_path.open("w", encoding="utf-8") as f:
            for i, (pid, source_url, _) in enumerate(pairs):
                f.write(json.dumps({"row": i, "canonical_program_id": pid, "source_url": source_url}, ensure_ascii=False) + "\n")

        meta["languages"][lang] = {
            "n_programs": len(pairs),
            "corpus_hash": chash,
            "matrix_path": str(npz_path.relative_to(WIKI_DIR)),
            "ids_path": str(ids_path.relative_to(WIKI_DIR)),
        }
        console.print(f"  /{lang}/: wrote [green]{npz_path.name}[/green] "
                       f"({vectors.shape[0]} × {vectors.shape[1]}, {npz_path.stat().st_size // 1024} KB) "
                       f"+ {ids_path.name}")

    meta_path = META_DIR / "embeddings_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    console.print(f"\nSidecar metadata → [green]{meta_path}[/green]")


if __name__ == "__main__":
    app()
