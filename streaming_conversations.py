"""FastAPI router for the wiki-tutor conversation history.

Four routes, all under ``/api/wiki-tutor/v1/conversations``:

- ``GET    /``        — list conversations for ``user_id``
- ``GET    /{id}``    — full transcript (3-source join: agno + meta + traces)
- ``PATCH  /{id}``    — rename (optimistic concurrency via ``version``)
- ``DELETE /{id}``    — soft-delete; agno's session document is also dropped

The store layer lives in :mod:`core.conversations_store`.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.auth import require_access_token
from core.conversations_store import get_store

logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/wiki-tutor/v1/conversations",
    tags=["conversations"],
    dependencies=[Depends(require_access_token)],
)


class ConversationRow(BaseModel):
    id: str
    title: str
    lang: str
    version: int
    turn_count: int
    updated_at: Optional[str] = None


class ConversationList(BaseModel):
    items: list[ConversationRow]


class RenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    expected_version: Optional[int] = None

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("title must not be empty")
        return v


def _serialize_dt(value) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@router.get("", response_model=ConversationList)
async def list_conversations(
    user_id: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ConversationList:
    store = get_store()
    rows = await store.list_for_user(user_id=user_id, limit=limit, offset=offset)
    return ConversationList(
        items=[
            ConversationRow(
                id=r["id"],
                title=r["title"],
                lang=r["lang"],
                version=r["version"],
                turn_count=r["turn_count"],
                updated_at=_serialize_dt(r.get("updated_at")),
            )
            for r in rows
        ]
    )


@router.get("/{session_id}")
async def get_conversation(
    session_id: str,
    user_id: Optional[str] = Query(None, min_length=1),
) -> dict:
    store = get_store()
    doc = await store.get_full(session_id=session_id, user_id=user_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {
        **doc,
        "created_at": _serialize_dt(doc.get("created_at")),
        "updated_at": _serialize_dt(doc.get("updated_at")),
    }


@router.patch("/{session_id}")
async def rename_conversation(
    session_id: str,
    body: RenameRequest,
) -> dict:
    store = get_store()
    try:
        row = await store.rename(
            session_id=session_id,
            title=body.title,
            expected_version=body.expected_version,
        )
    except ValueError as exc:
        # Distinguish "not found / version mismatch" from validation —
        # both surface as 409 to the client (refetch + retry).
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "id": row["_id"],
        "title": row["title"],
        "version": row["version"],
        "updated_at": _serialize_dt(row.get("updated_at")),
    }


@router.delete("/{session_id}", status_code=204)
async def delete_conversation(session_id: str) -> None:
    store = get_store()
    deleted = await store.soft_delete(session_id=session_id)
    if not deleted:
        # Idempotent for already-deleted conversations: still return 204.
        logger.info("conversation %s already deleted or absent", session_id)
    return None
