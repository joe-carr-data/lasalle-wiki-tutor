"""Agno-compatible tools that wrap ``catalog_wiki_api`` v1.

These are the ten functions the LLM agent has access to. Each one:

- Has a clear docstring (Agno builds the tool schema from it).
- Accepts simple primitive args (Agno tool-schema-friendly).
- Returns a JSON string the LLM can parse.
- Catches all expected errors (``CatalogApiError``, ``ValueError``, etc.)
  and turns them into a structured ``{"ok": false, "error": ...}`` payload
  rather than letting an exception bubble up.
- Calls ``agent.on_tool_result(...)`` after the work is done so the
  ``BaseStreamingAgent`` event loop emits a ``TOOL_END`` SSE event.

The factory ``build_catalog_tools(agent)`` returns a list of bound tool
callables ready to hand to ``agno.agent.Agent(tools=...)``.

The full list of tool names is exported as ``CATALOG_TOOL_NAMES`` so the
``WikiTutorAgent`` can pre-register the ``tool_result_queues`` for each.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import catalog_wiki_api as api
from catalog_wiki_api import CatalogApiError

logger = logging.getLogger(__name__)

# Generic message returned to the LLM when an unexpected exception is caught.
# We deliberately do NOT include ``str(exc)`` because exception strings can
# leak internal paths, secrets, or stack-trace fragments. The full
# traceback is captured via ``logger.exception`` for operator triage.
_GENERIC_ERROR_MSG = (
    "An unexpected error occurred while running this tool. Please retry "
    "with a different query, or escalate to admissions if the issue persists."
)


# ---------------------------------------------------------------------------
# Names exported for tool_result_queues bookkeeping
# ---------------------------------------------------------------------------

CATALOG_TOOL_NAMES: tuple[str, ...] = (
    "search_programs",
    "list_programs",
    "get_index_facets",
    "get_program",
    "get_program_section",
    "get_curriculum",
    "get_subject",
    "compare_programs",
    "get_faq",
    "get_glossary_entry",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(payload: Any) -> str:
    """Serialize a payload to compact JSON the LLM can read."""
    return json.dumps(payload, ensure_ascii=False, default=str)


def _error(code: str, message: str) -> str:
    """Build a structured error response."""
    return _json({"ok": False, "error": {"code": code, "message": message}})


def _clean(value: str | None) -> str | None:
    """Normalize an optional string parameter: empty / whitespace-only → None.

    OpenAI's strict-mode tool calling sometimes emits ``""`` for optional
    string fields instead of omitting them. Without this, an empty
    filter would slip through and the catalog API rejects it as an
    invalid enum value. Treat empty as "no filter" — what the LLM
    almost certainly meant.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _clean_lang(value: str | None, *, default: str = "en") -> str:
    """Like :func:`_clean` but for the ``lang`` knob, which is never null."""
    cleaned = _clean(value)
    return cleaned if cleaned else default


def _missing_arg(name: str, hint: str) -> str:
    """Build a structured error response for a missing required arg."""
    return _error(
        "missing_argument",
        f"Required argument '{name}' was empty. {hint}",
    )


def _summary_of(payload: dict | list, *, head: int = 200) -> str:
    """Compact preview string for the TOOL_END event's ``result_preview``."""
    s = _json(payload)
    return s if len(s) <= head else s[: head - 3] + "..."


