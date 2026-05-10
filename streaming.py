"""FastAPI SSE streaming for the LaSalle Wiki Tutor.

Single-agent simplified port of `lqc-ai-assistant-lib/underwriting_streaming.py`.
What's kept:

- AgentEvent → SSE conversion via the ported `BaseSSEAdapter`
- Cooperative cancellation via `core.cancellation_registry`
- The full SSE event vocabulary (session.started, agent.thinking.*,
  tool.*, final_response.*, response.final, error, cancelled)
- MongoDB-backed Agno session storage (history is wired through the agent)

What's stripped (vs. underwriting):

- Citation processing / web_search citation pipeline
- Graph display events
- File context / image upload pre-fetch
- MCP tool injection
- MongoDB persistence of `response.final` (not needed for the dummy)
- Multi-agent delegation events

Endpoints:

- ``POST /api/wiki-tutor/v1/query/stream`` — main query endpoint (SSE)
- ``POST /api/wiki-tutor/v1/query/cancel`` — cooperatively cancel a query

Run:

    uv run uvicorn streaming:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, field_validator

from agent import WikiTutorAgent, WikiTutorAgentConfig
from config.settings import PROJECT_SETTINGS
from core.base_sse_adapter import BaseSSEAdapter
from core.cancellation_registry import (
    cancel_query,
    register_query,
    unregister_query,
)
from core.conversations_store import close_store, init_store
from core.title_polisher import schedule_polish
from core.turn_trace_recorder import TurnTraceRecorder
from events import AgentEvent, EventType
from events.models import AgentRole
from fastapi_sse_contract import format_sse
from streaming_conversations import router as conversations_router

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#                       Request / response models
# ═══════════════════════════════════════════════════════════════════════


class WikiTutorQueryRequest(BaseModel):
    """SSE query request body."""

    query: str
    session_id: Optional[str] = None
    query_id: Optional[str] = None
    user_id: Optional[str] = None
    lang: Optional[str] = None  # "en" | "es"; client detects from text
    verbosity: Optional[int] = 3
    reasoning_effort: Optional[str] = None  # "none" | "low" | "medium" | "high"

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "What bachelor programs are available in AI?",
                "session_id": "session_abc123",
                "verbosity": 3,
                "reasoning_effort": "medium",
            }
        }
    )

    @field_validator("query")
    @classmethod
    def query_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query must not be empty")
        if len(v) > 100_000:
            raise ValueError("query must be 100,000 characters or fewer")
        return v


class CancelRequest(BaseModel):
    query_id: str


# ═══════════════════════════════════════════════════════════════════════
#                       Wiki Tutor SSE adapter
# ═══════════════════════════════════════════════════════════════════════


_TOOL_ICONS = {
    "echo_question": "💬",
    # Future catalog tools will register their icons here
}


class WikiTutorSSEAdapter(BaseSSEAdapter):
    """Thin subclass of BaseSSEAdapter for the Wiki Tutor.

    The base class handles every event type we need; we only override the
    constructor to set the agent metadata and tool icons.
    """

    def __init__(self, *, query: str, session_id: str, verbosity: int) -> None:
        super().__init__(
            agent_key="assistant",
            agent_display_name=PROJECT_SETTINGS.ASSISTANT_NAME,
            query=query,
            session_id=session_id,
            verbosity=verbosity,
            tool_icons=_TOOL_ICONS,
            response_origin="LASALLE_WIKI",
        )


# ═══════════════════════════════════════════════════════════════════════
#                       SSE generator
# ═══════════════════════════════════════════════════════════════════════


_DONE = object()


async def stream_query(
    *,
    query: str,
    session_id: str,
    query_id: str,
    user_id: str,
    lang: str,
    verbosity: int,
    reasoning_effort: Optional[str],
    cancellation_event: asyncio.Event,
) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted events for one query."""
    adapter = WikiTutorSSEAdapter(
        query=query, session_id=session_id, verbosity=verbosity,
    )
    event_queue: asyncio.Queue[Any] = asyncio.Queue()
    direct: Optional[WikiTutorAgent] = None

    try:
        # session.started
        yield format_sse(adapter.create_session_start())

        # Build agent (apply optional reasoning_effort override)
        cfg = WikiTutorAgentConfig()
        if reasoning_effort:
            cfg = WikiTutorAgentConfig(reasoning_effort=reasoning_effort)
        direct = WikiTutorAgent(
            session_id=session_id,
            user_id=user_id,
            config=cfg,
        )
        direct.setup()
        await direct.async_setup()

        # Per-turn trace recorder — runs in parallel with the SSE adapter.
        # ``agent_run_id`` is set on each AgentEvent by the event manager;
        # we capture it from the first event we see and key the trace by
        # it (matches agno's run_id).
        recorder = TurnTraceRecorder(
            session_id=session_id,
            user_id=user_id,
            run_id=query_id,  # default; replaced below once we see the real run_id
            lang=lang or "en",
        )
        # Track the agent's final answer text so the title polisher can
        # consider it. Built up from RESPONSE_DELTA content.
        answer_chunks: list[str] = []

        async def event_handler(event: AgentEvent) -> None:
            # Lazily lock in the real agno run_id the first time we see it.
            if event.agent_run_id and recorder._doc["_id"] == query_id:
                recorder._doc["_id"] = event.agent_run_id
            await recorder.on_event(event)
            if event.event_type == EventType.RESPONSE_DELTA and event.content:
                answer_chunks.append(event.content)
            sse_events = await adapter.convert(event)
            for sse_event in sse_events:
                await event_queue.put(format_sse(sse_event))

        direct.event_manager.subscribe(event_handler)

        async def run_agent() -> None:
            try:
                await direct.run(query)
                # Fallback: if the model never streamed deltas, emit a
                # response.delta + response.end so the client always sees a
                # final response.
                if not adapter._final_response_started:
                    await direct.event_manager.emit(AgentEvent(
                        event_type=EventType.RESPONSE_DELTA,
                        agent_role=AgentRole.ASSISTANT,
                        agent_name=PROJECT_SETTINGS.ASSISTANT_NAME,
                        content="(no response generated)",
                        session_id=session_id,
                    ))
                    await direct.event_manager.emit(AgentEvent(
                        event_type=EventType.RESPONSE_END,
                        agent_role=AgentRole.ASSISTANT,
                        agent_name=PROJECT_SETTINGS.ASSISTANT_NAME,
                        session_id=session_id,
                    ))
            except asyncio.CancelledError:
                logger.info("[wiki-sse] Query cancelled query_id=%s", query_id)
                raise
            except Exception as exc:  # pragma: no cover — surfaced as SSE error
                logger.error("[wiki-sse] Agent error: %s", exc, exc_info=True)
                err_event = adapter.create_error(exc)
                await event_queue.put(format_sse(err_event))
            finally:
                await direct.flush_events()
                await event_queue.put(_DONE)

        query_task = asyncio.create_task(run_agent())
        was_cancelled = False

        # Stream events from queue, watching for cancellation
        while True:
            if cancellation_event.is_set():
                logger.info("[wiki-sse] Cancelling query_id=%s", query_id)
                query_task.cancel()
                try:
                    await asyncio.wait_for(query_task, timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass
                yield format_sse(adapter.create_cancelled(query_id))
                was_cancelled = True
                break

            get_task = asyncio.create_task(event_queue.get())
            cancel_wait = asyncio.create_task(cancellation_event.wait())
            done, pending = await asyncio.wait(
                {get_task, cancel_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()
                try:
                    await p
                except (asyncio.CancelledError, Exception):
                    pass

            if cancel_wait in done:
                continue

            event = get_task.result()
            if event is _DONE:
                break
            yield event

        if not query_task.cancelled():
            await query_task

        # On cancellation we deliberately skip ``response.final`` and
        # ``session.ended``. A cancelled query has no successful final
        # payload to persist, and clients should not interpret a cancelled
        # turn as a normal completion. The ``cancelled`` event already
        # signaled the terminal state.
        if not was_cancelled:
            try:
                final = adapter.create_response_final(user_id=user_id)
                yield format_sse(final)
            except Exception as exc:
                logger.error("[wiki-sse] response.final error: %s", exc, exc_info=True)

            # Surface this conversation in the sidebar. Idempotent — first
            # turn inserts with a heuristic title, later turns just bump
            # updated_at. Failures are non-fatal; chat still works.
            #
            # Same block writes the per-turn trace doc and (on the very
            # first turn for this conversation) schedules the LLM title
            # polisher in the background.
            if user_id:
                try:
                    from core.conversations_store import get_store

                    store = get_store()
                    is_first_turn = await store.meta.find_one(
                        {"_id": session_id}
                    ) is None
                    await store.ensure_meta(
                        session_id=session_id,
                        user_id=user_id,
                        first_user_message=query,
                        lang=lang or "en",
                    )
                    await recorder.flush(store)
                    if is_first_turn:
                        agent_text = "".join(answer_chunks)
                        schedule_polish(
                            session_id=session_id,
                            user_message=query,
                            agent_message=agent_text,
                            expected_version=1,
                        )
                except Exception as exc:  # pragma: no cover
                    logger.warning("[wiki-sse] post-turn persistence failed: %s", exc)

            yield format_sse(adapter.create_session_end())

    except GeneratorExit:
        logger.info("[wiki-sse] Client disconnected session_id=%s", session_id)
        if direct:
            await direct.cleanup()
        raise
    except Exception as exc:  # pragma: no cover
        logger.error("[wiki-sse] Stream error: %s", exc, exc_info=True)
        yield format_sse(adapter.create_error(exc))
    finally:
        if direct:
            await direct.cleanup()


# ═══════════════════════════════════════════════════════════════════════
#                                FastAPI app
# ═══════════════════════════════════════════════════════════════════════


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """App lifecycle hook — initializes the conversations Mongo store."""
    logger.info("LaSalle Wiki Tutor streaming starting up.")
    try:
        await init_store()
        logger.info("Conversations Mongo store ready.")
    except Exception as exc:  # pragma: no cover
        # Don't crash the API if Mongo is down — chat still works without
        # the sidebar. The store getter will raise per-request instead.
        logger.warning("Conversations Mongo store unavailable: %s", exc)
    yield
    await close_store()
    logger.info("LaSalle Wiki Tutor streaming shutting down.")


app = FastAPI(
    title="LaSalle Wiki Tutor — Streaming API",
    version="0.1.0",
    lifespan=_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(conversations_router)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "assistant": PROJECT_SETTINGS.ASSISTANT_NAME}


@app.post("/api/wiki-tutor/v1/query/stream")
async def query_stream(request: WikiTutorQueryRequest) -> StreamingResponse:
    session_id = request.session_id or str(uuid.uuid4())
    query_id = request.query_id or str(uuid.uuid4())
    cancellation_event = await register_query(query_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for event in stream_query(
                query=request.query,
                session_id=session_id,
                query_id=query_id,
                user_id=request.user_id or "",
                lang=request.lang or "en",
                verbosity=request.verbosity or 3,
                reasoning_effort=request.reasoning_effort,
                cancellation_event=cancellation_event,
            ):
                yield event
        finally:
            await unregister_query(query_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/wiki-tutor/v1/query/cancel")
async def query_cancel(request: CancelRequest) -> dict[str, Any]:
    found = await cancel_query(request.query_id)
    if not found:
        raise HTTPException(status_code=404, detail="query_id not found")
    return {"cancelled": True, "query_id": request.query_id}


# ═══════════════════════════════════════════════════════════════════════
#                       Static frontend (Phase 5)
# ═══════════════════════════════════════════════════════════════════════
#
# The Vite-built bundle lives at frontend/dist/. Mount it as:
#   - /assets/*  → hashed JS/CSS chunks (long immutable cache)
#   - /          → bundled index.html (no-cache; SPA entrypoint)
#
# When the bundle is missing (e.g. a developer runs FastAPI without a
# build) we keep the API endpoints alive and serve a small note at /.
# In dev, the frontend is normally served by Vite on :5173 with a /api
# proxy back to this process — those clients never hit /.

_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "dist"
_FRONTEND_INDEX = _FRONTEND_DIST / "index.html"
_FRONTEND_ASSETS = _FRONTEND_DIST / "assets"


def _index_response() -> FileResponse:
    """Serve the SPA shell with no-cache so redeploys roll out cleanly."""
    return FileResponse(
        _FRONTEND_INDEX,
        media_type="text/html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


if _FRONTEND_ASSETS.exists():
    # Hashed assets — content-addressed by Vite, safe to cache forever.
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_ASSETS),
        name="frontend-assets",
    )

if _FRONTEND_INDEX.exists():
    @app.get("/", include_in_schema=False)
    async def frontend_root() -> FileResponse:  # type: ignore[no-redef]
        return _index_response()
else:
    @app.get("/", include_in_schema=False)
    async def frontend_root_missing() -> dict[str, Any]:  # type: ignore[no-redef]
        return {
            "status": "no-frontend-bundle",
            "hint": (
                "Build the frontend with `cd frontend && npm install && "
                "npm run build`, or run `npm run dev` in dev mode and "
                "use http://localhost:5173 instead."
            ),
        }
