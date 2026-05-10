# `paper/` — Scientific writeup of the LaSalle Wiki Tutor

This directory contains the Typst source of the system paper, the figures it embeds, the evaluation scripts that produce its data, and the bibliography.

## Building the paper

Two builds are supported, driven from the same Typst source:

### Public build (committed `main.pdf`)

The reviewer-access box shows endpoint + repo URL, and the access-token row reads "distributed out of band on request to the corresponding author". This is the version that ships in the public GitHub repository.

```bash
typst compile main.typ main.pdf
```

### Reviewer build (gitignored `main-reviewer.pdf`)

The access-token row shows the literal current token. Distribute this PDF privately to evaluators; never commit it.

```bash
typst compile --input access-token=<CURRENT_TOKEN> main.typ main-reviewer.pdf
```

The token is in the project `.env` as `WIKI_TUTOR_ACCESS_TOKEN`. A one-liner that reads it and builds:

```bash
typst compile \
  --input access-token=$(grep -E '^WIKI_TUTOR_ACCESS_TOKEN=' ../.env | cut -d= -f2-) \
  main.typ main-reviewer.pdf
```

`paper/.gitignore` keeps `main-reviewer.pdf` (and `main-with-token.pdf`) out of git.

## Layout

```
paper/
├── main.typ                 # Document entry point — wires sections together
├── template.typ             # Title block, abstract, headings, figure styling
├── diagrams.typ             # Inline Typst architectural diagrams (Figs 1–8)
├── refs.bib                 # Bibliography (Hayagriva format)
├── sections/                # IMRAD-with-Deployment manuscript body
│   ├── 02-abstract.typ
│   ├── 03-introduction.typ
│   ├── 04-related-work.typ
│   ├── 05-system.typ
│   ├── 06-deployment.typ    # Reviewer-access box lives here (sys.inputs)
│   ├── 07-evaluation.typ
│   ├── 08-discussion.typ
│   ├── 09-conclusion.typ
│   └── 11-acknowledgements.typ
├── figures/                 # PDF outputs from make_figures.py + make_schematics.py
├── data/                    # JSON files consumed by the figures
│   ├── ablation_results.json
│   ├── corpus_coverage.json
│   ├── cost_raw.json
│   ├── latency_raw.json
│   └── refusal_results.json
└── scripts/                 # Evaluation drivers and figure generators
    ├── eval_corpus_coverage.py
    ├── eval_cost_per_conversation.py
    ├── eval_latency_from_traces.py
    ├── eval_ranker_ablation.py
    ├── eval_refusal_correctness.py
    ├── make_figures.py      # Matplotlib data plots (Figs 9–14)
    └── make_schematics.py   # Matplotlib schematics (alternative to diagrams.typ)
```

## Reproducing the data

Each JSON file under `data/` is produced by a corresponding script under `scripts/`. The data scripts depend on the live MongoDB trace store and on `wiki/meta/*.jsonl` from the parent repository.

```bash
# From the repo root, with .env populated:
uv run --group paper-figs python paper/scripts/eval_corpus_coverage.py
uv run --group paper-figs python paper/scripts/eval_ranker_ablation.py
uv run --group paper-figs python paper/scripts/eval_latency_from_traces.py
uv run --group paper-figs python paper/scripts/eval_cost_per_conversation.py
uv run --group paper-figs python paper/scripts/eval_refusal_correctness.py
uv run --group paper-figs python paper/scripts/make_figures.py
```

`make_schematics.py` is retained as an alternative to the inline Typst diagrams in `diagrams.typ`; the published figures use the Typst versions, which is why Figs 1–8 do not appear under `figures/`.
