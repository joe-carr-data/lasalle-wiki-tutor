"""Lexical search over the wiki using BM25 with weighted fields.

Replaces the Phase 3 token-overlap scorer. Two ranker modes:

- ``token_overlap`` (legacy): the original simple counter, kept as a
  feature-flagged fallback for ablation/debugging.
- ``bm25`` (default): BM25-Field score with synonym expansion of the
  query, plus a small "type prior" so generic-degree intents do not
  get dominated by 1-week summer/workshop programs.

The BM25 index is **lazy-built on first call** per process and cached
for the lifetime of the process. Index sources:

- Program frontmatter (title, tags, area, level, slug) — fast.
- Program README.md body and selected section files (goals, careers).
- Per-program "tokens" cache so subsequent searches are O(N_programs).

Body text lives in the rendered wiki tree (`wiki/<lang>/programs/...`),
not in `data/structured.jsonl`, so the package stays self-contained
under `wiki/`.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from . import store
from .synonyms import expand_query

log = logging.getLogger("catalog_wiki_api.search")

# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-zA-ZÀ-ÿ0-9]{2,}")
_STOP = {
    # English
    "the", "and", "for", "with", "from", "into", "this", "that",
    "you", "your", "are", "was", "but", "not", "can", "all", "any",
    "have", "has", "had", "our", "their", "its", "they", "their",
    # Spanish
    "los", "las", "una", "uno", "del", "para", "por", "con", "sin",
    "que", "como", "más", "menos", "este", "esta", "estos", "estas",
    "tus", "sus", "ser", "estar", "haber", "muy", "ya", "no",
}


def _tokenise(text: str) -> list[str]:
    """Lowercase + tokenise + filter short stopwords."""
    if not text:
        return []
    return [t for t in (m.group().lower() for m in _WORD_RE.finditer(text))
            if t not in _STOP and len(t) >= 2]


# ---------------------------------------------------------------------------
# Field weights (BM25-F-style: per-field score is weight * BM25(query, field))
# ---------------------------------------------------------------------------

FIELD_WEIGHTS = {
    "title": 4.0,
    "tags": 3.0,
    "area": 2.0,
    "level": 1.5,
    "body": 1.0,
    "slug": 0.5,
}

# BM25 hyperparameters (Robertson-Sparck-Jones defaults)
BM25_K1 = 1.5
BM25_B = 0.75


# ---------------------------------------------------------------------------
# Long-degree intent detection (used by the type prior)
# ---------------------------------------------------------------------------

_LONG_INTENT_RE = re.compile(
    r"\b(bachelor|degree|grado|m[áa]ster|master|doctorate|doctorado|"
    r"long|four[- ]year|cuatro\s+a[ñn]os|completo|carrera)\b",
    re.IGNORECASE,
)
_SHORT_INTENT_RE = re.compile(
    r"\b(course|curso|workshop|short|breve|weekend|fin\s+de\s+semana|summer|verano|"
    r"intensive|intensivo|seminar|seminario|bootcamp)\b",
    re.IGNORECASE,
)

# Boost values applied to the final BM25 score.
LONG_LEVELS = {"bachelor", "master", "doctorate"}
SHORT_LEVELS = {"specialization", "summer", "online", "other"}


def _intent_modifier(query: str, level: str) -> float:
    """Return a multiplicative boost (>1) or demote (<1) based on query intent.

    Applies two layers:
      1. A baseline level prior — substantive degrees (bachelor/master/doctorate)
         get a tiny lift; 1-week "summer immersion"-style programs get a tiny
         demote. Reflects what most students searching the catalog want by default.
      2. An intent override — when the query explicitly signals "long degree"
         or "short course", flip the prior decisively in that direction.
    """
    long_hit = bool(_LONG_INTENT_RE.search(query))
    short_hit = bool(_SHORT_INTENT_RE.search(query))
    if long_hit and not short_hit:
        return 1.25 if level in LONG_LEVELS else 0.75
    if short_hit and not long_hit:
        return 1.20 if level in SHORT_LEVELS else 0.85
    # Baseline prior: gently favor substantive degrees over 1-week immersions.
    if level in LONG_LEVELS:
        return 1.10
    if level == "summer":
        return 0.85
    return 1.0


# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------


def _load_section_body(path: Path) -> str:
    """Read a markdown section file and strip frontmatter + headings."""
    if not path.exists():
        return ""
    fm, body = store.read_markdown(path)
    # Drop heading lines (`# Title`, `## Section`)
    return "\n".join(line for line in body.splitlines() if not line.startswith("#"))


def _build_program_doc(program_record: dict[str, Any]) -> dict[str, list[str]]:
    """Return a per-field token map for a program.

    Title, tags, area, level, slug come from frontmatter (cheap).
    Body is the concatenation of overview (in README.md) and goals +
    careers section files. We deliberately do NOT include the full
    syllabus list — subject titles add a lot of noise to BM25.
    """
    title = program_record.get("title", "")
    tags = " ".join(program_record.get("tags") or [])
    area = (program_record.get("area") or "").replace("-", " ")
    level = program_record.get("level", "")
    slug = (program_record.get("slug", "") or "").replace("-", " ")

    canonical_id = program_record.get("canonical_program_id", "")
    folder = store.program_folder(canonical_id) if canonical_id else None
    body_parts: list[str] = []
    if folder is not None:
        # README body excludes frontmatter; we want the overview prose.
        readme = folder / "README.md"
        if readme.exists():
            _, body = store.read_markdown(readme)
            body_parts.append(body)
        for section in ("goals", "careers"):
            body_parts.append(_load_section_body(folder / f"{section}.md"))
    body = "\n".join(p for p in body_parts if p)

    # Add the official_name and short_description (rich frontmatter fields)
    body = " ".join([
        body,
        program_record.get("official_name", "") or "",
    ]).strip()

    return {
        "title": _tokenise(title),
        "tags": _tokenise(tags),
        "area": _tokenise(area),
        "level": _tokenise(level),
        "slug": _tokenise(slug),
        "body": _tokenise(body),
    }


# ---------------------------------------------------------------------------
# BM25 index — lazy-built per language, cached per process
# ---------------------------------------------------------------------------


class _BM25Index:
    """BM25-F-style multi-field scorer for one language's program corpus."""

    def __init__(self, programs: list[dict[str, Any]]) -> None:
        self.programs = programs
        # Per-field structures: tokens, doc lengths, average length, df, idf
        self.field_tokens: dict[str, list[list[str]]] = {f: [] for f in FIELD_WEIGHTS}
        self.field_lens: dict[str, list[int]] = {f: [] for f in FIELD_WEIGHTS}
        self.field_avgdl: dict[str, float] = {}
        self.field_df: dict[str, dict[str, int]] = {f: {} for f in FIELD_WEIGHTS}
        self.field_idf: dict[str, dict[str, float]] = {f: {} for f in FIELD_WEIGHTS}
        # Per-doc cache of frequency tables: list of {field: {token: tf}}
        self.field_tfs: list[dict[str, dict[str, int]]] = []

        for p in programs:
            doc = _build_program_doc(p)
            tfs: dict[str, dict[str, int]] = {}
            for field, tokens in doc.items():
                self.field_tokens[field].append(tokens)
                self.field_lens[field].append(len(tokens))
                tf: dict[str, int] = {}
                seen: set[str] = set()
                for t in tokens:
                    tf[t] = tf.get(t, 0) + 1
                    if t not in seen:
                        self.field_df[field][t] = self.field_df[field].get(t, 0) + 1
                        seen.add(t)
                tfs[field] = tf
            self.field_tfs.append(tfs)

        n = max(1, len(programs))
        for field in FIELD_WEIGHTS:
            lens = self.field_lens[field]
            self.field_avgdl[field] = sum(lens) / max(1, len(lens))
            # Robertson-Sparck-Jones IDF: ln((N - df + 0.5) / (df + 0.5) + 1)
            for tok, df in self.field_df[field].items():
                self.field_idf[field][tok] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query_tokens: list[str], program_idx: int) -> float:
        """Return the BM25-F sum over fields for one document."""
        if not query_tokens:
            return 0.0
        total = 0.0
        for field, weight in FIELD_WEIGHTS.items():
            tf_map = self.field_tfs[program_idx][field]
            avgdl = max(1.0, self.field_avgdl[field])
            doc_len = self.field_lens[field][program_idx]
            field_score = 0.0
            for q in query_tokens:
                tf = tf_map.get(q, 0)
                if tf == 0:
                    continue
                idf = self.field_idf[field].get(q, 0.0)
                # BM25 saturation curve
                num = tf * (BM25_K1 + 1)
                denom = tf + BM25_K1 * (1 - BM25_B + BM25_B * doc_len / avgdl)
                field_score += idf * num / denom
            total += weight * field_score
        return total


