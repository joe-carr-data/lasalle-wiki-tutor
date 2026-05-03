# 00 – Correction prompt for Claude Code

Last updated: 2026-05-03
Use this when an existing Claude Code session has already been told (or is
about to be told) about the project, and we need to redirect it to the
correct target site.

If you're starting a *fresh* session, prefer
[`00-kickoff-prompt.md`](./00-kickoff-prompt.md) — it's self-contained and
shorter.

---

## Step 1 — Sync the latest docs into the repo

Before pasting the prompt below, make sure the docs in
`~/projects/lasalle-catalog` reflect the current (corrected) plan. From a
terminal on your Mac:

```bash
# Copy the up-to-date docs over the old ones, preserving any code
# Claude Code may already have written under scripts/.
SRC="/Users/jcarr/Library/Application Support/Claude/local-agent-mode-sessions/59902d80-bd20-459c-ac9b-cbd9621f228c/11ef9a00-ec8c-448b-9978-f1f77f4ba283/local_9d666d7a-2e64-49d2-a7ee-9dd1930b15e8/outputs/lasalle-catalog"
DEST=~/projects/lasalle-catalog

mkdir -p "$DEST"
rsync -av --delete "$SRC/docs/" "$DEST/docs/"

cd "$DEST"
git add docs
git commit -m "Phase 1 correction: retarget from catalog.lasalle.edu to salleurl.edu

- Move wrong-university docs to docs/archive/2026-05-03-wrong-university/
- Rewrite 01-exploration-findings, 02-download-plan, 03-storage-layout, aha
- Update INDEX and kickoff prompt"
```

## Step 2 — Paste this into Claude Code

> Heads up — Phase 1 needs a course correction. The docs you have (or were
> about to read) originally targeted **La Salle University, Philadelphia
> (`catalog.lasalle.edu`)**. That was wrong. The actual target is **La
> Salle Campus Barcelona — Universitat Ramon Llull
> (`https://www.salleurl.edu/en`)** — a different institution with a
> different site (Drupal, not CourseLeaf), different URL conventions, no
> sitemap, and no per-program PDFs.
>
> I have just synced corrected docs into this repo. Before doing anything
> else:
>
> 1. Re-read these files in order — they have been rewritten:
>    - `docs/INDEX.md`
>    - `docs/aha.md`
>    - `docs/01-exploration-findings.md`
>    - `docs/02-download-plan.md`
>    - `docs/03-storage-layout.md`
> 2. The wrong-university Phase 1 docs are preserved at
>    `docs/archive/2026-05-03-wrong-university/`. **Do not** use them.
> 3. **If you have already written any code under `scripts/` or fetched
>    any data under `data/`** based on the old plan: stop, move the old
>    code to `scripts/archive/2026-05-03-wrong-university/` and any old
>    data to `data/archive/2026-05-03-wrong-university/`, then commit
>    that move with a clear message. Do not silently delete anything.
>    If `scripts/` and `data/` are still empty, skip this step.
> 4. The new plan has **five open questions** at the bottom of
>    `02-download-plan.md` (languages, program-type scope, crawl rate,
>    run mode, where the script runs). Resolve those with me before
>    writing or modifying any scraper code.
>
> Standing constraints (unchanged):
> - Plan mode before writing code; share the plan first.
> - Production-ready, documented Python; Typer + rich for the CLI.
> - Commit frequently with descriptive messages.
> - When you discover something non-obvious, append it to `docs/aha.md`.
> - Keep `docs/INDEX.md` in sync; never silently delete docs (archive
>   them).
> - Do not make scope-affecting decisions without asking me first.
>
> After you have re-read the docs and answered (or asked) the open
> questions, propose an implementation plan and wait for my sign-off
> before writing any scraper code.
