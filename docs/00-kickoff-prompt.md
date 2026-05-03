# 00 – Kickoff prompt for a fresh Claude Code session

Last updated: 2026-05-03
Use this when starting Phase 2 in a new chat. Either point Claude at this
file, or copy the block below verbatim.

---

## Copy-paste this into Claude Code

> I'm building an AI assistant that answers questions about the academic
> offering of **La Salle Campus Barcelona — Universitat Ramon Llull**
> (`https://www.salleurl.edu/en`). Phase 1 (exploration + plan) is
> already done; the docs in this repo were initially written for the
> wrong institution and have since been corrected. The historical record
> lives under `docs/archive/`.
>
> Read these files in order before doing anything else:
>
> 1. `docs/INDEX.md` – entry point
> 2. `docs/aha.md` – short lessons learned, read this early
> 3. `docs/01-exploration-findings.md` – what the site looks like
> 4. `docs/02-download-plan.md` – the phased plan
> 5. `docs/03-storage-layout.md` – on-disk layout and manifest schema
>
> Your task is **Phase 2 only**: implement
> `scripts/fetch_catalog.py` per the plan in `docs/02-download-plan.md`.
> Do not start phase 3 (markdown conversion) or phase 4 (wiki) yet.
>
> Constraints from my standing preferences:
> - Use plan mode before writing code; share the plan with me first.
> - Production-ready, documented Python (type hints, docstrings,
>   Typer + rich for the CLI).
> - Commit frequently with descriptive messages.
> - When you discover something non-obvious, append it to `docs/aha.md`.
> - Keep `docs/INDEX.md` in sync; archive any superseded docs into
>   `docs/archive/`.
> - Do not make scope-affecting decisions without asking me first.
>
> The plan has **five open questions** at the bottom of
> `02-download-plan.md` that must be resolved before the scraper runs:
> language scope, program-type scope, crawl rate, run mode, and where
> the script will run. Ask me those before doing anything else.
>
> Once you have the answers, propose an implementation plan, get my
> sign-off, and implement it. Verify with the checks listed in the
> "Verification" section of `02-download-plan.md` before declaring
> success.

---

## Even shorter version (if you just want one line)

> Read `docs/INDEX.md`, then `docs/aha.md`, then
> `docs/02-download-plan.md`, and execute Phase 2 only. Resolve the
> five open questions at the bottom of the plan with me first. Use plan
> mode, ask before scope-affecting decisions, and update
> `docs/INDEX.md` and `docs/aha.md` as you go.