@lru_cache(maxsize=4)
def _bm25_index_for(lang: str) -> _BM25Index:
    """Build (or reuse) the BM25 index for a language."""
    programs = store.all_programs(lang)
    return _BM25Index(programs)


# ---------------------------------------------------------------------------
# Semantic layer — Model2Vec sidecar, lazy-loaded
# ---------------------------------------------------------------------------

EXPECTED_MODEL_NAME = "minishlab/potion-base-8M"
EXPECTED_VECTOR_DIM = 256
EXPECTED_SIDECAR_VERSION = "1.0"


@lru_cache(maxsize=1)
def _semantic_meta() -> dict[str, Any] | None:
    """Read wiki/meta/embeddings_meta.json once; return None if missing/incompatible."""
    path = store.wiki_dir() / "meta" / "embeddings_meta.json"
    if not path.exists():
        log.warning("Semantic sidecar metadata missing at %s — falling back to lexical-only.", path)
        return None
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not parse semantic sidecar metadata: %s — falling back to lexical-only.", exc)
        return None
    # Compatibility checks
    if meta.get("sidecar_version") != EXPECTED_SIDECAR_VERSION:
        log.warning("Semantic sidecar version %r != expected %r — falling back to lexical-only.",
                    meta.get("sidecar_version"), EXPECTED_SIDECAR_VERSION)
        return None
    if meta.get("model_name") != EXPECTED_MODEL_NAME:
        log.warning("Semantic sidecar model %r != expected %r — falling back to lexical-only.",
                    meta.get("model_name"), EXPECTED_MODEL_NAME)
        return None
    if meta.get("vector_dim") != EXPECTED_VECTOR_DIM:
        log.warning("Semantic sidecar dim %r != expected %r — falling back to lexical-only.",
                    meta.get("vector_dim"), EXPECTED_VECTOR_DIM)
        return None
    return meta


