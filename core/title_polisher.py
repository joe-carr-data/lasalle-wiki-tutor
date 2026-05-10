"""Background LLM-driven conversation title polisher.

After the first turn of a conversation finishes, the meta row carries a
heuristic title (the user's first message, articles stripped). This module
fires a background asyncio task that calls a small OpenAI model to turn
that question into a 4–8-word conversation title.

Follows the project's "Direct LLM Call" convention (see
``lqc-ai-assistant-lib/.claude/skills/create-agentic-system/references/01-simple-llm-call.md``):
``AsyncOpenAI().responses.parse(input=…, text_format=PydanticModel)``.

Design constraints:

- **Off the hot path.** Fires after the SSE stream has finished.
- **Cheap.** ``gpt-4o-mini``, single call.
- **Safe under user edits.** :func:`ConversationsStore.set_polished_title`
  only applies the new title if the conversation's ``version`` is
  unchanged (i.e. the user hasn't manually renamed in the meantime).
- **Localized.** Honors the conversation's ``lang`` so EN questions get
  EN titles and ES questions get ES titles.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from openai import AsyncOpenAI, AuthenticationError, BadRequestError
from pydantic import BaseModel, Field

from core.conversations_store import clean_title, get_store

logger = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TitlePolisherConfig:
    model: str = "gpt-4o-mini"
    timeout_s: float = 8.0
    max_agent_preview_chars: int = 600


CONFIG = TitlePolisherConfig()


# ── Pydantic response model (structured output) ───────────────────────


class _TitleResponse(BaseModel):
    """Schema enforced by Responses API ``text_format``."""

    title: str = Field(
        description=(
            "A short conversation title summarizing the user's question. "
            "4 to 8 words. No quotes. No trailing punctuation. "
            "Match the user's language (English or Spanish)."
        )
    )


_SYSTEM_PROMPT = (
    "You generate concise conversation titles. "
    "Given a single user question and the assistant's reply, return a "
    "4-to-8-word title that captures the topic. "
    "No quotes. No trailing punctuation. "
    "Match the user's language exactly: if they wrote in Spanish, the title is in Spanish."
)


# ── Lazy singleton client ─────────────────────────────────────────────


_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()
    return _client


# ── Validation helpers ────────────────────────────────────────────────

_WORD_RE = re.compile(r"[\w'’-]+", re.UNICODE)


def _word_count(text: str) -> int:
    return sum(1 for _ in _WORD_RE.finditer(text or ""))


# ── LLM call ──────────────────────────────────────────────────────────


async def _generate_title(
    *, user_message: str, agent_message: str
) -> Optional[str]:
    """Single Responses-API call. Returns a cleaned title or None."""
    preview = (agent_message or "")[: CONFIG.max_agent_preview_chars]
    user_prompt = f"USER: {user_message}\nASSISTANT: {preview}"
    client = _get_client()

    kwargs = dict(
        model=CONFIG.model,
        input=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        text_format=_TitleResponse,
        temperature=0.2,
    )

    try:
        resp = await asyncio.wait_for(
            client.responses.parse(**kwargs),
            timeout=CONFIG.timeout_s,
        )
    except asyncio.TimeoutError:
        logger.info("title polisher timed out after %.1fs", CONFIG.timeout_s)
        return None
    except (AuthenticationError, BadRequestError) as exc:
        logger.warning("title polisher non-retryable failure: %s", exc)
        return None
    except Exception as exc:
        logger.info("title polisher LLM call failed: %s", exc)
        return None

    parsed: Optional[_TitleResponse] = resp.output_parsed
    if parsed is None or not parsed.title:
        return None

    cleaned = clean_title(parsed.title)
    if not cleaned:
        return None
    wc = _word_count(cleaned)
    if wc < 2 or wc > 12:
        logger.info("title polisher rejected length=%s text=%r", wc, cleaned)
        return None
    return cleaned


async def polish_title(
    *,
    session_id: str,
    user_message: str,
    agent_message: str,
    expected_version: int,
) -> None:
    """Generate + write a polished title. Idempotent, race-safe via the
    store's ``expected_version`` check."""
    title = await _generate_title(
        user_message=user_message, agent_message=agent_message
    )
    if not title:
        return
    try:
        store = get_store()
    except RuntimeError:
        # Mongo store not initialized (e.g. degraded mode).
        return
    try:
        applied = await store.set_polished_title(
            session_id=session_id,
            title=title,
            expected_version=expected_version,
        )
    except Exception as exc:  # pragma: no cover
        logger.info("title polisher write failed: %s", exc)
        return
    if applied:
        logger.info("polished title for session=%s: %r", session_id, title)


def schedule_polish(
    *,
    session_id: str,
    user_message: str,
    agent_message: str,
    expected_version: int,
) -> Optional[asyncio.Task[None]]:
    """Fire-and-forget wrapper. Returns the Task so callers/tests can
    ``await`` it; production code ignores the return value."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    return loop.create_task(
        polish_title(
            session_id=session_id,
            user_message=user_message,
            agent_message=agent_message,
            expected_version=expected_version,
        )
    )
