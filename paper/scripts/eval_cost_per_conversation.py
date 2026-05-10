#!/usr/bin/env python3
"""Estimate per-turn and per-conversation cost from Agno session
documents. Agno persists each run with `usage` containing prompt_tokens,
completion_tokens, and a derived total. We multiply by the gpt-5.4
on-demand price (input $1.50 / MTok, cached $0.15 / MTok, output
$10 / MTok per the published list at the time of writing) to get a
dollar estimate.

Usage (on the EC2 box, or anywhere with access to the live Mongo):
    uv run python paper/scripts/eval_cost_per_conversation.py > paper/data/cost_raw.json

Notes:
    - Costs are an APPROXIMATION. The OpenAI Responses API also bills
      for reasoning tokens that are sometimes accounted under output
      tokens, sometimes separately. Treat the totals as upper-bound
      back-of-envelope.
    - Cache hits are not separately reflected in Agno's recorded usage
      so we cannot split cached vs uncached input tokens here.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, "/opt/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import asyncio
from pymongo import AsyncMongoClient

# gpt-5.4 list prices (US$/1M tokens) as of paper drafting.
PRICE_INPUT_PER_MTOK = 1.50
PRICE_OUTPUT_PER_MTOK = 10.00


async def main() -> None:
    uri = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("MONGO_DATABASE", "lasalle_catalog_assistant")
    client = AsyncMongoClient(uri)
    db = client[db_name]

    sessions = db["wiki_tutor_agent_sessions"]
    docs = [d async for d in sessions.find({})]

    per_conversation: list[dict] = []
    per_turn: list[dict] = []
    for s in docs:
        sid = s.get("session_id")
        runs = s.get("runs", []) or []
        conv_in = 0
        conv_out = 0
        for r in runs:
            usage = r.get("metrics") or r.get("usage") or {}
            in_toks = (
                usage.get("input_tokens")
                or usage.get("prompt_tokens")
                or 0
            )
            out_toks = (
                usage.get("output_tokens")
                or usage.get("completion_tokens")
                or 0
            )
            cost = (
                in_toks * PRICE_INPUT_PER_MTOK / 1_000_000
                + out_toks * PRICE_OUTPUT_PER_MTOK / 1_000_000
            )
            per_turn.append({
                "session_id": sid,
                "run_id": r.get("run_id"),
                "input_tokens": in_toks,
                "output_tokens": out_toks,
                "cost_usd": round(cost, 6),
            })
            conv_in += in_toks
            conv_out += out_toks
        if runs:
            per_conversation.append({
                "session_id": sid,
                "turns": len(runs),
                "input_tokens": conv_in,
                "output_tokens": conv_out,
                "cost_usd": round(
                    conv_in * PRICE_INPUT_PER_MTOK / 1_000_000
                    + conv_out * PRICE_OUTPUT_PER_MTOK / 1_000_000,
                    6,
                ),
            })

    def summary(values: list[float]) -> dict:
        if not values:
            return {}
        vs = sorted(values)
        n = len(vs)
        return {
            "n": n,
            "min": round(min(vs), 6),
            "median": round(statistics.median(vs), 6),
            "p95": round(vs[int(0.95 * (n - 1))], 6),
            "max": round(max(vs), 6),
            "mean": round(statistics.mean(vs), 6),
        }

    out = {
        "_source": "Agno session documents in MongoDB",
        "_pricing_assumptions_usd_per_mtok": {
            "input": PRICE_INPUT_PER_MTOK,
            "output": PRICE_OUTPUT_PER_MTOK,
        },
        "_caveats": [
            "Reasoning tokens may be included in output tokens depending on Agno version.",
            "Cached-input pricing is not differentiated here; OpenAI billing is the source of truth.",
        ],
        "turns_total": len(per_turn),
        "conversations_total": len(per_conversation),
        "per_turn_cost_usd_summary": summary([t["cost_usd"] for t in per_turn]),
        "per_turn_input_tokens_summary": summary([t["input_tokens"] for t in per_turn]),
        "per_turn_output_tokens_summary": summary([t["output_tokens"] for t in per_turn]),
        "per_conversation_cost_usd_summary": summary([c["cost_usd"] for c in per_conversation]),
        "per_conversation_turns_summary": summary([c["turns"] for c in per_conversation]),
        "sample_per_turn": per_turn[:20],
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
