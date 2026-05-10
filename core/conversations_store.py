"""MongoDB store for the wiki-tutor conversation list.

The agno session collection (``wiki_tutor_agent_sessions``) is owned by
``agno`` itself — we never write to it. We add two side-cars:

- ``wiki_tutor_conversations_meta`` — the per-conversation metadata that
  agno does not track: title (heuristic + LLM-polished), language, soft
  delete, and a ``version`` field for optimistic concurrency on rename.
- ``wiki_tutor_turn_traces`` — per-turn reasoning + tool-timing snapshot
  written by ``core.turn_trace_recorder`` (hooked up in Task #65). This
  module reads from it for replay, but does not write.

All public methods are ``async``; they wrap pymongo's ``AsyncMongoClient``
(available since pymongo 4.9). The store is lifecycle-managed by FastAPI
via ``init_store()`` / ``close_store()`` in ``streaming.py``.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from config.settings import MONGO_SETTINGS
from utils.mongo_connection import get_mongo_uri

logger = logging.getLogger(__name__)

# Collection names. The agno collection name is duplicated from
# ``WikiTutorAgentConfig.session_collection`` — keep them in sync if either
# moves.
AGNO_SESSIONS = "wiki_tutor_agent_sessions"
META = "wiki_tutor_conversations_meta"
TRACES = "wiki_tutor_turn_traces"

# Heuristic title generation — first user message, articles stripped.
_LEADING_ARTICLES = re.compile(
    r"^(the|a|an|el|la|los|las|un|una|unos|unas)\s+", re.IGNORECASE
)
_TITLE_MAX_CHARS = 60
_USER_TITLE_MAX_CHARS = 80
_USER_TITLE_MIN_CHARS = 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def heuristic_title(text: str) -> str:
    """Cheap placeholder title shown until the LLM polisher fires."""
    cleaned = (text or "").strip().replace("\n", " ")
    cleaned = _LEADING_ARTICLES.sub("", cleaned).strip()
    if len(cleaned) > _TITLE_MAX_CHARS:
        cleaned = cleaned[: _TITLE_MAX_CHARS - 1].rstrip() + "…"
    return cleaned or "Untitled"


def clean_title(raw: str) -> str:
    """Normalize a title coming from a user PATCH or the LLM polisher."""
    t = (raw or "").strip().strip("\"'").rstrip(".!?;:,")
    if len(t) > _USER_TITLE_MAX_CHARS:
        t = t[:_USER_TITLE_MAX_CHARS].rstrip()
    return t


class ConversationsStore:
    """Thin async wrapper over the three relevant collections."""

    def __init__(self, client: AsyncMongoClient, db_name: str) -> None:
        self._client = client
        self._db = client[db_name]

    @property
    def meta(self):
        return self._db[META]

    @property
    def sessions(self):
        return self._db[AGNO_SESSIONS]

    @property
    def traces(self):
        return self._db[TRACES]

    async def ensure_indexes(self) -> None:
        """Create the indexes we read against. Idempotent."""
        try:
            await self.sessions.create_index([("user_id", 1), ("updated_at", -1)])
            await self.meta.create_index([("deleted_at", 1)])
        except PyMongoError as exc:
            # Indexes are best-effort; a read-only Mongo (Atlas with limited
            # perms) should not crash startup.
            logger.warning("conversations index creation skipped: %s", exc)

    # ── Meta side-car (we own writes) ───────────────────────────────────

    async def ensure_meta(
        self,
        *,
        session_id: str,
        user_id: str,
        first_user_message: str,
        lang: str,
    ) -> None:
        """Idempotent upsert: create the meta row on first turn, otherwise
        bump ``updated_at`` so the sidebar surfaces this conversation."""
        now = _utc_now()
        title = heuristic_title(first_user_message)
        await self.meta.update_one(
            {"_id": session_id},
            {
                "$setOnInsert": {
                    "title": title,
                    "lang": lang,
                    "created_at": now,
                    "version": 1,
                    "deleted_at": None,
                    "title_polished_at": None,
                    "user_id": user_id,
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )

    async def rename(
        self, *, session_id: str, title: str, expected_version: Optional[int]
    ) -> dict[str, Any]:
        """Optimistic rename. Returns the patched row, or raises ValueError
        on a version conflict."""
        cleaned = clean_title(title)
        if len(cleaned) < _USER_TITLE_MIN_CHARS:
            raise ValueError("title must not be empty")

        match: dict[str, Any] = {"_id": session_id, "deleted_at": None}
        if expected_version is not None:
            match["version"] = expected_version

        result = await self.meta.find_one_and_update(
            match,
            {"$set": {"title": cleaned, "updated_at": _utc_now()}, "$inc": {"version": 1}},
            return_document=True,
        )
        if result is None:
            raise ValueError("conversation not found or version mismatch")
        return result

    async def set_polished_title(
        self, *, session_id: str, title: str, expected_version: int
    ) -> bool:
        """LLM-polisher writes only if the user hasn't renamed in the
        meantime. Returns True iff the title was applied."""
        cleaned = clean_title(title)
        if len(cleaned) < _USER_TITLE_MIN_CHARS:
            return False
        result = await self.meta.update_one(
            {"_id": session_id, "version": expected_version, "deleted_at": None},
            {
                "$set": {
                    "title": cleaned,
                    "title_polished_at": _utc_now(),
                    "updated_at": _utc_now(),
                },
                "$inc": {"version": 1},
            },
        )
        return bool(result.modified_count)

    async def soft_delete(self, *, session_id: str) -> bool:
        """Soft-delete the meta row AND drop the agno session document so
        re-using the id starts fresh.

        Returns True iff a row was actually marked deleted.
        """
        meta_res = await self.meta.update_one(
            {"_id": session_id, "deleted_at": None},
            {"$set": {"deleted_at": _utc_now()}, "$inc": {"version": 1}},
        )
        await self.sessions.delete_many({"session_id": session_id})
        return bool(meta_res.modified_count)

    # ── Read paths ──────────────────────────────────────────────────────

    async def list_for_user(
        self, *, user_id: str, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List non-deleted conversations for a user, ordered by recency.

        We drive from the meta side-car (we own writes to it, so user_id is
        always present) and look up the agno session for ``runs[]`` count.
        Agno itself does not always persist ``user_id`` on its session
        document, so a meta-driven list is more reliable than starting
        from the agno collection.
        """
        pipeline: list[dict[str, Any]] = [
            {"$match": {"user_id": user_id, "deleted_at": None}},
            {
                "$lookup": {
                    "from": AGNO_SESSIONS,
                    "localField": "_id",
                    "foreignField": "session_id",
                    "as": "session",
                }
            },
            {"$addFields": {"session": {"$arrayElemAt": ["$session", 0]}}},
            {
                "$project": {
                    "_id": 0,
                    "id": "$_id",
                    "title": {"$ifNull": ["$title", "Untitled"]},
                    "lang": {"$ifNull": ["$lang", "en"]},
                    "version": {"$ifNull": ["$version", 1]},
                    "updated_at": 1,
                    "turn_count": {
                        "$cond": [
                            {"$isArray": "$session.runs"},
                            {"$size": "$session.runs"},
                            0,
                        ]
                    },
                }
            },
            {"$sort": {"updated_at": -1}},
            {"$skip": int(offset)},
            {"$limit": int(limit)},
        ]
        cursor = await self.meta.aggregate(pipeline)
        return [doc async for doc in cursor]

    async def get_full(
        self, *, session_id: str, user_id: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Hydrate a full transcript for replay.

        Returns None if the session does not exist or is soft-deleted.
        """
        meta = await self.meta.find_one({"_id": session_id})
        if meta is not None and meta.get("deleted_at") is not None:
            return None
        if user_id and meta and meta.get("user_id") and meta["user_id"] != user_id:
            # Don't leak conversations across users (meta is authoritative
            # for ownership; agno's session.user_id is sometimes null).
            return None

        agno = await self.sessions.find_one({"session_id": session_id})
        if agno is None and meta is None:
            return None
        agno = agno or {}

        traces_cursor = self.traces.find({"session_id": session_id})
        traces = {doc["_id"]: doc async for doc in traces_cursor}

        turns = []
        for run in agno.get("runs", []) or []:
            run_id = run.get("run_id")
            user_msg = next(
                (m for m in run.get("messages", []) if m.get("role") == "user"),
                None,
            )
            agent_msg = next(
                (
                    m
                    for m in reversed(run.get("messages", []))
                    if m.get("role") == "assistant" and m.get("content")
                ),
                None,
            )
            trace = traces.get(run_id)
            turns.append(
                {
                    "run_id": run_id,
                    "user": {
                        "text": (user_msg or {}).get("content", ""),
                    },
                    "agent": {
                        "text": (agent_msg or {}).get("content", ""),
                    },
                    "reasoning": _build_replay_reasoning(run, trace),
                    "has_trace": trace is not None,
                }
            )

        return {
            "id": session_id,
            "title": (meta or {}).get("title", "Untitled"),
            "lang": (meta or {}).get("lang", "en"),
            "version": (meta or {}).get("version", 1),
            "created_at": (meta or {}).get("created_at"),
            "updated_at": agno.get("updated_at"),
            "turns": turns,
        }


def _build_replay_reasoning(
    run: dict[str, Any], trace: Optional[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Interleave thoughts (from trace) and tools (from agno + trace) by
    arrival time. If there's no trace, return tools only — the frontend
    will show a 'cannot replay reasoning' chip."""
    items: list[tuple[float, dict[str, Any]]] = []
    if trace:
        for thought in trace.get("thoughts", []) or []:
            items.append(
                (
                    float(thought.get("started_at") or 0),
                    {
                        "kind": "thought",
                        "text": thought.get("text", ""),
                        "started_at": thought.get("started_at"),
                        "ended_at": thought.get("ended_at"),
                    },
                )
            )
        for tool in trace.get("tool_timings", []) or []:
            items.append(
                (
                    float(tool.get("started_at") or 0),
                    {
                        "kind": "tool",
                        "name": tool.get("name", ""),
                        "args_display": tool.get("arguments_display", ""),
                        "duration_ms": tool.get("duration_ms"),
                        "duration_display": tool.get("duration_display"),
                        "preview": tool.get("preview", ""),
                        "icon": tool.get("icon", ""),
                    },
                )
            )
    else:
        # No trace — fall back to agno's tool messages so we at least show
        # which tools ran. Timings will be missing.
        for msg in run.get("messages", []) or []:
            if msg.get("role") == "tool":
                items.append(
                    (
                        float(time.mktime(msg["created_at"].timetuple()))
                        if isinstance(msg.get("created_at"), datetime)
                        else 0.0,
                        {
                            "kind": "tool",
                            "name": msg.get("tool_name", ""),
                            "args_display": str(msg.get("tool_args") or ""),
                            "preview": (msg.get("content") or "")[:240],
                        },
                    )
                )
    items.sort(key=lambda pair: pair[0])
    return [item for _, item in items]


# ── Module-level singleton, lifecycle-managed by streaming.py ──────────

_STORE: Optional[ConversationsStore] = None
_CLIENT: Optional[AsyncMongoClient] = None


async def init_store() -> ConversationsStore:
    """Initialize the singleton and create indexes. Called from FastAPI's
    lifespan startup hook."""
    global _STORE, _CLIENT
    if _STORE is not None:
        return _STORE
    _CLIENT = AsyncMongoClient(get_mongo_uri())
    _STORE = ConversationsStore(_CLIENT, MONGO_SETTINGS.MONGO_DATABASE)
    await _STORE.ensure_indexes()
    return _STORE


async def close_store() -> None:
    global _STORE, _CLIENT
    if _CLIENT is not None:
        await _CLIENT.close()
    _STORE = None
    _CLIENT = None


def get_store() -> ConversationsStore:
    """Sync getter for routers. Raises if init_store() was never called."""
    if _STORE is None:
        raise RuntimeError(
            "conversations store not initialized — did the FastAPI lifespan run?"
        )
    return _STORE