@lru_cache(maxsize=1)
def _semantic_model():
    """Load the Model2Vec model once. Returns None if the dep or model is unavailable."""
    try:
        from model2vec import StaticModel
    except ImportError:
        log.warning("model2vec not installed — falling back to lexical-only.")
        return None
    try:
        return StaticModel.from_pretrained(EXPECTED_MODEL_NAME)
    except Exception as exc:  # broad: network errors, model not cached, etc.
        log.warning("Could not load Model2Vec model: %s — falling back to lexical-only.", exc)
        return None


@lru_cache(maxsize=4)
def _semantic_matrix_for(lang: str):
    """Return (vectors, ids) for a language, or None if unavailable.

    `vectors` is an L2-normalized float32 ndarray of shape (N, dim).
    `ids` is a list[str] of canonical_program_ids aligned to rows.
    """
    meta = _semantic_meta()
    if meta is None:
        return None
    lang_meta = (meta.get("languages") or {}).get(lang)
    if lang_meta is None:
        log.warning("No semantic sidecar for lang=%r — falling back to lexical-only.", lang)
        return None
    try:
        import numpy as np  # imported lazily so the lexical-only path has no numpy req
        npz_path = store.wiki_dir() / lang_meta["matrix_path"]
        with np.load(npz_path) as data:
            vectors = data["vectors"]
        ids: list[str] = []
        ids_path = store.wiki_dir() / lang_meta["ids_path"]
        with ids_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                ids.append(rec["canonical_program_id"])
        if vectors.shape[0] != len(ids):
            log.warning("Semantic sidecar shape mismatch for lang=%r — falling back.", lang)
            return None
        return vectors, ids
    except Exception as exc:
        log.warning("Could not load semantic sidecar for %r: %s", lang, exc)
        return None


def _semantic_score(query: str, lang: str) -> dict[str, float] | None:
    """Return {canonical_program_id: cosine_similarity} for the query, or None."""
    matrix = _semantic_matrix_for(lang)
    if matrix is None:
        return None
    model = _semantic_model()
    if model is None:
        return None
    import numpy as np
    vectors, ids = matrix
    qv = np.asarray(model.encode([query]), dtype=np.float32)[0]
    # L2-normalize the query (sidecar vectors already normalized)
    qnorm = float(np.linalg.norm(qv))
    if qnorm == 0:
        return None
    qv = qv / qnorm
    sims = vectors @ qv
    # Map to {id: cosine}
    return {pid: float(sim) for pid, sim in zip(ids, sims)}


# ---------------------------------------------------------------------------
# Public scoring API (replaces the Phase 3 token-overlap scorer)
# ---------------------------------------------------------------------------


RankerMode = Literal["hybrid", "lexical", "semantic", "token_overlap", "bm25"]


def _ranker_mode() -> str:
    """Default mode: hybrid. Overridden by LASALLE_RANKER_MODE env var.

    Accepted values: hybrid (default), lexical (BM25 only), semantic (cosine
    only), bm25 (alias for lexical), token_overlap (legacy fallback).
    """
    return os.environ.get("LASALLE_RANKER_MODE", "hybrid").lower()


# Hybrid blend: final = LEX_WEIGHT * normalized_bm25 + SEM_WEIGHT * cosine
LEX_WEIGHT = 0.55
SEM_WEIGHT = 0.45


