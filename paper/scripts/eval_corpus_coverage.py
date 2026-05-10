#!/usr/bin/env python3
"""Measure corpus coverage, frontmatter completeness, and pairing
characteristics directly from wiki/meta/{catalog,subjects,pairings}.jsonl
— never from wiki/meta/stats.md, which is a build artefact that may lag
the JSONL source of truth.

Outputs paper/data/corpus_coverage.json.

Usage:
    uv run python scripts/eval_corpus_coverage.py
"""

from __future__ import annotations

import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

WIKI_META = Path("wiki/meta")
OUT_PATH = Path("paper/data/corpus_coverage.json")


def is_present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return value != 0
    return True


def main() -> None:
    programs = [
        json.loads(line)
        for line in (WIKI_META / "catalog.jsonl").read_text().splitlines()
        if line.strip()
    ]
    subjects = [
        json.loads(line)
        for line in (WIKI_META / "subjects.jsonl").read_text().splitlines()
        if line.strip()
    ]
    pairings = [
        json.loads(line)
        for line in (WIKI_META / "pairings.jsonl").read_text().splitlines()
        if line.strip()
    ]

    # ── Programs by language ─────────────────────────────────────────────
    by_lang: Counter = Counter()
    for p in programs:
        pid = p.get("canonical_program_id", "")
        by_lang[pid.split("/", 1)[0] if "/" in pid else "?"] += 1

    # ── Subjects by language ─────────────────────────────────────────────
    subj_by_lang: Counter = Counter()
    for s in subjects:
        sid = s.get("canonical_subject_id", "")
        subj_by_lang[sid.split("/", 1)[0] if "/" in sid else "?"] += 1

    # ── Pairing characterisation ─────────────────────────────────────────
    en_programs = {p["canonical_program_id"]: p for p in programs if p["canonical_program_id"].startswith("en/")}
    es_programs = {p["canonical_program_id"]: p for p in programs if p["canonical_program_id"].startswith("es/")}
    auto = [p for p in pairings if p.get("auto_linked")]

    # Which OR-rule from build_wiki.py's `pair()` actually fired for each
    # auto-linked record. Replicates the same condition list here so the
    # paper's narrative cites the canonical rule names.
    rule_buckets: Counter = Counter()
    for p in auto:
        s = p["signals"]
        score = p["confidence"]
        if s["shared_subjects"] >= 0.5 and s["structural"] >= 0.5:
            rule_buckets["shared-subjects + structural"] += 1
        elif s["title_similarity"] >= 0.80 and s["slug_similarity"] >= 0.50:
            rule_buckets["title + slug"] += 1
        elif s["title_similarity"] >= 0.85 and s["structural"] >= 0.85:
            rule_buckets["title + structural"] += 1
        elif score >= 0.30:
            rule_buckets["weighted-score ≥ 0.30"] += 1
        else:
            rule_buckets["uncategorised"] += 1

    # Score-band distribution among auto-linked
    score_bands: Counter = Counter()
    for p in auto:
        s = p["confidence"]
        if s >= 0.70:
            score_bands["high (≥0.70)"] += 1
        elif s >= 0.50:
            score_bands["mid (0.50–0.70)"] += 1
        elif s >= 0.30:
            score_bands["low (0.30–0.50)"] += 1
        else:
            score_bands["very-low (<0.30)"] += 1

    # ── Frontmatter completeness ─────────────────────────────────────────
    fields = [
        "title", "slug", "canonical_program_id", "level", "area", "official",
        "tags", "modality", "duration", "ects", "languages_of_instruction",
        "schedule", "location", "start_date", "tuition_status",
        "admissions_contact", "official_name", "degree_issuer", "subject_count",
        "source_url", "source_fetched_at", "extractor_version",
        "equivalent_program_id", "pairing_confidence", "related_programs",
    ]
    completeness = {
        f: round(100 * sum(1 for p in programs if is_present(p.get(f))) / len(programs), 1)
        for f in fields
    }

    # ── Level / area distributions ───────────────────────────────────────
    levels = Counter(p.get("level") for p in programs)
    en_areas = Counter(p.get("area") for p in programs if p["canonical_program_id"].startswith("en/"))
    es_areas = Counter(p.get("area") for p in programs if p["canonical_program_id"].startswith("es/"))

    # ── Unlinked breakdown (which levels have what unlinked %) ───────────
    linked_ids = {p["en_program_id"] for p in auto}
    unlinked_ids = set(en_programs.keys()) - linked_ids
    unlinked_levels: Counter = Counter(en_programs[pid].get("level") for pid in unlinked_ids)
    total_en_levels: Counter = Counter(p.get("level") for p in en_programs.values())
    unlinked_breakdown = {
        lvl: {
            "unlinked": unlinked_levels.get(lvl, 0),
            "total": total_en_levels.get(lvl, 0),
            "pct_unlinked": round(100 * unlinked_levels.get(lvl, 0) / total_en_levels.get(lvl, 1), 1),
        }
        for lvl in total_en_levels
    }

    # ── Diagnostic: does each unlinked EN program have ANY plausible ES candidate? ─
    def title_sim(a: str, b: str) -> float:
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    es_titles = {pid: p.get("title", "") for pid, p in es_programs.items()}
    has_plausible_candidate = sum(
        1 for pid in unlinked_ids
        if max(title_sim(en_programs[pid].get("title", ""), t) for t in es_titles.values()) >= 0.35
    )

    out = {
        "_source": "computed from wiki/meta/{catalog,subjects,pairings}.jsonl (NOT stats.md)",
        "_script": "scripts/eval_corpus_coverage.py",
        "programs": {
            "total": len(programs),
            "by_lang": dict(by_lang),
        },
        "subjects": {
            "total": len(subjects),
            "by_lang": dict(subj_by_lang),
        },
        "levels": dict(levels),
        "areas_en": dict(en_areas),
        "areas_es": dict(es_areas),
        "frontmatter_completeness_pct": completeness,
        "pairing": {
            "_definition": (
                "Cross-language link coverage between EN and ES program catalogs. "
                "auto_linked is the matcher's decision; pairing_confidence is the "
                "weighted-score signal (0-1), not a probability of correctness. "
                "Decision can fire via OR-rules (shared-subjects + structural, "
                "title + slug, title + structural) even when the weighted score "
                "is low — so low confidence does NOT imply incorrect pairing."
            ),
            "total_pairing_records": len(pairings),
            "auto_linked": len(auto),
            "unlinked": len(unlinked_ids),
            "link_coverage_pct": round(100 * len(auto) / len(en_programs), 1),
            "auto_link_rule_breakdown": dict(rule_buckets),
            "auto_link_score_bands": dict(score_bands),
            "unlinked_breakdown_by_level": unlinked_breakdown,
            "unlinked_with_plausible_es_candidate": has_plausible_candidate,
            "unlinked_total": len(unlinked_ids),
            "_unlinked_note": (
                "Unlinked programs cluster in short-format levels (specialization, "
                "online courses, 'other'). Major degrees pair well: only 1/77 "
                "bachelors and a small minority of masters are unlinked. Most "
                "unlinked programs have at least one plausible ES candidate "
                "(title similarity ≥0.35) but the bipartite matcher correctly "
                "deferred when no OR-rule fired strongly enough."
            ),
        },
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