def _claim_call_id(agent: Any, tool_name: str) -> str | None:
    """Atomically claim the call_id of the oldest unclaimed active tool by name.

    The framework (``BaseStreamingAgent`` + ``OpenAIEventInterceptor``)
    populates ``agent._active_tools[call_id] = {"name", "started_at", ...}``
    *before* dispatching the tool function. A tool function calling this
    synchronously (no ``await`` between dispatch and the call) gets its
    own call_id, even when multiple same-named tools run in parallel and
    finish out of order.

    We mark the entry with ``_claimed=True`` so a sibling parallel call
    can't grab the same entry. The framework still pops the entry on
    ``on_tool_result`` (exact call_id match path), so this flag is
    transient.
    """
    active = getattr(agent, "_active_tools", None)
    if not active:
        return None
    for cid, info in active.items():
        if info.get("name") == tool_name and not info.get("_claimed"):
            info["_claimed"] = True
            return cid
    return None


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_catalog_tools(agent: Any) -> list[Callable]:
    """Return the catalog tool callables, bound to the given agent.

    The agent is the ``BaseStreamingAgent`` subclass — we close over it so
    each tool can call ``on_tool_result`` after finishing, which is what
    causes a ``TOOL_END`` SSE event to fire.
    """

    async def _emit_end(name: str, payload_str: str, call_id: str | None) -> None:
        try:
            await agent.on_tool_result(
                tool_name=name,
                summary=payload_str[:500],
                call_id=call_id,
            )
        except Exception as exc:  # pragma: no cover — best-effort
            logger.warning("[catalog_tools] on_tool_result(%s) raised: %s", name, exc)

    # ──────────────────────────────────────────────────────────────────
    # Discovery / search
    # ──────────────────────────────────────────────────────────────────

    async def search_programs(
        query: str,
        lang: str = "en",
        level: str | None = None,
        area: str | None = None,
        modality: str | None = None,
        top_k: int = 8,
    ) -> str:
        """Hybrid (BM25 + semantic) search over the program catalog.

        This is the primary retrieval tool. Use it whenever the student asks
        about a topic, an interest, or a vague program description. Prefer it
        over ``list_programs`` for free-text queries.

        Args:
            query: The student's search phrase. Synonyms are expanded
                automatically (e.g. "machine learning" → AI; "hacking" →
                cybersecurity).
            lang: ``"en"`` or ``"es"`` — match the user's language.
            level: Optional filter — one of ``bachelor``, ``master``,
                ``doctorate``, ``specialization``, ``online``, ``summer``,
                ``other``.
            area: Optional area filter — one of the keys returned by
                ``get_index_facets`` (``ai-data-science``, ``architecture``,
                ``business-management``, ``computer-science``,
                ``cybersecurity``, ``animation-digital-arts``,
                ``telecom-electronics``, ``health-engineering``,
                ``philosophy-humanities``, ``project-management``).
            modality: Optional — ``on-site``, ``online``, ``hybrid``.
            top_k: How many candidates to return (default 8).

        Returns:
            JSON: ``{"ok": True, "query": ..., "total": N, "results": [...]}``.
        """
        call_id = _claim_call_id(agent, "search_programs")
        cleaned_query = _clean(query)
        if cleaned_query is None:
            result = _missing_arg(
                "query",
                "Pass a free-text search phrase like 'computer science bachelor' "
                "or 'cybersecurity online'. If you don't have a query and just "
                "want to browse, call list_programs instead.",
            )
            await _emit_end("search_programs", result, call_id)
            return result
        try:
            filters = {
                "level": _clean(level),
                "area": _clean(area),
                "modality": _clean(modality),
            }
            payload = api.search_programs(cleaned_query, filters=filters, top_k=top_k, lang=_clean_lang(lang))
            out = {
                "ok": True,
                "query": payload["query"],
                "total": payload["total"],
                "results": payload["results"],
                "applied_filters": payload["applied_filters"],
                "lang": payload["lang"],
            }
            result = _json(out)
        except CatalogApiError as exc:
            result = _error(exc.code, exc.message)
        except Exception as exc:  # pragma: no cover
            logger.exception("search_programs failed")
            # Don't leak internal exception strings to the LLM. The
            # full traceback is captured by logger.exception above.
            result = _error("internal_error", _GENERIC_ERROR_MSG)
        await _emit_end("search_programs", result, call_id)
        return result

    async def list_programs(
        lang: str = "en",
        level: str | None = None,
        area: str | None = None,
        modality: str | None = None,
        language: str | None = None,
        offset: int = 0,
        limit: int = 30,
    ) -> str:
        """List programs with structured filters (no free-text search).

        Use this when the student asks "show me all bachelors", "what
        masters are online", "programs taught in English", etc.

        Args:
            lang: ``"en"`` or ``"es"``.
            level: Optional level filter (see ``search_programs``).
            area: Optional area filter (see ``search_programs``).
            modality: Optional — ``on-site``, ``online``, ``hybrid``.
            language: Optional language of instruction filter (e.g.
                ``"English"`` to find English-taught programs).
            offset: Pagination offset (default 0).
            limit: Max programs per call (default 30).

        Returns:
            JSON: ``{"ok": True, "total": N, "programs": [...], ...}``.
        """
        call_id = _claim_call_id(agent, "list_programs")
        try:
            payload = api.list_programs(
                level=_clean(level), area=_clean(area), modality=_clean(modality),
                language=_clean(language),
                lang=_clean_lang(lang), offset=offset, limit=limit,
            )
            out = {"ok": True, **payload}
            result = _json(out)
        except CatalogApiError as exc:
            result = _error(exc.code, exc.message)
        except Exception as exc:  # pragma: no cover
            logger.exception("list_programs failed")
            # Don't leak internal exception strings to the LLM. The
            # full traceback is captured by logger.exception above.
            result = _error("internal_error", _GENERIC_ERROR_MSG)
        await _emit_end("list_programs", result, call_id)
        return result

    async def get_index_facets(lang: str = "en") -> str:
        """Return all areas, levels, modalities, and instruction languages with counts.

        Use this once at the start of a session to understand what's in the
        catalog before drilling down. Cheap (single call, ~200 ms).

        Args:
            lang: ``"en"`` or ``"es"``.

        Returns:
            JSON: ``{"ok": True, "areas": [...], "levels": [...], ...}``.
        """
        call_id = _claim_call_id(agent, "get_index_facets")
        try:
            payload = api.get_index_facets(lang=_clean_lang(lang))
            result = _json({"ok": True, **payload})
        except CatalogApiError as exc:
            result = _error(exc.code, exc.message)
        except Exception as exc:  # pragma: no cover
            logger.exception("get_index_facets failed")
            # Don't leak internal exception strings to the LLM. The
            # full traceback is captured by logger.exception above.
            result = _error("internal_error", _GENERIC_ERROR_MSG)
        await _emit_end("get_index_facets", result, call_id)
        return result

    # ──────────────────────────────────────────────────────────────────
    # Detail retrieval
    # ──────────────────────────────────────────────────────────────────

    async def get_program(program_id: str, include_sections: bool = False) -> str:
        """Return the full detail for one program.

        Use this after ``search_programs`` to fetch the overview of the
        specific program(s) the student is interested in. Only set
        ``include_sections=True`` if the student needs a full deep-dive —
        the response gets large.

        Args:
            program_id: Canonical id, e.g. ``"en/bachelor-animation-and-vfx"``.
            include_sections: When ``True`` also returns the goals,
                requirements, careers, methodology, and faculty section
                bodies. Default ``False``.

        Returns:
            JSON: program detail with frontmatter + ``overview_md`` (and
            ``sections`` if requested).
        """
        call_id = _claim_call_id(agent, "get_program")
        cleaned_id = _clean(program_id)
        if cleaned_id is None:
            result = _missing_arg(
                "program_id",
                "Pass a canonical id like 'en/bachelor-artificial-intelligence' "
                "or 'es/grado-en-ingenieria-informatica'. Get ids from "
                "search_programs or list_programs results.",
            )
            await _emit_end("get_program", result, call_id)
            return result
        try:
            payload = api.get_program(cleaned_id, include_sections=include_sections)
            result = _json({"ok": True, **payload})
        except CatalogApiError as exc:
            result = _error(exc.code, exc.message)
        except Exception as exc:  # pragma: no cover
            logger.exception("get_program failed")
            # Don't leak internal exception strings to the LLM. The
            # full traceback is captured by logger.exception above.
            result = _error("internal_error", _GENERIC_ERROR_MSG)
        await _emit_end("get_program", result, call_id)
        return result

    async def get_program_section(program_id: str, section: str) -> str:
        """Return one section of a program's content.

        Sections (case-sensitive): ``goals``, ``requirements``,
        ``curriculum``, ``careers``, ``methodology``, ``faculty``.
        Use this when the student asks something focused (e.g. "what jobs
        can I get with this degree?" → fetch ``careers``).

        Args:
            program_id: Canonical id (e.g. ``"en/bachelor-animation-and-vfx"``).
            section: One of the six section names.

        Returns:
            JSON: ``{"ok": True, "section": ..., "body_markdown": "..."}``.
        """
        call_id = _claim_call_id(agent, "get_program_section")
        cleaned_id = _clean(program_id)
        cleaned_section = _clean(section)
        if cleaned_id is None:
            result = _missing_arg(
                "program_id",
                "Pass a canonical id like 'en/bachelor-artificial-intelligence'. "
                "Get ids from search_programs or list_programs results.",
            )
            await _emit_end("get_program_section", result, call_id)
            return result
        if cleaned_section is None:
            result = _missing_arg(
                "section",
                "Pass one of: goals, requirements, curriculum, careers, "
                "methodology, faculty. Case-sensitive.",
            )
            await _emit_end("get_program_section", result, call_id)
            return result
        try:
            payload = api.get_program_section(cleaned_id, cleaned_section)
            result = _json({"ok": True, **payload})
        except CatalogApiError as exc:
            result = _error(exc.code, exc.message)
        except Exception as exc:  # pragma: no cover
            logger.exception("get_program_section failed")
            # Don't leak internal exception strings to the LLM. The
            # full traceback is captured by logger.exception above.
            result = _error("internal_error", _GENERIC_ERROR_MSG)
        await _emit_end("get_program_section", result, call_id)
        return result

    async def get_curriculum(program_id: str) -> str:
        """Return the structured year-by-year curriculum for a program.

        Use this for "what courses will I take?" / "show me year 2 of
        the AI bachelor". The response is structured (year → semester →
        subjects) so the LLM can navigate it without re-parsing markdown.

        Args:
            program_id: Canonical id of the program.

        Returns:
            JSON: ``{"ok": True, "years": [{"year": ..., "sections":
            [{"semester": ..., "subjects": [...]}]}, ...]}``.
        """
        call_id = _claim_call_id(agent, "get_curriculum")
        cleaned_id = _clean(program_id)
        if cleaned_id is None:
            result = _missing_arg(
                "program_id",
                "Pass a canonical id like 'en/bachelor-artificial-intelligence'. "
                "Get ids from search_programs or list_programs results.",
            )
            await _emit_end("get_curriculum", result, call_id)
            return result
        try:
            payload = api.get_curriculum(cleaned_id)
            result = _json({"ok": True, **payload})
        except CatalogApiError as exc:
            result = _error(exc.code, exc.message)
        except Exception as exc:  # pragma: no cover
            logger.exception("get_curriculum failed")
            # Don't leak internal exception strings to the LLM. The
            # full traceback is captured by logger.exception above.
            result = _error("internal_error", _GENERIC_ERROR_MSG)
        await _emit_end("get_curriculum", result, call_id)
        return result

    async def get_subject(subject_id: str) -> str:
        """Return the full detail for one subject (course).

        Use this when the student asks about a specific course mentioned
        in a program's curriculum (e.g. "what is 'Linear algebra' about?").

        Args:
            subject_id: Canonical id, e.g. ``"en/algebra-lineal"``.

        Returns:
            JSON: subject detail (description, prerequisites, objectives,
            contents, methodology, evaluation, etc.).
        """
        call_id = _claim_call_id(agent, "get_subject")
        cleaned_id = _clean(subject_id)
        if cleaned_id is None:
            result = _missing_arg(
                "subject_id",
                "Pass a canonical subject id like 'en/algebra-lineal' or "
                "'es/programacion-de-graficos-3d-0'. Get ids from "
                "get_curriculum's subjects list.",
            )
            await _emit_end("get_subject", result, call_id)
            return result
        try:
            payload = api.get_subject(cleaned_id)
            result = _json({"ok": True, **payload})
        except CatalogApiError as exc:
            result = _error(exc.code, exc.message)
        except Exception as exc:  # pragma: no cover
            logger.exception("get_subject failed")
            # Don't leak internal exception strings to the LLM. The
            # full traceback is captured by logger.exception above.
            result = _error("internal_error", _GENERIC_ERROR_MSG)
        await _emit_end("get_subject", result, call_id)
        return result

    # ──────────────────────────────────────────────────────────────────
    # Comparison & relations
    # ──────────────────────────────────────────────────────────────────

    async def compare_programs(program_ids: list[str]) -> str:
        """Return normalised comparable fields for N programs side-by-side.

        Use this for the comparison-shopper persona: "Difference between
        Bachelor in CS and Bachelor in AI?". Pass 2-4 canonical ids.

        Args:
            program_ids: List of canonical program ids.

        Returns:
            JSON: ``{"ok": True, "rows": [...], "lang": ...}``. Each row
            has the same keys (title, level, area, ects, modality,
            duration, languages_of_instruction, schedule, location,
            start_date, subject_count) so the LLM can render a table.
        """
        call_id = _claim_call_id(agent, "compare_programs")
        # Drop empty / blank ids that the LLM occasionally emits in a list
        # (e.g. ["", "en/bachelor-ai", ""]). Need at least two real ids
        # for the comparison to be meaningful.
        clean_ids = [pid for pid in (program_ids or []) if _clean(pid)]
        if len(clean_ids) < 2:
            result = _missing_arg(
                "program_ids",
                "Pass at least two canonical program ids, e.g. "
                "['en/bachelor-computer-engineering', 'en/bachelor-artificial-intelligence']. "
                "Get ids from search_programs or list_programs.",
            )
            await _emit_end("compare_programs", result, call_id)
            return result
        try:
            payload = api.compare_programs(clean_ids)
            result = _json({"ok": True, **payload})
        except CatalogApiError as exc:
            result = _error(exc.code, exc.message)
        except Exception as exc:  # pragma: no cover
            logger.exception("compare_programs failed")
            # Don't leak internal exception strings to the LLM. The
            # full traceback is captured by logger.exception above.
            result = _error("internal_error", _GENERIC_ERROR_MSG)
        await _emit_end("compare_programs", result, call_id)
        return result

    # ──────────────────────────────────────────────────────────────────
    # FAQ / glossary
    # ──────────────────────────────────────────────────────────────────

    async def get_faq(lang: str = "en") -> str:
        """Return the wiki's student FAQ document.

        Use this to answer routing questions ("how do I find programs in
        English?", "where is pricing?"). The FAQ explicitly documents
        that tuition is not on the site — when the student asks about
        cost, surface the admissions contact instead of guessing.

        Args:
            lang: ``"en"`` or ``"es"``.

        Returns:
            JSON: ``{"ok": True, "title": ..., "body_markdown": "..."}``.
        """
        call_id = _claim_call_id(agent, "get_faq")
        try:
            payload = api.get_faq(lang=_clean_lang(lang))
            result = _json({"ok": True, **payload})
        except CatalogApiError as exc:
            result = _error(exc.code, exc.message)
        except Exception as exc:  # pragma: no cover
            logger.exception("get_faq failed")
            # Don't leak internal exception strings to the LLM. The
            # full traceback is captured by logger.exception above.
            result = _error("internal_error", _GENERIC_ERROR_MSG)
        await _emit_end("get_faq", result, call_id)
        return result

    async def get_glossary_entry(term: str, lang: str = "en") -> str:
        """Look up a glossary term (e.g. ``"ECTS"``, ``"Modality"``, ``"Ramon Llull"``).

        Use this when the student uses unfamiliar academic terminology
        and a brief definition would help. Returns ``None`` if the term
        isn't in the glossary.

        Args:
            term: Term to look up (case-insensitive).
            lang: ``"en"`` or ``"es"``.

        Returns:
            JSON: ``{"ok": True, "entry": {...}}`` or
            ``{"ok": True, "entry": null}`` if not found.
        """
        call_id = _claim_call_id(agent, "get_glossary_entry")
        cleaned_term = _clean(term)
        if cleaned_term is None:
            result = _missing_arg(
                "term",
                "Pass a glossary term like 'ECTS', 'Modality', or 'Ramon Llull'. "
                "Case-insensitive. Get the available terms by reading the glossary "
                "section returned by get_faq, or just try the term as-is.",
            )
            await _emit_end("get_glossary_entry", result, call_id)
            return result
        try:
            entry = api.get_glossary_entry(cleaned_term, lang=_clean_lang(lang))
            result = _json({"ok": True, "entry": entry})
        except CatalogApiError as exc:
            result = _error(exc.code, exc.message)
        except Exception as exc:  # pragma: no cover
            logger.exception("get_glossary_entry failed")
            # Don't leak internal exception strings to the LLM. The
            # full traceback is captured by logger.exception above.
            result = _error("internal_error", _GENERIC_ERROR_MSG)
        await _emit_end("get_glossary_entry", result, call_id)
        return result

    return [
        search_programs,
        list_programs,
        get_index_facets,
        get_program,
        get_program_section,
        get_curriculum,
        get_subject,
        compare_programs,
        get_faq,
        get_glossary_entry,
    ]
