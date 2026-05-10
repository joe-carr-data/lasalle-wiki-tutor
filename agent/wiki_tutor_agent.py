"""LaSalle Wiki Tutor — single-agent skeleton with a dummy tool.

Mirrors the architecture of `lqc-ai-assistant-lib/origination_agent.py:OriginationAgent`
and `underwriting_agent.py:UnderwritingDirect`:

- Inherits from ``BaseStreamingAgent`` to get the OpenAI event interception
  loop, parallel-safe tool tracking, and reasoning-event emission for free.
- Wraps an Agno ``Agent`` configured the same way as the production
  underwriting/origination agents (OpenAIResponses model, MongoDb session
  persistence, history, telemetry off).
- Exposes a single dummy tool ``echo_question`` that returns its input.
  Replaced in Phase 4 with the catalog wiki tools.

Use the ``WikiTutorAgentConfig`` dataclass to override model / reasoning
settings without touching this module.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from agno.agent import Agent
from agno.db.mongo import MongoDb
from agno.models.openai import OpenAIResponses

from agent.catalog_wiki_tools import CATALOG_TOOL_NAMES, build_catalog_tools
from config.settings import MONGO_SETTINGS, PROJECT_SETTINGS
from core.base_streaming_agent import BaseStreamingAgent
from events import AgentEvent, EventType
from events.models import AgentRole
from utils.mongo_connection import get_mongo_uri

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
#                          AGENT CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class WikiTutorAgentConfig:
    """Tunable parameters for the Wiki Tutor agent.

    Defaults mirror the production underwriting/origination agents:
    ``gpt-5.4`` with medium reasoning effort, MongoDB-backed sessions,
    8 turns of history, telemetry disabled.
    """

    model_id: str = "gpt-5.4"
    reasoning_effort: str = "medium"           # "none" | "low" | "medium" | "high"
    reasoning_summary: str = "auto"
    num_history_runs: int = 8
    add_history_to_context: bool = True
    markdown: bool = True
    telemetry: bool = False
    session_collection: str = "wiki_tutor_agent_sessions"

    def to_openai_responses(self) -> OpenAIResponses:
        """Build the Agno OpenAIResponses model for this config."""
        kwargs: dict[str, Any] = {"id": self.model_id}
        # Reasoning is only meaningful for the o-series / gpt-5.x models that
        # support it (matches the underwriting agent's runtime check).
        if "5" in self.model_id and self.reasoning_effort != "none":
            kwargs["reasoning"] = {
                "effort": self.reasoning_effort,
                "summary": self.reasoning_summary,
            }
        return OpenAIResponses(**kwargs)


# ═══════════════════════════════════════════════════════════════════════
#                              SYSTEM PROMPT
# ═══════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
You are the **LaSalle Wiki Tutor**, an AI study advisor for prospective and
current students of **La Salle Campus Barcelona** (Universitat Ramon Llull).

Your job is to help students discover, compare, and understand the academic
programs the school offers — bachelors, masters, doctorates, specialization
courses, online programs, and summer school.

## Language

Always answer in the user's language. Detect it from their question:
- English → call tools with ``lang="en"``.
- Spanish → call tools with ``lang="es"``.
- Mixed / unclear → default to English.

## Tools — when to use what

You have **10 read-only tools** that read the LaSalle catalog wiki. Use them
liberally; don't guess at facts. Budget: **≤ 5 tool calls per response** in
the common case.

| Situation | Tool to call |
|---|---|
| Free-text query: "I'm into AI", "anything with games?" | ``search_programs`` |
| Structured browse: "show all bachelors", "online masters" | ``list_programs`` |
| First-time orientation / "what areas do you have?" | ``get_index_facets`` |
| Drill into a specific program | ``get_program`` |
| One section of a program (admission, careers, etc.) | ``get_program_section`` |
| "What courses will I take?" / year-by-year | ``get_curriculum`` |
| One specific subject (course) | ``get_subject`` |
| Comparing 2–4 programs | ``compare_programs`` |
| Routing questions ("how do I find online programs?") | ``get_faq`` |
| Unfamiliar academic term ("what's an ECTS?") | ``get_glossary_entry`` |

A typical flow:

1. ``search_programs`` (or ``list_programs`` with filters) → get 3–8 candidates.
2. If the student named one specifically: ``get_program`` (or
   ``get_program_section``).
3. For comparisons: ``compare_programs`` with the canonical ids you got back.

## Identifiers

Programs are addressed by ``canonical_program_id`` like
``"en/bachelor-animation-and-vfx"`` or ``"es/grado-en-animacion-y-vfx"``.
Subjects use ``canonical_subject_id`` of the same shape. The ``en/`` or
``es/`` prefix matches the language tree.

## Citations — link every program / subject you mention

**Every program, subject, FAQ, or glossary entry you mention must be cited
as a clickable markdown link to the official LaSalle page.** The tools
return a ``source_url`` field on every record (e.g.
``"https://www.salleurl.edu/en/education/bachelor-animation-and-vfx"``).
Use that URL — never invent one.

Format the citation as a plain markdown link with the program title as
the link text:

> The [**Bachelor in Animation and VFX**](https://www.salleurl.edu/en/education/bachelor-animation-and-vfx)
> is a 4-year on-site program …

For tables and bullet lists, the title cell should itself be a markdown
link:

> | Program | Level | ECTS |
> |---|---|---|
> | [Bachelor in Animation and VFX](https://www.salleurl.edu/en/education/bachelor-animation-and-vfx) | bachelor | 240 |

When you list multiple programs in a row, link each title individually
in the same way — never collapse them into a single "see more" link.

For program **sections** (goals, curriculum, careers, …) the section's
``source_url`` points at the deeper page (e.g.
``…/bachelor-animation-and-vfx/syllabus``). Link to that deeper URL when
you cite the section directly.

For **subjects** (courses), each tool returns the subject's own
``source_url`` (e.g. ``https://www.salleurl.edu/en/sculpting-anatomy-…``).
Link to that.

If the student asks for the canonical id (rarely), append it in
backticks AFTER the link, not instead of it:

> [**Bachelor in AI and Data Science**](https://www.salleurl.edu/en/education/bachelor-artificial-intelligence-and-data-science)
> (`en/bachelor-artificial-intelligence-and-data-science`)

Never fabricate program names, ECTS counts, durations, course lists, or
URLs. If the tools don't return a ``source_url`` for something, omit the
link rather than invent one.

## Pricing

The catalog **does not publish tuition**. If the student asks about cost,
direct them to admissions:

- EN: <https://www.salleurl.edu/en/admissions>
- ES: <https://www.salleurl.edu/es/admisiones>

Don't invent numbers.

## Style

- Markdown, with headings/tables when comparing 2+ items.
- Friendly, concise, neutral tone — you're an advisor, not a salesperson.
- Lead with what the student asked; structure follows.
- When ambiguous, ask one clarifying question instead of guessing.
"""


