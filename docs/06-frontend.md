# Phase 5 — Frontend chat UI

Last updated: 2026-05-10

The student-facing chat lives at `frontend/`. It is a Vite + React + TS
bundle served as static files by the same FastAPI process that owns the
SSE stream and the conversations REST API. One service. One process.

## Layout

```
frontend/
├── index.html              # Vite entry; <div id="root">
├── package.json            # react 19, react-markdown 10, lucide-react 1
├── vite.config.ts          # /api + /health proxy → :8000 in dev
├── dist/                   # **committed** so deploy is `git pull && uv run uvicorn`
└── src/
    ├── main.tsx            # mounts <App>; imports tokens.css + app.css
    ├── App.tsx             # session lifecycle + composer + thread orchestration
    ├── api/
    │   ├── stream.ts       # hardened POST + SSE iterator → AsyncIterable<SseEvent>
    │   ├── types.ts        # full SSE event union
    │   └── conversations.ts# list / get / rename / delete REST client
    ├── state/
    │   ├── useChatStream.ts    # reduces SSE events into a Turn[] tree
    │   ├── useConversations.ts # sidebar list + per-request sequence token
    │   └── useStickyScroll.ts  # bottom-pinning scroll behavior
    ├── components/
    │   ├── Shell.tsx, Sidebar.tsx, TopBar.tsx, Composer.tsx, EmptyState.tsx
    │   ├── ReasoningTimeline.tsx, ToolCallItem.tsx, ToolIcon.tsx
    │   ├── MarkdownAnswer.tsx, CitationChip.tsx
    │   ├── ConversationRow.tsx, ConfirmDelete.tsx
    │   ├── JumpToLatest.tsx, Avatar.tsx, icons.tsx
    ├── styles/
    │   ├── tokens.css      # copy of the design system's colors_and_type.css
    │   └── app.css         # adapted from the kit's styles.css
    └── lib/
        ├── format.ts       # ms→"3.2 s", truncate, summarizeReasoning
        ├── citations.ts    # extract salleurl.edu refs from agent markdown
        └── userId.ts       # stable per-browser UUID in localStorage
```

## Dev / build

```bash
# dev (HMR + auto-reload)
cd frontend && npm install && npm run dev   # serves on :5173, /api proxied to :8000

# prod (single-process)
cd frontend && npm run build                 # writes ./dist
uv run uvicorn streaming:app --port 8000     # auto-picks up dist/
open http://localhost:8000
```

`frontend/node_modules` is gitignored. `frontend/dist` is **committed**:
the t3.micro deploy is `git pull && uv run uvicorn streaming:app` with no
Node toolchain on the box. Trade-off: rebuild before pushing UI changes.

## Streaming pipeline

1. `useChatStream.send(...)` → `streamQuery(body, signal)` (`api/stream.ts`).
2. SSE parser yields a typed `SseEvent`. Handles CRLF, multi-line
   `data:`, trailing-buffer flush, non-200 / wrong content-type → typed
   `StreamError`.
3. Reducer (`useChatStream`) interleaves `agent.thinking.*` and `tool.*`
   into a single `reasoning[]` array per turn, in arrival order.
4. `final_response.delta` accumulates into the answer markdown.
5. `cancelled` and `error` are terminal — the reducer does **not** wait
   for `session.ended` after them (the backend intentionally skips it).

`tool.end` matches `tool.start` by `call_id`, falling back to FIFO by
name. Mirrors the backend's matching so out-of-order tool completions
don't mis-attribute previews.

## Reasoning timeline

The `ReasoningTimeline` component pulses the active step while streaming,
auto-collapses to a `Thought for 3.2 s · 2 tools` chip about 350 ms after
the answer finishes, and is expandable on click. Tool rows show a
curated lucide icon (per tool name, see `ToolIcon.tsx`), args truncated
to 64 chars, and a duration + check on completion. Long previews fold
to a one-line "result" affordance.

## Conversation history

Three Mongo collections back the sidebar:

| Collection | Owner | Contents |
|---|---|---|
| `wiki_tutor_agent_sessions` | agno | text turns, tool_calls, ordering |
| `wiki_tutor_conversations_meta` | this app | title, lang, version, deleted_at |
| `wiki_tutor_turn_traces` | this app | thoughts + tool timings per turn |

Routes (`streaming_conversations.py`):

- `GET    /api/wiki-tutor/v1/conversations?user_id=…` — list
- `GET    /api/wiki-tutor/v1/conversations/{id}?user_id=…` — full transcript
- `PATCH  /api/wiki-tutor/v1/conversations/{id}` — rename, optimistic via `version`
- `DELETE /api/wiki-tutor/v1/conversations/{id}` — soft-delete

The list aggregation **drives from `wiki_tutor_conversations_meta`**
because agno does not consistently persist `user_id` on its session
document. We always have it on meta because we own writes there.

Trace docs are zipped to agno's `runs[]` by ordinal (started_at order),
not by run_id, because the recorder's run_id and agno's run_id live in
parallel namespaces. See `_build_replay_reasoning()`.

## Title polishing

After the first turn finishes, `core/title_polisher.py` schedules a
background task that calls `gpt-4o-mini` via the project's standard
Responses API + Pydantic `text_format` pattern. The polisher only
applies the new title when the meta row's `version` is unchanged — if
the user has manually renamed in the meantime, the LLM update is
discarded. ~$0.0001 per conversation.

## Production hardening

In `streaming.py`:

- **GZipMiddleware** with `minimum_size=1024`. The 1 KB threshold
  leaves SSE alone (its event chunks are tiny) but compresses the
  ~380 KB JS bundle to ~115 KB.
- **`_ImmutableStaticFiles`** subclass: hashed assets under `/assets/*`
  ship with `Cache-Control: public, max-age=31536000, immutable`.
- **SPA fallback**: `GET /{full_path:path}` returns the bundled
  `index.html` for non-API paths, so deep links survive a hard reload.
  `/api/*` and `/assets/*` are explicitly excluded.
- **Index headers**: baseline CSP, `Cache-Control: no-cache,
  must-revalidate`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`.

Mongo: the local docker container runs without auth. `.env` therefore
uses `mongodb://localhost:27017` (no user/pass). For Atlas, swap to the
`mongodb+srv://...` URL and the `ENVIRONMENT=dev` branch in
`utils/mongo_connection.py` builds it from the cluster-side fields.

## Smoke

```bash
uv run uvicorn streaming:app --port 8000
# In another terminal:
curl -N -X POST http://localhost:8000/api/wiki-tutor/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"Compare CS and AI bachelors","user_id":"smoke","lang":"en"}'
```

Expected: ~600+ SSE events including 3–5 balanced `tool.start`/`tool.end`
pairs, a `response.final`, then `session.ended`. Re-listing the
conversation immediately after returns the polished title within a
few seconds (background task; first list call may still show the
heuristic placeholder).
