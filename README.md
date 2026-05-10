# LaSalle Wiki Tutor

A deployed AI study advisor for the [La Salle Campus Barcelona](https://www.salleurl.edu) academic catalog (Universitat Ramon Llull). It takes a *tools-over-wiki* approach to retrieval-augmented question answering: the bilingual catalog (357 programs, 4,606 subjects) is compiled once into a structured Markdown wiki with strict YAML frontmatter, and a streaming Agno + OpenAI agent navigates it through ten deterministic, read-only tools. Vector retrieval is preserved as a primitive but confined to a single tool — `search_programs` — where a hybrid BM25-F + Model2Vec ranker handles colloquial and cross-lingual queries.

- **Live demo:** <https://lasalle.generateeve.com> (shared-token gate; see [access](#access))
- **Paper:** [`paper/main.pdf`](paper/main.pdf) — the full design and evaluation argument
- **License:** MIT

The whole stack runs on a single AWS `t3.micro` (~14 USD/month) behind Caddy + Let's Encrypt, with MongoDB in a Docker container for session state and a 50 MB sidecar `.npz` for the static embeddings. There is no managed vector database, no chunking pipeline, no index lifecycle to maintain.

---

## Table of contents

1. [Why this design](#why-this-design)
2. [Architecture at a glance](#architecture-at-a-glance)
3. [Repository layout](#repository-layout)
4. [Quickstart — local development](#quickstart--local-development)
5. [Running with Docker Compose](#running-with-docker-compose)
6. [Deploying to AWS](#deploying-to-aws)
7. [The agent and its ten tools](#the-agent-and-its-ten-tools)
8. [Hybrid retrieval inside `search_programs`](#hybrid-retrieval-inside-search_programs)
9. [Observability](#observability)
10. [HTTP API surface](#http-api-surface)
11. [Scripts and CLIs](#scripts-and-clis)
12. [Frontend](#frontend)
13. [Tests and evaluation](#tests-and-evaluation)
14. [The paper](#the-paper)
15. [Access](#access)
16. [Authorship](#authorship)
17. [License](#license)

---

## Why this design

University catalogs at one-institution scale sit in an awkward middle ground for large language model applications: too large to put into a prompt, too small to justify the operational machinery of a managed vector database. The reflexive answer — chunk the documents, embed them, retrieve them at query time — inherits the well-documented failure modes of canonical RAG (chunk boundaries, retrieval miss, generation drift) without providing a native answer to long-context degradation.

We take a different route. The catalog is crawled once into a structured Markdown wiki with strict YAML frontmatter (each program is a directory of Markdown files; each subject is one file). The agent is exposed to that wiki through ten deterministic Python tools — facet listings, structured browses, detail fetches, comparisons, and one hybrid free-text search. Vector retrieval lives inside `search_programs` as a 0.45-weight semantic input that is blended with BM25-F lexical scoring after pool-normalisation; everywhere else the agent navigates by id and by structured filter, never by chunk similarity.

The argument is empirical and narrow: for knowledge bases that are bounded, structured, slowly changing, and frontmatter-heavy, this is a more honest substrate than chunk-and-embed RAG. The [paper](paper/main.pdf) defends this in detail with a ranker ablation, per-tool latency from the live deploy, and a per-conversation cost rollup against the fixed monthly infrastructure spend.

---

## Architecture at a glance

```
┌──────────────┐  HTML  ┌──────────────┐  Markdown +  ┌──────────────────┐
│ salleurl.edu │ ─────► │  Crawler     │  frontmatter │  catalog_wiki_api │
│  (Drupal)    │        │  scripts/    │ ───────────► │  (read-only API) │
└──────────────┘        │  fetch_*.py  │              │  10 deterministic │
                        └──────────────┘              │  tools            │
                                                      └────────┬─────────┘
                                                               │
                                                               ▼
            ┌────────────────────────────────────────────────────────────────┐
            │  Streaming agent (Agno + OpenAI Responses gpt-5.4)             │
            │  - SSE event lifecycle (BaseSSEAdapter)                        │
            │  - Per-turn trace recorder (parallel listener, side-channel)   │
            └────────────────────────────────────────────────────────────────┘
                                                               │
                                       FastAPI / SSE  ────────►│◄──── MongoDB
                                                               │     (3 collections:
                                                               ▼      sessions, meta,
                                                       React 19 client          turn_traces)
                                                       (frontend/, Vite)
```

The five layers map cleanly onto top-level directories:

| Layer                            | Code                                  | Purpose |
|----------------------------------|---------------------------------------|---------|
| Crawl + extraction               | `scripts/fetch_catalog.py`, `scripts/build_wiki.py` | Polite resumable crawl of `salleurl.edu`; field-targeted extraction into structured Markdown |
| Wiki + read-only catalog API     | `wiki/`, `catalog_wiki_api/`          | The Markdown corpus and the Python module that exposes it as functions |
| Embeddings + hybrid search       | `scripts/build_embeddings.py`, `catalog_wiki_api/search.py` | Model2Vec static embeddings (256-d) + BM25-F lexical scoring |
| Streaming agent + SSE adapter    | `agent/`, `core/`, `events/`          | Agno wrapper, tool bindings, SSE event lifecycle, trace recorder |
| HTTP API + frontend              | `streaming*.py`, `frontend/`          | FastAPI server, auth gate, conversations REST, React client |

---

## Repository layout

```
.
├── agent/                       # Agno agent + the 10 tool bindings
│   ├── wiki_tutor_agent.py      # WikiTutorAgent (BaseStreamingAgent + gpt-5.4)
│   └── catalog_wiki_tools.py    # 10 tools wrapping catalog_wiki_api
├── catalog_wiki_api/            # Read-only API over wiki/
│   ├── store.py                 # Wiki loader: frontmatter, indices, facets
│   ├── search.py                # BM25-F + Model2Vec hybrid ranker
│   ├── synonyms.py              # EN+ES synonym-expansion table
│   ├── cli.py                   # Typer CLI for poking the API by hand
│   └── types.py                 # Pydantic-ish dataclasses for return shapes
├── core/                        # Streaming, sessions, auth, observability
│   ├── base_streaming_agent.py  # OpenAI event interception loop, tool tracking
│   ├── base_sse_adapter.py      # AgentEvent → SSE envelope
│   ├── turn_trace_recorder.py   # Side-channel listener → wiki_tutor_turn_traces
│   ├── conversations_store.py   # Title/lang/soft-delete with optimistic concurrency
│   ├── cancellation_registry.py # query_id → asyncio.Event for cooperative cancel
│   ├── title_polisher.py        # First-message title backfill (one-shot LLM call)
│   ├── openai_event_interceptor.py
│   └── auth.py                  # X-Access-Token dependency + constant-time compare
├── events/                      # AgentEvent vocabulary and replay infra
├── config/                      # Pydantic Settings (env-driven)
├── utils/                       # Mongo connection, loguru logger
├── scripts/                     # Build / fetch / publish entry points
│   ├── fetch_catalog.py         # Polite resumable crawler
│   ├── build_wiki.py            # Field-targeted extractor → wiki/
│   ├── build_embeddings.py      # Model2Vec embedding builder
│   ├── fetch_wiki.sh            # Idempotent wiki/ pull from GitHub Release
│   ├── publish_wiki.sh          # Push wiki-latest tarball to GitHub Release
│   └── ask_tutor.py             # CLI smoke test against a running agent
├── wiki/                        # The compiled bilingual catalog (gitignored)
│   ├── en/, es/                 # Per-language program + subject trees
│   ├── faq.md, glossary.md
│   └── meta/                    # catalog.jsonl, subjects.jsonl, pairings.jsonl,
│                                # embeddings_{en,es}.npz, stats.md, fallback_report.md
├── frontend/                    # React 19 + Vite + TypeScript SPA
├── infra/                       # Terraform: EC2 t3.micro + SSM + Caddy + DLM
├── tests/                       # pytest: API contract, persona walks, search benchmark
├── docs/                        # Phase-by-phase design history (00 to 07 + aha.md)
├── paper/                       # Typst manuscript + figures + eval scripts
├── streaming.py                 # FastAPI app entrypoint (uvicorn streaming:app)
├── streaming_auth.py            # /api/auth router (token validate, rate-limit)
├── streaming_conversations.py   # /api/wiki-tutor/v1/conversations REST router
├── fastapi_sse_contract.py      # Pydantic request/response models for the SSE API
├── docker-compose.yml           # mongo + app on one host
├── Dockerfile                   # 3-stage build (node, uv, slim runtime)
├── pyproject.toml               # uv-managed deps (Python 3.13)
└── .env.example                 # Copy to .env, fill in real values
```

---

## Quickstart — local development

Requirements:

- Python 3.13 with [`uv`](https://docs.astral.sh/uv/) installed (`brew install uv` on macOS)
- Node 22 + npm (for the frontend bundle)
- Docker + Docker Compose (only for the Mongo container; or run Mongo natively)
- An OpenAI API key with access to the Responses API and `gpt-5.4`

### 1. Clone and install Python deps

```bash
git clone https://github.com/joe-carr-data/lasalle-wiki-tutor.git
cd lasalle-wiki-tutor
uv sync                # creates .venv/, installs runtime + dev groups
```

### 2. Configure environment

```bash
cp .env.example .env
$EDITOR .env           # set OPENAI_API_KEY; leave WIKI_TUTOR_ACCESS_TOKEN empty
                       # for local dev (the gate falls open when unset)
```

For local dev you usually want:

```
ENVIRONMENT=local
OPENAI_API_KEY=sk-...
WIKI_TUTOR_ACCESS_TOKEN=
MONGO_URL=mongodb://localhost:27017
MONGO_DATABASE=lasalle_catalog_assistant
```

### 3. Fetch the wiki corpus

The Markdown wiki is large (~50 MB) and not committed. Pull the prebuilt corpus from the GitHub Release:

```bash
bash scripts/fetch_wiki.sh        # downloads wiki-latest asset → wiki/
```

Or rebuild it from source (takes 8–10 hours because of the 10-second crawl delay):

```bash
uv run python scripts/fetch_catalog.py   # crawls salleurl.edu → data/
uv run python scripts/build_wiki.py      # extracts → wiki/
uv run python scripts/build_embeddings.py # produces wiki/meta/embeddings_*.npz
```

### 4. Start MongoDB

Easiest path is the Compose service in isolation:

```bash
docker compose up -d mongo
```

Or any local Mongo 6.x install will do; the connection URL is configurable in `.env`.

### 5. Run the API

```bash
uv run uvicorn streaming:app --reload --host 127.0.0.1 --port 8000
```

Visit <http://127.0.0.1:8000/health> — should return `{"status":"ok",...}`.

### 6. Run the frontend dev server

In a second terminal:

```bash
cd frontend
npm install
npm run dev            # Vite serves on http://127.0.0.1:5173 with /api proxy
```

Open <http://127.0.0.1:5173>. Because `WIKI_TUTOR_ACCESS_TOKEN` is empty, the gate auto-passes and you land in the chat UI.

### 7. Smoke-test the agent from the CLI

```bash
uv run python scripts/ask_tutor.py "what bachelors do you offer in AI?"
```

This streams the agent's response token-by-token through the same SSE adapter the web client uses, useful for narrowing where regressions come from.

---

## Running with Docker Compose

A single-host stack — Mongo + the FastAPI app — that mirrors the production layout. The Dockerfile is a three-stage build: a Node 22 stage that produces the frontend bundle, a `uv`-managed Python stage that resolves dependencies, and a slim Python 3.13 runtime.

```bash
# Build the corpus locally first (NOT done inside the image)
uv run python scripts/build_wiki.py
uv run python scripts/build_embeddings.py

# Bring up Mongo + app
docker compose --env-file .env up -d --build

# Tail logs
docker compose logs -f app
```

The compose file binds both services to `127.0.0.1`. Production deployments terminate TLS one layer up (Caddy on the EC2 host, or an ALB in a multi-host topology) and forward to `127.0.0.1:8000`. CORS is `*` for the demo and should be tightened before exposing the app port directly to the public internet.

---

## Deploying to AWS

The `infra/` directory is a self-contained Terraform module that provisions a single `t3.micro` in `eu-west-1` with everything pre-wired: SSM Session Manager (no SSH), SSM Parameter Store for secrets, IMDSv2 required, encrypted root volume, daily EBS snapshots via DLM, Caddy + Let's Encrypt for TLS, MongoDB in `docker compose`, and the FastAPI app under `systemd`.

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars       # domain_name, letsencrypt_email,
                               # openai_api_key, wiki_tutor_access_token
terraform init
terraform apply
```

Full deploy / update / rotate / teardown walkthrough — including snapshot lifecycle, DNS A record at the registrar, and the SSM commands for in-place app updates — lives in [`infra/README.md`](infra/README.md).

Fixed monthly cost breakdown (post-free-tier on-demand, `eu-west-1`, May 2026 pricing):

| Item                                            | USD/month |
|-------------------------------------------------|-----------|
| `t3.micro` 24/7                                 | ~7.50     |
| 30 GB `gp3` root volume                         | ~2.40     |
| Public IPv4 address (charged since Feb 2024)    | ~3.60     |
| EBS daily snapshots (7-day retention)           | <0.50     |
| SSM Parameter Store, data egress < 100 GB       | 0         |
| **Total**                                       | **~14**   |

---

## The agent and its ten tools

The agent is a thin wrapper over [Agno](https://github.com/agno-agi/agno)'s `Agent` class, configured for `OpenAIResponses(model="gpt-5.4", reasoning={"effort":"medium","summary":"auto"})`, with `num_history_runs=8` and MongoDB session persistence. The agent's system prompt enforces a five-tool-call budget per response, the scope guardrails (decline politely on out-of-scope questions like other universities, coding help, visa advice), and the no-fabrication rule for fields the catalog does not publish (e.g. tuition routes to the admissions URL).

The ten tools are defined in [`agent/catalog_wiki_tools.py`](agent/catalog_wiki_tools.py) and bound to the agent in `agent/wiki_tutor_agent.py`. Each tool wraps a pure function in `catalog_wiki_api`, returns a JSON string with explicit `ok` / `error` fields, and emits a `tool.start` / `tool.end` SSE event pair.

| Family   | Tool                  | Purpose |
|----------|-----------------------|---------|
| Browse   | `search_programs`     | Free-text query → ranked programs via the hybrid BM25-F + Model2Vec ranker |
| Browse   | `list_programs`       | Structured filtered browse (by area, level, modality, language) |
| Browse   | `get_index_facets`    | Inventory of areas, levels, modalities — what filters are populated |
| Browse   | `compare_programs`    | Side-by-side comparison of 2–4 programs on key frontmatter fields |
| Detail   | `get_program`         | Full program record (overview + frontmatter) |
| Detail   | `get_program_section` | One named subsection (goals, careers, methodology, faculty, …) |
| Detail   | `get_curriculum`      | The year-by-year syllabus + subject list |
| Detail   | `get_subject`         | One subject record (description, ECTS, year, language) |
| Routing  | `get_faq`             | The bilingual FAQ pulled from `wiki/faq.md` |
| Routing  | `get_glossary_entry`  | A single glossary term from `wiki/glossary.md` (ECTS, modality, …) |

Each tool also normalises common LLM mistakes: an empty-string filter becomes a missing filter, a required argument that arrives empty returns a structured `missing_argument` error with a hint telling the model which sibling tool to call to obtain a usable value. This pattern keeps the API contract strict while keeping the surface forgiving in practice.

---

## Hybrid retrieval inside `search_programs`

`search_programs` is the only tool that involves vector retrieval. It takes a free-text query and returns a ranked list of programs from one language catalog. The pipeline computes two scoring branches that are then blended:

1. **Lexical branch — BM25-F.** Field-weighted over six fields: title 4.0, tags 3.0, area 2.0, level 1.5, body 1.0, slug 0.5. Robertson–Spärck-Jones IDF, standard hyperparameters `k1 = 1.5`, `b = 0.75`. The query passes through a bilingual synonym table first (`hacking` → `cybersecurity`; `aprendizaje automático` → `machine learning`).
2. **Semantic branch — Model2Vec.** [`minishlab/potion-base-8M`](https://github.com/MinishLab/model2vec), a static distilled embedding family that produces 256-d vectors per program at wiki-build time with no transformer encoder pass at query time. The embeddings are L2-normalised and stored in `wiki/meta/embeddings_{en,es}.npz`; query embedding takes a few milliseconds; cosine similarity is a single matrix-vector multiply.

Both signals are **pool-normalised** to `[0, 1]` over the candidate pool (not against absolute corpus statistics — the catalog is too small for global normalisation to behave well), then combined linearly: `0.55 · lex + 0.45 · sem`. An **intent prior** is multiplied in last: queries carrying `bachelor`, `master`, `doctorate` (and Spanish equivalents) nudge substantive degree-level programs up and short-format immersions down.

The `LASALLE_RANKER_MODE` environment variable selects among `hybrid` (default), `lexical` (BM25 only), `semantic` (cosine only), and `token_overlap` (the legacy baseline retained for regression comparison). The four-mode ablation reported in [`paper/data/ablation_results.json`](paper/data/ablation_results.json) and driven by [`paper/scripts/eval_ranker_ablation.py`](paper/scripts/eval_ranker_ablation.py) shows that `hybrid` is the only mode that reaches 100% top-5 coverage on the 20-query benchmark.

---

## Observability

Three MongoDB collections cooperate without coupling:

| Collection                       | Owner       | Purpose |
|----------------------------------|-------------|---------|
| `wiki_tutor_agent_sessions`      | Agno        | Per-session conversation memory; treated as read-only by the app and joined against on demand for cost rollups |
| `wiki_tutor_conversations_meta`  | Application | Title, language, soft-delete; carries an integer `version` field for optimistic-concurrency renames |
| `wiki_tutor_turn_traces`         | Application | One document per `run_id`: every reasoning passage with timestamps, every tool invocation with arguments preview and `duration_ms`, language, user id, turn start/end |

The trace collection is the empirical workhorse for the paper. The recorder ([`core/turn_trace_recorder.py`](core/turn_trace_recorder.py)) is a parallel listener on the same event manager that drives the SSE adapter, but it writes only on `final_response.end` so it never sits on the streaming hot path. Every measurement in `paper/data/*.json` is derived from this collection via `paper/scripts/eval_latency_from_traces.py` and `paper/scripts/eval_cost_from_sessions.py`.

---

## HTTP API surface

The FastAPI app is composed in [`streaming.py`](streaming.py); auxiliary routers live in [`streaming_auth.py`](streaming_auth.py) and [`streaming_conversations.py`](streaming_conversations.py). All `/api/wiki-tutor/*` endpoints are protected by the `require_access_token` dependency that does a constant-time comparison against `WIKI_TUTOR_ACCESS_TOKEN`.

| Method | Path                                              | Auth | Purpose |
|--------|---------------------------------------------------|------|---------|
| GET    | `/health`                                         | no   | Liveness check |
| POST   | `/api/auth/validate`                              | no   | Test a token before storing it in the browser; per-IP rate-limited |
| POST   | `/api/wiki-tutor/v1/query/stream`                 | yes  | Stream an agent response over SSE |
| POST   | `/api/wiki-tutor/v1/query/cancel`                 | yes  | Cooperatively cancel an in-flight `query_id` |
| GET    | `/api/wiki-tutor/v1/conversations`                | yes  | List conversations (paginated, soft-delete-aware) |
| GET    | `/api/wiki-tutor/v1/conversations/{session_id}`   | yes  | Hydrate the messages for one conversation |
| PATCH  | `/api/wiki-tutor/v1/conversations/{session_id}`   | yes  | Rename / change language (uses `If-Match`-style `version` for OCC) |
| DELETE | `/api/wiki-tutor/v1/conversations/{session_id}`   | yes  | Soft-delete a conversation |
| GET    | `/`, `/assets/*`                                  | no   | The bundled React SPA (gate UI + chat) |

The SSE event vocabulary covers session lifecycle (`session.started`, `session.ended`), reasoning (`agent.thinking.start`, `agent.thinking.delta`, `agent.thinking.end`), tool execution (`tool.start`, `tool.end`), and the final response (`final_response.delta`, `final_response.end`, `response.final`). Each event carries an envelope with event name, timestamp, elapsed milliseconds, correlation id, and agent metadata; the payload sits under `data`.

A more formal contract reference lives in [`fastapi_sse_contract.py`](fastapi_sse_contract.py).

---

## Scripts and CLIs

```
scripts/fetch_catalog.py            # Polite resumable crawler against salleurl.edu
scripts/build_wiki.py               # Field-targeted HTML → Markdown wiki/
scripts/build_embeddings.py         # Model2Vec embeddings + identity-signature check
scripts/fetch_wiki.sh               # Idempotent pull of wiki/ from GitHub Release
scripts/publish_wiki.sh             # Push wiki-latest tarball to GitHub Release
scripts/ask_tutor.py                # CLI smoke test against a running agent

python -m catalog_wiki_api          # Typer CLI for the read-only catalog API
                                    # subcommands: list, search, facets, languages,
                                    # get-program, section, curriculum, subject,
                                    # subjects, by-slug, equivalent, related,
                                    # compare, faq, glossary
```

The `catalog_wiki_api` CLI is the fastest way to inspect the corpus without spinning up the agent:

```bash
uv run python -m catalog_wiki_api search "machine learning" --lang en --top 5
uv run python -m catalog_wiki_api get-program en/bachelor-artificial-intelligence-and-data-science
uv run python -m catalog_wiki_api facets --lang en
```

---

## Frontend

Vite + React 19 + TypeScript SPA in [`frontend/`](frontend). State lives in a thin reducer; the SSE client consumes the event vocabulary above and updates the rendered text only on delta events. The gate UI (`AppGated.tsx`) validates the token against `/api/auth/validate` and stores it in `localStorage`; the chat UI (`App.tsx`) is mounted after a successful validation.

```bash
cd frontend
npm install
npm run dev      # http://127.0.0.1:5173 with a /api proxy to localhost:8000
npm run build    # type-check + bundle to dist/
```

The bundle is copied into the Docker image at build time (stage 1 of the Dockerfile) and mounted at `/` and `/assets/*` by the FastAPI app in production.

---

## Tests and evaluation

```bash
uv run pytest tests/                            # API contract + persona walks + search regressions
uv run pytest tests/test_search_failure_benchmark.py  # the 20-query retrieval benchmark
```

`tests/test_search_failure_benchmark.py` is the source of truth for the ranker ablation reported in the paper. To run the full four-mode sweep:

```bash
LASALLE_RANKER_MODE=hybrid    uv run pytest tests/test_search_failure_benchmark.py
LASALLE_RANKER_MODE=lexical   uv run pytest tests/test_search_failure_benchmark.py
LASALLE_RANKER_MODE=semantic  uv run pytest tests/test_search_failure_benchmark.py
LASALLE_RANKER_MODE=token_overlap uv run pytest tests/test_search_failure_benchmark.py
```

Or use the wrapper script in `paper/scripts/eval_ranker_ablation.py` which runs all four modes and emits a JSON summary into `paper/data/ablation_results.json`.

---

## The paper

A full scientific writeup of the system and its design argument lives in [`paper/`](paper). It is a Typst manuscript that defends the tools-over-wiki design against the chunk-and-embed RAG default with measured evidence from the live deployment: corpus coverage, the four-mode ranker ablation, per-tool latency, per-conversation cost, and a refusal-correctness spot-check.

```bash
cd paper
typst compile main.typ          # produces main.pdf
```

The `paper/data/` directory contains every JSON file consumed by the figures; `paper/scripts/` contains the evaluation drivers that produce them; `paper/diagrams.typ` contains the inline Typst schematics for the eight architectural figures.

---

## Access

The live deployment at <https://lasalle.generateeve.com> is gated by a shared-secret token sent as the `X-Access-Token` header. The gate UI accepts the token on first load and stores it in `localStorage`.

The current token value is **not committed to this public repository.** The public build of the paper (`paper/main.pdf`) shows "distributed out of band on request to the corresponding author" in the reviewer-access box. A second build of the same Typst source — `paper/main-reviewer.pdf`, gitignored — has the literal token slotted in via `--input access-token=...` and is distributed privately to evaluators. Build instructions are in [`paper/README.md`](paper/README.md). To obtain the current token, contact the corresponding author (Alex Carreras Forns, <alexcarrerasforns@gmail.com>).

Token validation runs constant-time string comparison against the `WIKI_TUTOR_ACCESS_TOKEN` environment variable, and the `/api/auth/validate` endpoint is per-IP rate-limited (ten attempts per minute with a `Retry-After` header) so brute-force attempts are bounded.

---

## Authorship

This system is a joint effort by:

1. **Alex Carreras Forns** — design and implementation lead (crawler, wiki builder, catalog API, agent tool surface). Corresponding author: <alexcarrerasforns@gmail.com>.
2. **Josep Carreras Molins** — mentorship, code review across all phases, deployment and infrastructure: <joe.carr.data@gmail.com>.
3. **Claude Code** — pair-programming support across every phase, from initial site exploration through the Terraform module and the scope guardrails to the manuscript typesetting.

The work is submitted in support of the first author's application to La Salle Campus Barcelona's Bachelor in Artificial Intelligence and Data Science. The choice of corpus is therefore not accidental: the system retrieves and answers questions about the very programme its first author is applying to.

---

## License

MIT — see [`LICENSE`](LICENSE).

The rendered Markdown wiki corpus distributed via the GitHub Release `wiki-latest` asset is a derivative work of content published at `salleurl.edu` and is redistributed for academic and evaluation purposes only. The raw HTML scrape inputs are not redistributed; reproducing them from scratch requires re-running the polite crawl over approximately eight to ten hours.

---

## Acknowledgements

We thank the maintainers of the open-source dependencies the work rests on: [Agno](https://github.com/agno-agi/agno) for the streaming agent framework that made the SSE adapter tractable, [FastAPI](https://fastapi.tiangolo.com/) and [Starlette](https://www.starlette.io/) for the server, [Model2Vec](https://github.com/MinishLab/model2vec) for the static-embedding implementation that keeps the semantic pole lightweight, [Typst](https://typst.app/) and [Fletcher](https://typst.app/universe/package/fletcher) for the typesetting and diagram libraries used to produce the manuscript, [Caddy](https://caddyserver.com/) for the TLS edge, and [Terraform](https://www.terraform.io/) for reproducible infrastructure. We also acknowledge the OpenAI Responses API for the `gpt-5.4` model that drives the streaming agent.
