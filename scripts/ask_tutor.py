#!/usr/bin/env python3
"""LaSalle Wiki Tutor debug console — structured output with full reasoning trace.

Mirrors `ask_underwriting.py` from lqc-ai-assistant-lib but adapted for the
single-agent tutor's SSE contract (no citations / no graph events).

Usage:
    # Single question
    uv run python scripts/ask_tutor.py "What bachelor programs are in AI?"

    # Multiple concurrent questions (each gets its own session)
    uv run python scripts/ask_tutor.py \
        "Compare CS and AI bachelors" \
        "What's the difference between MBA full-time and part-time?"

    # Shared session (multi-turn)
    uv run python scripts/ask_tutor.py --session demo_001 \
        "I'm into AI" \
        "What about the master programs?"

    # Reasoning effort override (none|low|medium|high)
    uv run python scripts/ask_tutor.py --reasoning-effort high \
        "What courses will I take in year 2 of CS?"

    # Other modes
    uv run python scripts/ask_tutor.py --raw "How many ECTS is the AI bachelor?"
    uv run python scripts/ask_tutor.py --json "What's the modality of the BIM master?"

    # Cancel an in-flight query (rare; from another shell)
    uv run python scripts/ask_tutor.py --cancel <query_id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import uuid

import httpx


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint
# ─────────────────────────────────────────────────────────────────────────────

QUERY_ROUTE = "/api/wiki-tutor/v1/query/stream"
CANCEL_ROUTE = "/api/wiki-tutor/v1/query/cancel"


# ─────────────────────────────────────────────────────────────────────────────
# SSE event collector
# ─────────────────────────────────────────────────────────────────────────────


async def run_query(
    question: str,
    endpoint: str,
    session_id: str,
    *,
    raw: bool = False,
    verbosity: int = 3,
    reasoning_effort: str | None = None,
) -> dict:
    """Run a single query and collect all SSE events into a structured result."""
    url = f"{endpoint}{QUERY_ROUTE}"
    query_id = f"qry_{uuid.uuid4().hex[:8]}"
    payload: dict = {
        "query": question,
        "session_id": session_id,
        "query_id": query_id,
        "user_id": "cli_test",
        "verbosity": verbosity,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    state = {
        "tools": [],
        "tool_by_corr": {},
        "thinking_deltas": [],
        "events_log": [],
        "events_count": {},
        "errors": [],
        "total_duration": "",
    }
    t0 = time.time()
    t_first_event: float | None = None

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST", url, json=payload, headers={"Accept": "text/event-stream"},
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                return {
                    "error": f"HTTP {response.status_code}: {body.decode()[:200]}",
                    "question": question,
                    "session_id": session_id,
                    "query_id": query_id,
                }

            buffer = ""
            current_event: dict[str, str] = {}

            async for chunk in response.aiter_text():
                if t_first_event is None:
                    t_first_event = time.time()
                buffer += chunk
                lines = buffer.split("\n")
                buffer = lines.pop()

                for line in lines:
                    if line.startswith("event:"):
                        current_event["event"] = line[6:].strip()
                    elif line.startswith("data:"):
                        current_event["data"] = line[5:].strip()
                    elif line == "" and current_event.get("event") and current_event.get("data"):
                        _process_event(current_event, state)
                        current_event = {}

    wall_time = f"{time.time() - t0:.1f}s"
    ttfe = f"{t_first_event - t0:.2f}s" if t_first_event else "n/a"
    events_log = state["events_log"]

    # Final response text from last delta/end event
    final_response = ""
    for entry in reversed(events_log):
        if entry["type"] == "final_response.end":
            final_response = entry.get("full_text", "")
            break
        if entry["type"] == "final_response.delta":
            final_response = entry.get("accumulated", "")
            break

    # response.final payload
    final_obj: dict = {}
    for entry in reversed(events_log):
        if entry["type"] == "response.final":
            final_obj = entry.get("data", {})
            break

    return {
        "question": question,
        "session_id": session_id,
        "query_id": query_id,
        "wall_time": wall_time,
        "wall_time_s": time.time() - t0,
        "ttfe": ttfe,
        "t0": t0,
        "total_duration": state["total_duration"],
        "tools": state["tools"],
        "thinking_deltas": state["thinking_deltas"],
        "response": final_response,
        "response_final": final_obj,
        "events_count": state["events_count"],
        "events_log": events_log,
        "errors": state["errors"],
    }


def _process_event(current_event: dict, state: dict) -> None:
    """Process one SSE event and update the state collectors."""
    event_type = current_event["event"]
    try:
        data = json.loads(current_event["data"])
    except json.JSONDecodeError:
        data = {"raw": current_event["data"]}

    event_data = data.get("data", {})
    correlation_id = data.get("correlation_id")
    elapsed = data.get("elapsed_ms", 0)
    ts = time.time()

    tools = state["tools"]
    tool_by_corr = state["tool_by_corr"]
    state["events_count"][event_type] = state["events_count"].get(event_type, 0) + 1

    log_entry: dict = {
        "type": event_type,
        "correlation_id": correlation_id,
        "elapsed_ms": elapsed,
        "ts": ts,
    }

    if event_type == "agent.thinking.delta":
        accumulated = event_data.get("accumulated", "")
        log_entry["accumulated"] = accumulated
        log_entry["delta"] = event_data.get("delta", "")
        if accumulated:
            state["thinking_deltas"].append(accumulated)

    elif event_type == "tool.start":
        tool = event_data.get("tool", {})
        entry = {
            "name": tool.get("name", "?"),
            "icon": tool.get("icon", ""),
            "call_id": tool.get("call_id", ""),
            "corr_start": correlation_id,
            "args_display": tool.get("arguments_display", ""),
            "args": tool.get("arguments", {}),
            "elapsed_start": elapsed,
            "ts_start": ts,
        }
        tools.append(entry)
        if correlation_id:
            tool_by_corr[correlation_id] = entry
        log_entry["tool_name"] = entry["name"]
        log_entry["args_display"] = entry["args_display"][:120]

    elif event_type == "tool.end":
        tool = event_data.get("tool", {})
        name = tool.get("name", "?")
        matched = tool_by_corr.pop(correlation_id, None) if correlation_id else None
        if not matched:
            for t in reversed(tools):
                if t["name"] == name and not t.get("dur"):
                    matched = t
                    break
        if matched:
            matched["dur"] = event_data.get("duration_display", "?")
            matched["preview"] = event_data.get("result_preview", "")
            matched["success"] = event_data.get("success", True)
            matched["orphaned"] = event_data.get("orphaned")
            matched["corr_end"] = correlation_id
            matched["end_args"] = tool.get("arguments_display", "")
            matched["ts_end"] = ts
        log_entry["tool_name"] = name
        log_entry["duration"] = event_data.get("duration_display", "?")
        log_entry["matched"] = matched is not None

    elif event_type == "final_response.delta":
        log_entry["accumulated"] = event_data.get("accumulated", "")

    elif event_type == "final_response.end":
        log_entry["full_text"] = event_data.get("full_text", "")

    elif event_type == "response.final":
        log_entry["data"] = event_data

    elif event_type == "session.ended":
        state["total_duration"] = event_data.get("total_duration_display", "")

    elif event_type == "error":
        msg = event_data.get("message", "Unknown error")
        state["errors"].append(msg)
        log_entry["error"] = msg

    state["events_log"].append(log_entry)


# ─────────────────────────────────────────────────────────────────────────────
# Structured printer
# ─────────────────────────────────────────────────────────────────────────────


def print_result(result: dict, index: int = 0, raw: bool = False, json_mode: bool = False):
    """Print a single result in structured debug format."""
    if json_mode:
        print(json.dumps(result, indent=2, default=str))
        return

    q = result["question"]
    sid = result["session_id"]

    print(f"\n{'=' * 90}")
    print(f" Q{index}: {q}")
    print(f" Session: {sid} | Query: {result.get('query_id', '?')}")
    print(f" Wall: {result['wall_time']} | TTFE: {result.get('ttfe', '?')} | Server: {result.get('total_duration', '?')}")
    print(f"{'=' * 90}")

    if result.get("error"):
        print(f"\n  ERROR: {result['error']}")
        return

    _print_reasoning(result)
    _print_tools(result)
    _print_correlation_audit(result)

    if result.get("errors"):
        print(f"\n{'─' * 90}")
        print(" ERRORS")
        print(f"{'─' * 90}")
        for e in result["errors"]:
            print(f"  !! {e}")

    _print_time_profile(result)
    _print_event_counts(result)

    if raw:
        _print_raw_events(result)

    _print_response(result)


def _print_reasoning(result: dict):
    """Print agent reasoning/thinking, split by natural step boundaries."""
    thinking = result.get("thinking_deltas", [])
    if not thinking:
        print(f"\n{'─' * 90}")
        print(" REASONING: (none)")
        return

    print(f"\n{'─' * 90}")
    print(" REASONING")
    print(f"{'─' * 90}")

    final_thinking = thinking[-1] if thinking else ""
    if not final_thinking:
        print("  (empty)")
        return

    steps = re.split(r"\n\n+", final_thinking.strip())
    for i, step in enumerate(steps):
        clean = step.strip()
        if not clean:
            continue
        lines = clean.split("\n")
        prefix = f"  [{i+1}] " if len(steps) > 1 else "  "
        for j, line in enumerate(lines):
            if j == 0:
                print(f"{prefix}{line}")
            else:
                print(f"  {'    ' if len(steps) > 1 else ''}{line}")
        print()  # blank line between steps


def _print_tools(result: dict):
    """Print tool invocations with args and results."""
    tools = result.get("tools", [])
    print(f"{'─' * 90}")
    print(f" TOOLS ({len(tools)})")
    print(f"{'─' * 90}")

    if not tools:
        print("  (none)")
        return

    for i, t in enumerate(tools):
        dur = t.get("dur", "pending...")
        name = t["name"]
        icon = t.get("icon", "")
        corr_start = t.get("corr_start", "")
        corr_end = t.get("corr_end", "")

        if corr_start and corr_start == corr_end:
            corr_status = "OK"
        elif corr_start and not corr_end:
            corr_status = "NO_END"
        elif corr_start and corr_end and corr_start != corr_end:
            corr_status = f"MISMATCH({corr_start[:12]}!={corr_end[:12]})"
        else:
            corr_status = "NO_CORR"

        ts_start = t.get("ts_start")
        ts_end = t.get("ts_end")
        wall = f"{ts_end - ts_start:.2f}s" if ts_start and ts_end else ""
        dur_str = dur
        if wall and dur != "pending...":
            dur_str = f"{dur} (wall: {wall})"
        elif wall:
            dur_str = f"wall: {wall}"

        print(f"\n  {i+1}. {icon} {name}")
        print(f"     Duration: {dur_str} | Correlation: {corr_status}")

        args_display = t.get("args_display", "")
        if args_display:
            try:
                args_parsed = json.loads(args_display) if args_display.startswith("{") else None
            except (json.JSONDecodeError, TypeError):
                args_parsed = None
            if args_parsed:
                for k, v in args_parsed.items():
                    val_str = str(v)
                    if len(val_str) > 120:
                        val_str = val_str[:120] + "..."
                    print(f"     > {k}: {val_str}")
            else:
                print(f"     > {args_display[:200]}")

        preview = t.get("preview", "")
        if preview:
            preview_lines = preview.strip().split("\n")
            for j, pl in enumerate(preview_lines[:4]):
                print(f"     < {pl[:150]}")
            if len(preview_lines) > 4:
                print(f"     < ... ({len(preview_lines)} lines total)")

        if t.get("orphaned") is not None:
            print(f"     Orphaned: {t['orphaned']}")


def _print_correlation_audit(result: dict):
    """Audit correlation_id matching between tool.start and tool.end events."""
    tools = result.get("tools", [])
    if not tools:
        return

    ok = 0
    issues = []
    for i, t in enumerate(tools):
        corr_start = t.get("corr_start", "")
        corr_end = t.get("corr_end", "")
        if corr_start and corr_start == corr_end:
            ok += 1
        elif not corr_start:
            issues.append(f"  Tool {i+1} ({t['name']}): no correlation_id on start")
        elif not corr_end:
            issues.append(f"  Tool {i+1} ({t['name']}): no tool.end received (corr={corr_start[:16]})")
        else:
            issues.append(f"  Tool {i+1} ({t['name']}): start={corr_start[:16]} != end={corr_end[:16]}")

    print(f"\n{'─' * 90}")
    print(f" CORRELATION AUDIT: {ok}/{len(tools)} matched", end="")
    if not issues:
        print(" -- ALL OK")
    else:
        print(f" -- {len(issues)} ISSUE(S)")
        for issue in issues:
            print(issue)


def _print_time_profile(result: dict):
    """Build a time profile from event timestamps and print as a table."""
    events_log = result.get("events_log", [])
    t0 = result.get("t0")
    wall_s = result.get("wall_time_s", 0)
    if not events_log or not t0 or wall_s <= 0:
        return

    segments: list[tuple[str, float, float]] = []
    thinking_start: float | None = None
    thinking_idx = 0
    response_start: float | None = None
    tool_starts: dict[str, float] = {}

    for entry in events_log:
        ts = entry.get("ts", 0)
        etype = entry["type"]

        if etype == "agent.thinking.start":
            thinking_start = ts
        elif etype == "agent.thinking.end":
            if thinking_start:
                thinking_idx += 1
                segments.append((f"thinking #{thinking_idx}", thinking_start, ts))
                thinking_start = None
        elif etype == "tool.start":
            corr = entry.get("correlation_id", "")
            name = entry.get("tool_name", "?")
            tool_starts[corr or name] = ts
        elif etype == "tool.end":
            corr = entry.get("correlation_id", "")
            name = entry.get("tool_name", "?")
            key = corr or name
            start = tool_starts.pop(key, None)
            if not start:
                for k, v in list(tool_starts.items()):
                    if name in k or k in name:
                        start = v
                        del tool_starts[k]
                        break
            if start:
                segments.append((f"tool: {name}", start, ts))
        elif etype == "final_response.start":
            response_start = ts
        elif etype == "final_response.end":
            if response_start:
                segments.append(("response streaming", response_start, ts))
                response_start = None

    if events_log:
        first_ts = events_log[0].get("ts", t0)
        if first_ts - t0 > 0.001:
            segments.insert(0, ("setup (TTFE)", t0, first_ts))

    segments.sort(key=lambda s: s[1])

    timeline: list[tuple[str, float, float]] = []
    prev_end = t0

    for label, start, end in segments:
        gap_dur = start - prev_end
        if gap_dur > 0.05:
            if not any(l for l, _, _ in timeline if not l.startswith("  >>") and l != "setup (TTFE)"):
                gap_label = "agent setup + OpenAI first call"
            elif "tool:" in label:
                gap_label = "OpenAI → tool call decision"
            elif "thinking" in label and any("tool:" in l for l, _, _ in timeline):
                gap_label = "OpenAI processing tool result"
            elif "response" in label:
                gap_label = "OpenAI → response start"
            elif "thinking" in label:
                gap_label = "OpenAI API round-trip"
            else:
                gap_label = "gap (unknown)"
            timeline.append((f"  >> {gap_label}", prev_end, start))
        timeline.append((label, start, end))
        prev_end = end

    trailing = (t0 + wall_s) - prev_end
    if trailing > 0.05:
        timeline.append(("  >> finalize + SSE flush", prev_end, t0 + wall_s))

    print(f"\n{'─' * 90}")
    print(f" TIME PROFILE")
    print(f"{'─' * 90}")
    print(f"  {'Phase':<40} {'Duration':>10} {'Start':>8} {'End':>8} {'%':>6}")
    print(f"  {'─'*40} {'─'*10} {'─'*8} {'─'*8} {'─'*6}")

    for label, start, end in timeline:
        dur = end - start
        offset_start = start - t0
        offset_end = end - t0
        pct = (dur / wall_s * 100) if wall_s > 0 else 0
        is_gap = label.startswith("  >>")
        marker = "·" if is_gap else " "
        print(f" {marker}{label:<40} {dur:>9.2f}s {offset_start:>7.1f}s {offset_end:>7.1f}s {pct:>5.1f}%")

    print(f"  {'─'*40} {'─'*10} {'─'*8} {'─'*8} {'─'*6}")
    print(f"  {'TOTAL':<40} {wall_s:>9.2f}s {'':>8} {'':>8} {'100.0':>6}%")

    cat_tools = sum(e - s for l, s, e in timeline if l.startswith("tool:"))
    cat_thinking = sum(e - s for l, s, e in timeline if l.startswith("thinking"))
    cat_response = sum(e - s for l, s, e in timeline if l.startswith("response"))
    cat_openai = sum(e - s for l, s, e in timeline if l.startswith("  >> OpenAI"))
    cat_setup = sum(e - s for l, s, e in timeline if "setup" in l or "TTFE" in l)
    cat_flush = sum(e - s for l, s, e in timeline if "finalize" in l)

    print(f"\n  Summary: tools={cat_tools:.1f}s thinking={cat_thinking:.1f}s "
          f"response={cat_response:.1f}s OpenAI_wait={cat_openai:.1f}s "
          f"setup={cat_setup:.1f}s flush={cat_flush:.1f}s")


def _print_event_counts(result: dict):
    """Print event type counts as a compact summary."""
    counts = result.get("events_count", {})
    if not counts:
        return
    print(f"\n{'─' * 90}")
    print(f" EVENT COUNTS")
    print(f"{'─' * 90}")
    for etype, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {etype:40s} {count:>4d}")


def _print_raw_events(result: dict):
    """Print all events in chronological order."""
    print(f"\n{'─' * 90}")
    print(f" RAW EVENT LOG ({len(result.get('events_log', []))} events)")
    print(f"{'─' * 90}")
    for entry in result.get("events_log", []):
        etype = entry["type"]
        corr = entry.get("correlation_id", "")
        corr_str = f" corr={corr[:16]}" if corr else ""

        if etype == "tool.start":
            print(f"  >> {etype}{corr_str} {entry.get('tool_name', '?')} args={entry.get('args_display', '')[:100]}")
        elif etype == "tool.end":
            matched = "matched" if entry.get("matched") else "UNMATCHED"
            print(f"  << {etype}{corr_str} {entry.get('tool_name', '?')} dur={entry.get('duration', '?')} [{matched}]")
        elif etype == "agent.thinking.delta":
            acc = entry.get("accumulated", "")
            print(f"  .. {etype} (+{len(entry.get('delta', ''))} chars, total={len(acc)})")
        elif etype == "final_response.delta":
            acc = entry.get("accumulated", "")
            print(f"  .. {etype} (total={len(acc)} chars)")
        elif etype == "error":
            print(f"  !! {etype}: {entry.get('error', '?')}")
        elif etype == "response.final":
            rf = entry.get("data", {})
            print(f"  ** {etype} origin={rf.get('response_origin', '?')}")
        else:
            print(f"  -- {etype}{corr_str}")


def _print_response(result: dict):
    """Print the final response text."""
    rf = result.get("response_final", {})

    print(f"\n{'─' * 90}")
    meta_parts = []
    if rf.get("conversation_id"):
        meta_parts.append(f"conversation={rf['conversation_id']}")
    origin = rf.get("response_origin")
    if origin:
        meta_parts.append(f"origin={origin}")
    if meta_parts:
        print(f" META: {' | '.join(meta_parts)}")
        print(f"{'─' * 90}")

    print(f"\n RESPONSE:")
    print(f"{'─' * 90}")
    resp = result.get("response", "(empty)")
    if resp:
        print(resp)
    else:
        print("  (empty)")


def print_summary(results: list, total_time: float):
    """Print a compact summary table for multiple questions."""
    n = len(results)
    print(f"\n{'=' * 90}")
    print(f" SUMMARY: {n} questions | Total wall time: {total_time:.1f}s")
    print(f"{'=' * 90}")

    print(f"  {'#':<4} {'Question':<55} {'Wall':>6} {'TTFE':>6} {'Tools':>6} {'Corr':>6}")
    print(f"  {'─'*4} {'─'*55} {'─'*6} {'─'*6} {'─'*6} {'─'*6}")

    for i, r in enumerate(results):
        q = r["question"][:54]
        if r.get("error"):
            print(f"  Q{i+1:<3} {q:<55} {'ERR':>6} {'':>6} {'':>6} {'':>6}")
            continue
        tools_n = len(r.get("tools", []))
        tools = r.get("tools", [])
        corr_ok = sum(1 for t in tools if t.get("corr_start") and t.get("corr_start") == t.get("corr_end"))
        corr_str = f"{corr_ok}/{len(tools)}" if tools else "n/a"
        print(f"  Q{i+1:<3} {q:<55} {r['wall_time']:>6} {r.get('ttfe', '?'):>6} {tools_n:>6} {corr_str:>6}")


# ─────────────────────────────────────────────────────────────────────────────
# Cancel
# ─────────────────────────────────────────────────────────────────────────────


async def cancel(query_id: str, endpoint: str) -> None:
    url = f"{endpoint}{CANCEL_ROUTE}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json={"query_id": query_id})
        if resp.status_code == 200:
            print(json.dumps(resp.json(), indent=2))
        else:
            print(f"HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
            sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


async def main():
    parser = argparse.ArgumentParser(
        description="LaSalle Wiki Tutor debug console",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("questions", nargs="*", help="One or more questions (run concurrently)")
    parser.add_argument("--endpoint", default="http://localhost:8000", help="Backend URL")
    parser.add_argument("--session", default=None,
                        help="Session ID (shared if set; new per-question otherwise)")
    parser.add_argument("--verbosity", type=int, default=3, help="Verbosity (1-3)")
    parser.add_argument("--reasoning-effort",
                        choices=["none", "low", "medium", "high"], default=None,
                        help="Override reasoning_effort on the agent")
    parser.add_argument("--raw", action="store_true", help="Show raw event log")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON (machine-readable)")
    parser.add_argument("--cancel", metavar="QUERY_ID", default=None,
                        help="Cancel an in-flight query and exit")
    args = parser.parse_args()

    if args.cancel:
        await cancel(args.cancel, args.endpoint)
        return

    if not args.questions:
        parser.error("at least one question is required (or use --cancel)")

    questions = args.questions
    n = len(questions)

    if not args.json:
        print(f"Agent: wiki-tutor")
        print(f"Endpoint: {args.endpoint}")
        if args.reasoning_effort:
            print(f"Reasoning effort: {args.reasoning_effort}")
        print(f"Running {n} question(s) {'concurrently' if n > 1 else ''}...")

    tasks = []
    for q in questions:
        sid = args.session or f"ask_{uuid.uuid4().hex[:8]}"
        tasks.append(run_query(
            q, args.endpoint, sid,
            raw=args.raw,
            verbosity=args.verbosity,
            reasoning_effort=args.reasoning_effort,
        ))

    t0 = time.time()
    results = await asyncio.gather(*tasks)
    total = time.time() - t0

    if args.json:
        print(json.dumps({"results": results, "total_wall_time": f"{total:.1f}s"},
                         indent=2, default=str))
        return

    for i, result in enumerate(results):
        print_result(result, i + 1, args.raw, args.json)

    if n > 1:
        print_summary(results, total)


if __name__ == "__main__":
    asyncio.run(main())