# ═══════════════════════════════════════════════════════════════════════
#                                AGENT
# ═══════════════════════════════════════════════════════════════════════


class WikiTutorAgent(BaseStreamingAgent):
    """Streaming agent for the LaSalle Wiki Tutor.

    Built on top of ``BaseStreamingAgent`` so we inherit:
    - OpenAI stream interception (reasoning + tool + response events)
    - Background drain task that emits AgentEvents in order
    - Parallel-safe tool tracking and TOOL_END correlation
    - Reasoning lifecycle tracking

    Note: the base class assumes structured JSON output with a
    ``"response":"…"`` key (the underwriting/origination pattern). This
    agent uses plain markdown output, so we override the delta handler
    to emit raw text directly (no JSON unwrapping).
    """

    def __init__(
        self,
        session_id: str,
        user_id: str = "",
        config: WikiTutorAgentConfig | None = None,
    ) -> None:
        super().__init__(
            agent_role=AgentRole.ASSISTANT,
            agent_name=PROJECT_SETTINGS.ASSISTANT_NAME,
            session_id=session_id,
            user_id=user_id,
            tool_result_queues={name: [] for name in CATALOG_TOOL_NAMES},
        )
        self._config = config or WikiTutorAgentConfig()
        self._agent: Agent | None = None
        self._tools: list[Callable] = []
        # Track whether we've emitted any response delta this run, so the
        # streaming layer can fall back to "no response" only if truly empty.
        self._response_started = False

    # Override: plain-markdown agent — bypass JSON `"response":"…"` extraction.
    async def _handle_json_response_delta(self, delta: str) -> None:  # type: ignore[override]
        """Emit raw model output as RESPONSE_DELTA events with no JSON parsing."""
        if not delta:
            return
        if not self._response_started:
            self._response_started = True
        await self.event_manager.emit(AgentEvent(
            event_type=EventType.RESPONSE_DELTA,
            agent_role=self._agent_role,
            agent_name=self._agent_name,
            content=delta,
            session_id=self.session_id,
        ))

    async def _handle_openai_event(self, event) -> None:  # type: ignore[override]
        """Wrap base handler to emit RESPONSE_END when a text turn finishes."""
        await super()._handle_openai_event(event)
        if getattr(event, "type", "") == "response.output_text.done":
            if self._response_started:
                self._response_started = False
                await self.event_manager.emit(AgentEvent(
                    event_type=EventType.RESPONSE_END,
                    agent_role=self._agent_role,
                    agent_name=self._agent_name,
                    session_id=self.session_id,
                ))

    # ──────────────────────────────────────────────────────────────────
    # BaseStreamingAgent lifecycle hooks
    # ──────────────────────────────────────────────────────────────────

    async def async_setup(self) -> None:
        """Build the catalog tools and configure the underlying Agno agent."""
        self._tools = build_catalog_tools(self)

        self._agent = Agent(
            name=PROJECT_SETTINGS.ASSISTANT_NAME,
            model=self._config.to_openai_responses(),
            tools=self._tools,
            instructions=_SYSTEM_PROMPT,
            markdown=self._config.markdown,
            db=MongoDb(
                db_url=get_mongo_uri(),
                db_name=MONGO_SETTINGS.MONGO_DATABASE,
                session_collection=self._config.session_collection,
            ),
            session_id=self.session_id,
            add_history_to_context=self._config.add_history_to_context,
            num_history_runs=self._config.num_history_runs,
            telemetry=self._config.telemetry,
        )
        logger.info(
            "[WikiTutor] Agent ready (model=%s, session=%s)",
            self._config.model_id,
            self.session_id[:8],
        )

    async def run(self, question: str) -> dict[str, Any]:
        """Stream the agent over a question and return a small result dict.

        Returns the run identifier — most callers should subscribe to
        ``self.event_manager`` for the streamed AgentEvents.
        """
        if self._agent is None:
            raise RuntimeError("WikiTutorAgent.async_setup() was not called")

        run_id = str(uuid.uuid4())

        # `agent.arun(stream=True)` returns an async generator — iterate it
        # directly. The OpenAI event interceptor (installed in `setup()`) is
        # what actually emits AgentEvents; the iterator just drives the stream.
        response_text = ""
        async for event in self._agent.arun(
            question,
            session_id=self.session_id,
            stream=True,
            yield_run_output=True,
        ):
            if hasattr(event, "content") and event.content:
                response_text = event.content

        # Flush any remaining queued events so the caller sees them in order.
        await self.flush_events()
        return {
            "run_id": run_id,
            "session_id": self.session_id,
            "response": response_text,
        }

    async def _on_cleanup(self) -> None:
        """Release agent-specific resources (none for the dummy)."""
        self._agent = None
        self._tools = []
