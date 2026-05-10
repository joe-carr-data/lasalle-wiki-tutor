"""Thin CLI wrapper for catalog_wiki_api.

Usage:
    uv run python -m catalog_wiki_api list-programs --level bachelor
    uv run python -m catalog_wiki_api search "artificial intelligence"
    uv run python -m catalog_wiki_api get-program en/bachelor-animation-and-vfx
    uv run python -m catalog_wiki_api curriculum en/bachelor-animation-and-vfx
    uv run python -m catalog_wiki_api facets

The CLI is for debugging and pilot simulation. All commands delegate to
the package functions; no logic is duplicated here.
"""

from __future__ import annotations

import json
import sys

import typer

from . import (
    CatalogApiError,
    compare_programs,
    get_curriculum,
    get_equivalent,
    get_faq,
    get_glossary_entry,
    get_index_facets,
    get_program,
    get_program_by_slug,
    get_program_section,
    get_related_programs,
    get_subject,
    list_languages,
    list_programs,
    list_subjects_for_program,
    search_programs,
)

app = typer.Typer(help="catalog_wiki_api thin CLI (debugging/pilot)")


def _emit(payload):
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _try(callable_):
    try:
        return callable_()
    except CatalogApiError as e:
        sys.stderr.write(f"[{e.code}] {e.message}\n")
        sys.exit(2)


@app.command("list-programs")
def cli_list_programs(
    level: str = typer.Option(None),
    area: str = typer.Option(None),
    modality: str = typer.Option(None),
    language: str = typer.Option(None),
    lang: str = typer.Option("en"),
    offset: int = typer.Option(0),
    limit: int = typer.Option(50),
) -> None:
    _emit(_try(lambda: list_programs(
        level=level, area=area, modality=modality, language=language,
        lang=lang, offset=offset, limit=limit,
    )))


@app.command("search")
def cli_search(
    query: str = typer.Argument(...),
    level: str = typer.Option(None),
    area: str = typer.Option(None),
    modality: str = typer.Option(None),
    top_k: int = typer.Option(10),
    lang: str = typer.Option("en"),
) -> None:
    _emit(_try(lambda: search_programs(
        query, filters={"level": level, "area": area, "modality": modality},
        top_k=top_k, lang=lang,
    )))


@app.command("facets")
def cli_facets(lang: str = typer.Option("en")) -> None:
    _emit(_try(lambda: get_index_facets(lang)))


@app.command("languages")
def cli_languages() -> None:
    _emit(_try(list_languages))


@app.command("get-program")
def cli_get_program(
    program_id: str = typer.Argument(...),
    sections: bool = typer.Option(False, "--sections", help="Include section bodies"),
) -> None:
    _emit(_try(lambda: get_program(program_id, include_sections=sections)))


@app.command("section")
def cli_section(
    program_id: str = typer.Argument(...),
    section: str = typer.Argument(..., help="goals|requirements|curriculum|careers|methodology|faculty"),
) -> None:
    _emit(_try(lambda: get_program_section(program_id, section)))  # type: ignore[arg-type]


@app.command("curriculum")
def cli_curriculum(program_id: str = typer.Argument(...)) -> None:
    _emit(_try(lambda: get_curriculum(program_id)))


@app.command("subject")
def cli_subject(subject_id: str = typer.Argument(...)) -> None:
    _emit(_try(lambda: get_subject(subject_id)))


@app.command("subjects")
def cli_subjects(program_id: str = typer.Argument(...)) -> None:
    _emit(_try(lambda: list_subjects_for_program(program_id)))


@app.command("by-slug")
def cli_by_slug(
    slug: str = typer.Argument(...),
    lang: str = typer.Option("en"),
) -> None:
    rec = get_program_by_slug(slug, lang)
    if rec is None:
        sys.stderr.write("not_found\n")
        sys.exit(2)
    _emit(rec)


@app.command("equivalent")
def cli_equivalent(
    program_id: str = typer.Argument(...),
    target_lang: str = typer.Argument(...),
) -> None:
    rec = _try(lambda: get_equivalent(program_id, target_lang))
    if rec is None:
        sys.stderr.write("no_equivalent\n")
        sys.exit(2)
    _emit(rec)


@app.command("related")
def cli_related(
    program_id: str = typer.Argument(...),
    top_k: int = typer.Option(5),
) -> None:
    _emit(_try(lambda: get_related_programs(program_id, top_k=top_k)))


@app.command("compare")
def cli_compare(program_ids: list[str] = typer.Argument(...)) -> None:
    _emit(_try(lambda: compare_programs(program_ids)))


@app.command("faq")
def cli_faq(lang: str = typer.Option("en")) -> None:
    _emit(_try(lambda: get_faq(lang)))


@app.command("glossary")
def cli_glossary(
    term: str = typer.Argument(...),
    lang: str = typer.Option("en"),
) -> None:
    rec = _try(lambda: get_glossary_entry(term, lang))
    if rec is None:
        sys.stderr.write("not_found\n")
        sys.exit(2)
    _emit(rec)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
