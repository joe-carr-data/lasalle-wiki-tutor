"""Admin-only inspection endpoints.

Gated by ``core.auth.require_admin`` — loopback source IP plus, if set,
the ``WIKI_TUTOR_ADMIN_TOKEN`` header. The operator reaches these through
an SSM port-forward to the EC2 instance::

    aws ssm start-session \\
      --target $(terraform output -raw instance_id) \\
      --document-name AWS-StartPortForwardingSession \\
      --parameters '{"portNumber":["8000"],"localPortNumber":["8000"]}'
    curl http://127.0.0.1:8000/api/admin/connections \\
      -H "X-Admin-Token: $WIKI_TUTOR_ADMIN_TOKEN"

The endpoints return JSON only. There is no admin UI in the bundled
frontend; the gate UI shows whatever the shared evaluator token unlocks
and nothing else.
"""

from __future__ import annotations

import logging
from typing import Any

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException

from core.auth import check_admin_rate_limit, require_admin
from core.conversations_store import get_store


def _serialize_dt(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[
        Depends(check_admin_rate_limit),
        Depends(require_admin),
    ],
    include_in_schema=False,
)


@router.get("/connections")
async def list_connections(limit: int = 200) -> dict[str, Any]:
    """Aggregate the IP audit log into one row per distinct source IP.

    Each row carries first/last activity, the count of distinct
    conversations that IP has participated in, and the total turn count
    across all of them. Records auto-expire 30 days after the last turn
    via the TTL index on ``wiki_tutor_ip_records.last_seen_at``.
    """
    store = get_store()
    rows = await store.aggregate_connections_by_ip(limit=limit)
    return {
        "count": len(rows),
        "ttl_days": 30,
        "rows": rows,
    }


@router.get("/connections/{ip}/conversations")
async def conversations_for_ip(ip: str, limit: int = 100) -> dict[str, Any]:
    """Drill down: list the conversations a given IP has touched.

    Joins the IP audit log against the conversation-meta side-car so
    each row carries a title and language for human inspection.
    """
    if not ip:
        raise HTTPException(status_code=400, detail="ip is required")
    store = get_store()
    rows = await store.list_conversations_for_ip(ip=ip, limit=limit)
    return {
        "ip": ip,
        "count": len(rows),
        "rows": rows,
    }


@router.get("/conversations/{session_id}")
async def conversation_full(session_id: str) -> dict[str, Any]:
    """Full transcript for one conversation, by session id.

    Skips the user_id ownership check that the evaluator endpoint applies
    (admin sees everything). Returns the same shape so the frontend can
    reuse the existing transcript-render components.
    """
    store = get_store()
    doc = await store.get_full(session_id=session_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {
        **doc,
        "created_at": _serialize_dt(doc.get("created_at")),
        "updated_at": _serialize_dt(doc.get("updated_at")),
    }
