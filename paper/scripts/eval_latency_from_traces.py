#!/usr/bin/env python3
"""Export per-tool latency from the live wiki_tutor_turn_traces collection.

Runs ON the EC2 box (e.g. via `aws ssm send-command`). Uses the
application's pymongo client to read from the production trace store.

Writes paper/data/latency_raw.json to stdout (caller redirects).

Local usage (against a local mongo):
    uv run python paper/scripts/eval_latency_from_traces.py > paper/data/latency_raw.json

Remote usage (against the production EC2 instance):
    B64=$(base64 < paper/scripts/eval_latency_from_traces.py | tr -d '\n')
    aws ssm send-command --instance-ids <i-...> \\
        --document-name AWS-RunShellScript \\
        --parameters "commands=[\"echo $B64 | base64 -d > /tmp/exp.py && cd /opt/app && sudo -u app .venv/bin/python /tmp/exp.py 2>/dev/null\"]"
    # Then fetch the StandardOutputContent from aws ssm get-command-invocation
    # and write it to paper/data/latency_raw.json.
"""
import json
import statistics
import sys
import os

# When run on the EC2 box the app code lives at /opt/app; locally we run
# from the repo root. Add both to sys.path so pymongo's AsyncMongoClient
# import works regardless of cwd.
sys.path.insert(0, "/opt/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import asyncio
from pymongo import AsyncMongoClient


async def main():
    uri = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    db_name = os.environ.get("MONGO_DATABASE", "lasalle_catalog_assistant")
    client = AsyncMongoClient(uri)
    coll = client[db_name]["wiki_tutor_turn_traces"]
    docs = [d async for d in coll.find({})]

    print(json.dumps({"_loaded_traces": len(docs)}), file=sys.stderr)

    per_tool: dict[str, list[float]] = {}
    total_thoughts = 0
    total_tools = 0
    for d in docs:
        for t in d.get("tool_timings", []):
            name = t.get("name", "?")
            duration = t.get("duration_ms", 0)
            per_tool.setdefault(name, []).append(duration)
            total_tools += 1
        total_thoughts += len(d.get("thoughts", []))

    out: dict = {
        "trace_count": len(docs),
        "total_tool_calls": total_tools,
        "total_thought_passages": total_thoughts,
        "per_tool": {},
    }
    for name, values in sorted(per_tool.items()):
        if not values:
            continue
        vs = sorted(values)
        n = len(vs)
        out["per_tool"][name] = {
            "count": n,
            "min_ms": round(min(vs), 1),
            "median_ms": round(statistics.median(vs), 1),
            "p95_ms": round(vs[int(0.95 * (n - 1))], 1),
            "max_ms": round(max(vs), 1),
            "mean_ms": round(statistics.mean(vs), 1),
            "samples": vs,
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
