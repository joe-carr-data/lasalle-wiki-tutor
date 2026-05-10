#!/usr/bin/env python3
"""Run the BENCHMARK from tests/test_search_failure_benchmark.py across
all four ranker modes (hybrid, lexical, semantic, token_overlap) and save
top-1 / top-3 hit rates per mode to paper/data/ablation_results.json.

Usage:
    uv run python scripts/eval_ranker_ablation.py
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path

# Make catalog_wiki_api importable when running this script directly
# rather than as `uv run python -m paper.scripts.eval_ranker_ablation`.
# Script lives at paper/scripts/, so the repo root is three parents up.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Same queries we use in the regression test, plus a handful of bilingual
# extension queries that stress cross-language matching specifically.
BENCHMARK = [
    # AI / ML / data
    ("machine learning", "en", ["artificial intelligence", "ai-data-science"]),
    ("deep learning", "en", ["artificial intelligence", "ai-data-science"]),
    ("data analysis", "en", ["data", "analytics"]),
    ("AI", "en", ["artificial intelligence", "ai-data-science"]),
    # Cybersecurity colloquial
    ("hacking", "en", ["cybersecurity"]),
    ("ethical hacking", "en", ["cybersecurity"]),
    # Entrepreneurship colloquial
    ("startup", "en", ["entrepreneur", "innovation", "business"]),
    # Game development
    ("game development", "en", ["videogame", "multimedia", "animation"]),
    ("video games", "en", ["videogame", "multimedia", "animation"]),
    # Programming
    ("programming", "en", ["programming", "computer", "software"]),
    # Spanish queries on EN catalog (mixed-language student behaviour)
    ("ciberseguridad", "en", ["cybersecurity"]),
    ("inteligencia artificial", "en", ["artificial intelligence", "ai-data-science"]),
    # ES queries on ES catalog
    ("aprendizaje automático", "es", ["inteligencia artificial", "ai-data-science"]),
    ("ciberseguridad", "es", ["ciberseguridad", "cybersecurity"]),
    ("emprendimiento", "es", ["business-management", "innovaci"]),
]

# Bilingual extension queries — added to stress cross-lingual cases.
EXTENSION = [
    # Spanish word, EN catalog
    ("informática", "en", ["computer", "informatic"]),
    ("animación", "en", ["animation"]),
    # English word, ES catalog
    ("data science", "es", ["data", "datos", "ai-data-science"]),
    ("project management", "es", ["project", "proyecto", "gestion"]),
    ("architecture", "es", ["arquitectura", "architecture"]),
]

ALL_QUERIES = BENCHMARK + EXTENSION
MODES = ["hybrid", "lexical", "semantic", "token_overlap"]


def hit(payload, expected, k: int) -> bool:
    """True iff any expected substring appears in the top-k results."""
    results = payload["results"][:k]
    haystack = " ".join(
        f"{r.get('title','').lower()}|{r.get('area','').lower()}"
        for r in results
    )
    return any(needle.lower() in haystack for needle in expected)


def run_mode(mode: str) -> dict:
    """Set LASALLE_RANKER_MODE and run the full benchmark. Returns per-query results."""
    os.environ["LASALLE_RANKER_MODE"] = mode
    # Force reimport so the module-level mode pickup is fresh.
    import catalog_wiki_api  # noqa
    importlib.reload(catalog_wiki_api)
    api = catalog_wiki_api

    per_query = []
    for q, lang, expected in ALL_QUERIES:
        t0 = time.perf_counter()
        payload = api.search_programs(q, lang=lang, top_k=10)
        ms = (time.perf_counter() - t0) * 1000
        per_query.append({
            "query": q,
            "lang": lang,
            "expected_any": expected,
            "top1_hit": hit(payload, expected, 1),
            "top3_hit": hit(payload, expected, 3),
            "top5_hit": hit(payload, expected, 5),
            "latency_ms": round(ms, 1),
            "top3_titles": [r.get("title", "") for r in payload["results"][:3]],
        })

    return {
        "mode": mode,
        "per_query": per_query,
        "summary": {
            "n": len(per_query),
            "top1_hits": sum(1 for r in per_query if r["top1_hit"]),
            "top3_hits": sum(1 for r in per_query if r["top3_hit"]),
            "top5_hits": sum(1 for r in per_query if r["top5_hit"]),
            "top1_rate": round(100 * sum(1 for r in per_query if r["top1_hit"]) / len(per_query), 1),
            "top3_rate": round(100 * sum(1 for r in per_query if r["top3_hit"]) / len(per_query), 1),
            "top5_rate": round(100 * sum(1 for r in per_query if r["top5_hit"]) / len(per_query), 1),
            "median_latency_ms": round(sorted(r["latency_ms"] for r in per_query)[len(per_query) // 2], 1),
        },
    }


def main() -> None:
    out: dict = {"modes": {}, "queries": ALL_QUERIES}
    for mode in MODES:
        print(f"\n=== {mode} ===")
        result = run_mode(mode)
        out["modes"][mode] = result
        s = result["summary"]
        print(f"  top-1: {s['top1_hits']}/{s['n']} = {s['top1_rate']}%")
        print(f"  top-3: {s['top3_hits']}/{s['n']} = {s['top3_rate']}%")
        print(f"  top-5: {s['top5_hits']}/{s['n']} = {s['top5_rate']}%")
        print(f"  median latency: {s['median_latency_ms']} ms")
        for r in result["per_query"]:
            mark = "✓" if r["top3_hit"] else "✗"
            print(f"    {mark} [{r['lang']}] {r['query']!r:32s} -> {r['top3_titles'][0][:50] if r['top3_titles'] else '(none)':50s}")

    Path("paper/data").mkdir(parents=True, exist_ok=True)
    Path("paper/data/ablation_results.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print("\nWrote paper/data/ablation_results.json")


if __name__ == "__main__":
    main()