def score_program(query: str, program: dict[str, Any]) -> float:
    """Single-program score — used by tests and CLI ad-hoc.

    For BM25 we still build/use the per-language index (small corpus).
    """
    if not query:
        return 0.0
    if _ranker_mode() == "token_overlap":
        return _token_overlap_score(query, program)
    lang = (program.get("canonical_program_id", "") or "/").split("/", 1)[0] or "en"
    idx = _bm25_index_for(lang)
    # Find the doc index for this program
    canonical = program.get("canonical_program_id", "")
    for i, p in enumerate(idx.programs):
        if p.get("canonical_program_id") == canonical:
            qtokens = expand_query(query)
            base = idx.score(qtokens, i)
            return base * _intent_modifier(query, p.get("level", ""))
    return 0.0


def rank_programs(
    query: str,
    programs: list[dict[str, Any]],
    top_k: int = 10,
) -> list[tuple[float, dict[str, Any]]]:
    """Rank ``programs`` (a filtered subset) against ``query``.

    Mode selection (env var ``LASALLE_RANKER_MODE``):
        hybrid (default)  : 0.55 * BM25 + 0.45 * cosine + intent prior
        lexical / bm25    : BM25 only + intent prior
        semantic          : cosine only (no synonym expansion)
        token_overlap     : legacy fallback
    """
    if not query or not programs:
        return []

    mode = _ranker_mode()
    if mode == "token_overlap":
        scored = [(_token_overlap_score(query, p), p) for p in programs]
        scored = [(s, p) for s, p in scored if s > 0]
        scored.sort(key=lambda x: -x[0])
        return scored[:top_k]

    first = programs[0]
    lang = (first.get("canonical_program_id", "") or "/").split("/", 1)[0] or "en"

    # Lexical (BM25) scores
    lex: dict[str, float] = {}
    idx = _bm25_index_for(lang)
    qtokens = expand_query(query)
    canonical_to_idx = {
        p.get("canonical_program_id"): i for i, p in enumerate(idx.programs)
    }
    for p in programs:
        pid = p.get("canonical_program_id")
        i = canonical_to_idx.get(pid)
        if i is None:
            continue
        s = idx.score(qtokens, i)
        if s > 0:
            lex[pid] = s

    # Semantic (cosine) scores — only if mode wants them
    sem: dict[str, float] | None = None
    if mode in ("hybrid", "semantic"):
        sem = _semantic_score(query, lang)
        # If the sidecar is unavailable, gracefully degrade to lexical
        if sem is None and mode == "semantic":
            log.warning("Semantic sidecar unavailable; degrading to BM25 for this query.")
            mode = "lexical"

    # Combine. Both signals are pool-normalised to [0, 1] so a rare-but-
    # high BM25 hit doesn't always crush a strong semantic match.
    scored: list[tuple[float, dict[str, Any]]] = []
    max_lex = max(lex.values()) if lex else 0.0
    norm_lex = {pid: (s / max_lex) if max_lex > 0 else 0.0 for pid, s in lex.items()}
    if sem is not None:
        # Use only the pool we're ranking right now, not all corpus rows
        pool_ids = {p.get("canonical_program_id") for p in programs}
        pool_sem = {pid: max(0.0, sim) for pid, sim in sem.items() if pid in pool_ids}
        max_sem = max(pool_sem.values()) if pool_sem else 0.0
        norm_sem = {pid: (s / max_sem) if max_sem > 0 else 0.0 for pid, s in pool_sem.items()}
    else:
        norm_sem = {}

    for p in programs:
        pid = p.get("canonical_program_id")
        lex_s = norm_lex.get(pid, 0.0)
        sem_s = norm_sem.get(pid, 0.0)
        if mode == "lexical" or mode == "bm25":
            base = lex_s
        elif mode == "semantic":
            base = sem_s
        else:  # hybrid
            base = LEX_WEIGHT * lex_s + SEM_WEIGHT * sem_s
        if base <= 0:
            continue
        score = base * _intent_modifier(query, p.get("level", ""))
        scored.append((score, p))

    scored.sort(key=lambda x: -x[0])
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Legacy token-overlap scorer (kept for ablation / fallback)
# ---------------------------------------------------------------------------


def _token_overlap_score(query: str, program: dict[str, Any]) -> float:
    qt = set(_tokenise(query))
    if not qt:
        return 0.0
    title_t = set(_tokenise(program.get("title", "")))
    tags_t = {t.lower() for t in (program.get("tags") or [])}
    slug_t = set((program.get("slug", "") or "").lower().split("-"))
    area = (program.get("area") or "").replace("-", " ").lower()
    level = (program.get("level") or "").lower()
    score = 0.0
    score += len(qt & title_t) * 1.0
    score += len(qt & tags_t) * 0.6
    score += len(qt & slug_t) * 0.3
    if any(tok in area for tok in qt):
        score += 0.4
    if level and level in qt:
        score += 0.4
    return score / max(1.0, len(qt))


def reset_index_cache() -> None:
    """Clear the BM25 index cache. Used by tests after wiki regeneration."""
    _bm25_index_for.cache_clear()
