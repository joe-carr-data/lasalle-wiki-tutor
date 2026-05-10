#!/usr/bin/env python3
"""Schematic diagrams (architecture, tool surface, retrieval flow, etc.)
rendered as vector PDFs via matplotlib. Same palette as make_figures.py.

Usage:
    uv run --group paper-figs python paper/scripts/make_schematics.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import patches
from matplotlib.patches import FancyArrow, FancyBboxPatch, FancyArrowPatch

mpl.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "axes.spines.bottom": False,
    "xtick.bottom": False,
    "ytick.left": False,
})

OUT = Path("paper/figures")
OUT.mkdir(parents=True, exist_ok=True)

BRAND_BLUE = "#5BA8DA"
BRAND_DARK = "#205C87"
BRAND_LIGHT = "#D3E8F6"
BRAND_ORANGE = "#E89E48"
BRAND_GREEN = "#7CB07C"
BRAND_PAPER = "#FAF8F4"
GRAY = "#9CA3AF"
GRAY_DARK = "#4B5563"
INK = "#111827"


def _box(ax, x, y, w, h, label, sublabel=None, fill=BRAND_BLUE, fg="white", border=BRAND_DARK, lw=0.8, rounding=0.05):
    """Draw a rounded box with a centered label."""
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0.02,rounding_size={rounding}",
        linewidth=lw,
        edgecolor=border,
        facecolor=fill,
    )
    ax.add_patch(box)
    if sublabel:
        ax.text(x + w / 2, y + h / 2 + h * 0.16, label, ha="center", va="center",
                fontsize=9, fontweight="bold", color=fg)
        ax.text(x + w / 2, y + h / 2 - h * 0.20, sublabel, ha="center", va="center",
                fontsize=7.5, color=fg, alpha=0.9)
    else:
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                fontsize=9, fontweight="bold", color=fg)


def _arrow(ax, x1, y1, x2, y2, color=GRAY_DARK, lw=1.0, style="-|>"):
    arr = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle=style,
        mutation_scale=12,
        color=color,
        linewidth=lw,
        zorder=2,
    )
    ax.add_patch(arr)


def _label(ax, x, y, text, fontsize=8, color=GRAY_DARK, fontweight="normal", italic=False):
    style = "italic" if italic else "normal"
    ax.text(x, y, text, ha="center", va="center", fontsize=fontsize, color=color, fontweight=fontweight, fontstyle=style)


# ─────────────────────────────────────────────────────────────────────────
# Figure 1 — Graphical abstract: bilingual question → tools → cited answer
# ─────────────────────────────────────────────────────────────────────────


def fig_graphical_abstract() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 6)
    ax.set_aspect("equal")
    ax.axis("off")

    # Title strip
    ax.text(7, 5.6, "LaSalle Wiki Tutor — compiled knowledge + deterministic tools + selective hybrid retrieval",
            ha="center", va="center", fontsize=10.5, fontweight="bold", color=INK)

    # Stage 1: question (left)
    _box(ax, 0.3, 2.8, 2.6, 1.6, "Student question",
         sublabel='"¿qué grado en IA\\ntenéis?"  (ES)',
         fill=BRAND_PAPER, fg=INK, border=GRAY_DARK)

    # Stage 2: agent + tools
    _box(ax, 3.6, 3.0, 3.0, 1.2, "Streaming agent",
         sublabel="Agno + GPT-5.4\n10 deterministic tools",
         fill=BRAND_BLUE, fg="white", border=BRAND_DARK)

    # Stage 3: wiki
    _box(ax, 7.4, 3.8, 2.7, 0.7, "Compiled wiki",
         sublabel="357 programs · 4,606 subjects · EN+ES",
         fill=BRAND_GREEN, fg="white", border=BRAND_DARK)

    # Stage 4: hybrid search inside one tool
    _box(ax, 7.4, 2.6, 2.7, 0.7, "Hybrid retrieval",
         sublabel="BM25-F  ⊕  Model2Vec (256-d)",
         fill=BRAND_ORANGE, fg="white", border=BRAND_DARK)

    # Stage 5: answer + citation
    _box(ax, 10.8, 2.8, 2.9, 1.6, "Answer + citation",
         sublabel='Grade in AI & Data\nScience [salleurl.edu]',
         fill=BRAND_PAPER, fg=INK, border=GRAY_DARK)

    # Connecting arrows
    _arrow(ax, 2.9, 3.6, 3.6, 3.6)
    _arrow(ax, 6.6, 3.8, 7.4, 4.1)
    _arrow(ax, 6.6, 3.4, 7.4, 2.9)
    _arrow(ax, 10.1, 4.1, 10.8, 3.7)
    _arrow(ax, 10.1, 2.9, 10.8, 3.3)

    # Bottom strip: design commitments
    ax.text(7, 1.8, "Design commitments", ha="center", fontsize=8,
            fontweight="bold", color=GRAY_DARK)
    commits = [
        ("Field-targeted", "extraction"),
        ("≤5 tool hops", "per turn"),
        ("Retrieval as one input", "to a hybrid ranker"),
        ("Observability-first", "runtime (3 collections)"),
    ]
    cw = 13 / len(commits)
    for i, (a, b) in enumerate(commits):
        cx = 0.5 + i * cw
        _box(ax, cx, 0.55, cw - 0.3, 0.95, a, sublabel=b,
             fill="white", fg=INK, border=BRAND_DARK, lw=0.6, rounding=0.04)

    fig.tight_layout()
    fig.savefig(OUT / "fig01_graphical_abstract.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig01_graphical_abstract.pdf")


# ─────────────────────────────────────────────────────────────────────────
# Figure 2 — System architecture (5-stage pipeline)
# ─────────────────────────────────────────────────────────────────────────


def fig_system_arch() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 3.2))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 5.5)
    ax.set_aspect("equal")
    ax.axis("off")

    stages = [
        ("Crawler", "polite resumable\nfetch_catalog.py", BRAND_BLUE),
        ("Wiki render", "build_wiki.py\nbuild_embeddings.py", BRAND_BLUE),
        ("Catalog API", "catalog_wiki_api\n10 read-only tools", BRAND_BLUE),
        ("Streaming\nagent", "Agno · GPT-5.4\nSSE over FastAPI", BRAND_BLUE),
        ("React 19\nclient", "Vite bundle served\nfrom FastAPI", BRAND_BLUE),
    ]
    w = 2.45
    gap = 0.27
    x = 0.3
    for label, sublabel, color in stages:
        _box(ax, x, 2.4, w, 1.6, label, sublabel=sublabel, fill=color, fg="white", border=BRAND_DARK)
        x += w + gap

    # Arrows between stages
    x = 0.3 + w
    for _ in range(4):
        _arrow(ax, x + 0.02, 3.2, x + gap - 0.02, 3.2, lw=1.2)
        x += w + gap

    # Mongo + observability strip
    _box(ax, 3.0, 0.4, 8.0, 1.2, "MongoDB",
         sublabel="wiki_tutor_agent_sessions · wiki_tutor_conversations_meta · wiki_tutor_turn_traces",
         fill=BRAND_GREEN, fg="white", border=BRAND_DARK, lw=0.8)

    # Down arrows from agent to Mongo
    _arrow(ax, 9.0, 2.4, 8.0, 1.6, style="<|-|>", lw=0.8)

    ax.text(7, 4.8, "System architecture (5 stages)", ha="center", fontsize=10,
            fontweight="bold", color=INK)

    fig.tight_layout()
    fig.savefig(OUT / "fig02_system_arch.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig02_system_arch.pdf")


# ─────────────────────────────────────────────────────────────────────────
# Figure 3 — Crawl-and-build pipeline (with politeness + fallback)
# ─────────────────────────────────────────────────────────────────────────


def fig_crawl_pipeline() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 3.0))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 5.2)
    ax.set_aspect("equal")
    ax.axis("off")

    _box(ax, 0.3, 2.5, 2.3, 1.4, "salleurl.edu",
         sublabel="Drupal · no\nsitemap (HTTP 500)",
         fill=BRAND_PAPER, fg=INK, border=GRAY_DARK)

    _box(ax, 3.0, 2.5, 2.5, 1.4, "Field-targeted\nextractors",
         sublabel="Drupal field-*\nselectors",
         fill=BRAND_BLUE, fg="white", border=BRAND_DARK)

    _box(ax, 6.0, 3.4, 2.5, 0.6, "structured.jsonl",
         fill=BRAND_GREEN, fg="white", border=BRAND_DARK)
    _box(ax, 6.0, 2.5, 2.5, 0.6, "pairings.jsonl",
         fill=BRAND_GREEN, fg="white", border=BRAND_DARK)

    _box(ax, 9.0, 2.5, 2.5, 1.4, "Cross-language\npairing",
         sublabel="greedy bipartite\nmulti-signal",
         fill=BRAND_ORANGE, fg="white", border=BRAND_DARK)

    _box(ax, 12.0, 2.5, 1.7, 1.4, "wiki/",
         sublabel="EN + ES\nmarkdown",
         fill=BRAND_DARK, fg="white", border=BRAND_DARK)

    # Arrows
    _arrow(ax, 2.6, 3.2, 3.0, 3.2, lw=1.2)
    _arrow(ax, 5.5, 3.4, 6.0, 3.7)
    _arrow(ax, 5.5, 2.9, 6.0, 2.8)
    _arrow(ax, 8.5, 3.2, 9.0, 3.2, lw=1.2)
    _arrow(ax, 11.5, 3.2, 12.0, 3.2, lw=1.2)

    # Annotations
    ax.text(1.45, 1.9, "Crawl-delay: 10s\nresumable, sha256", ha="center", fontsize=7, color=GRAY_DARK, fontstyle="italic")
    ax.text(4.25, 1.9, "fallback < 5%\n(measured 1.6%)", ha="center", fontsize=7, color=GRAY_DARK, fontstyle="italic")
    ax.text(10.25, 1.9, "57.5% link\ncoverage (EN→ES)", ha="center", fontsize=7, color=GRAY_DARK, fontstyle="italic")

    ax.text(7, 4.6, "Crawl-and-build pipeline", ha="center", fontsize=10, fontweight="bold", color=INK)

    fig.tight_layout()
    fig.savefig(OUT / "fig03_crawl_pipeline.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig03_crawl_pipeline.pdf")


# ─────────────────────────────────────────────────────────────────────────
# Figure 5 — Tool surface with two example call flows
# ─────────────────────────────────────────────────────────────────────────


def fig_tool_surface() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 4.4))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 9)
    ax.set_aspect("equal")
    ax.axis("off")

    tools = [
        ("search_programs", 1.6, 7.0, BRAND_BLUE),
        ("list_programs", 4.6, 7.0, BRAND_BLUE),
        ("get_index_facets", 7.6, 7.0, BRAND_BLUE),
        ("compare_programs", 10.6, 7.0, BRAND_BLUE),
        ("get_program", 1.6, 5.0, BRAND_BLUE),
        ("get_program_section", 4.6, 5.0, BRAND_BLUE),
        ("get_curriculum", 7.6, 5.0, BRAND_BLUE),
        ("get_subject", 10.6, 5.0, BRAND_BLUE),
        ("get_faq", 3.1, 3.0, BRAND_GREEN),
        ("get_glossary_entry", 8.1, 3.0, BRAND_GREEN),
    ]
    w = 2.6
    h = 0.85
    for name, x, y, c in tools:
        _box(ax, x, y, w, h, name, fill=c, fg="white", border=BRAND_DARK, lw=0.8, rounding=0.03)

    # Two example flows overlaid as colored arrows.
    # Flow 1 (comparison shopper, orange):
    #   search_programs → compare_programs → get_curriculum
    flow1 = [(1.6 + w / 2, 7.4), (10.6 + w / 2, 7.4), (7.6 + w / 2, 5.85)]
    for i in range(len(flow1) - 1):
        x1, y1 = flow1[i]
        x2, y2 = flow1[i + 1]
        _arrow(ax, x1, y1, x2, y2, color=BRAND_ORANGE, lw=1.6, style="-|>")

    # Flow 2 (explorer student, dark blue):
    #   get_index_facets → list_programs → get_program
    flow2 = [(7.6 + w / 2, 7.4), (4.6 + w / 2, 7.4), (1.6 + w / 2, 5.85)]
    for i in range(len(flow2) - 1):
        x1, y1 = flow2[i]
        x2, y2 = flow2[i + 1]
        _arrow(ax, x1, y1, x2, y2, color=BRAND_DARK, lw=1.6, style="-|>")

    # Legend
    ax.text(0.5, 1.6, "—", color=BRAND_ORANGE, fontsize=14, fontweight="bold")
    ax.text(1.2, 1.6, "comparison-shopper flow:  search → compare → get_curriculum",
            fontsize=8, color=INK, va="center")
    ax.text(0.5, 1.0, "—", color=BRAND_DARK, fontsize=14, fontweight="bold")
    ax.text(1.2, 1.0, "explorer flow:  facets → list → get_program",
            fontsize=8, color=INK, va="center")

    ax.text(7, 8.5, "Ten-tool surface with two example student flows",
            ha="center", fontsize=10, fontweight="bold", color=INK)
    ax.text(7, 8.05, "Solid blue = retrieval & detail tools. Green = FAQ / glossary routing tools.",
            ha="center", fontsize=7.5, color=GRAY_DARK, fontstyle="italic")

    fig.tight_layout()
    fig.savefig(OUT / "fig05_tool_surface.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig05_tool_surface.pdf")


# ─────────────────────────────────────────────────────────────────────────
# Figure 6 — Hybrid retrieval data flow inside search_programs
# ─────────────────────────────────────────────────────────────────────────


def fig_hybrid_retrieval() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7)
    ax.set_aspect("equal")
    ax.axis("off")

    _box(ax, 0.3, 3.2, 2.0, 1.0, "query",
         sublabel='"machine learning"',
         fill=BRAND_PAPER, fg=INK, border=GRAY_DARK)

    _box(ax, 2.8, 3.2, 2.0, 1.0, "synonym\nexpansion",
         sublabel="EN+ES synonyms",
         fill=BRAND_BLUE, fg="white", border=BRAND_DARK)

    # Upper branch: BM25-F
    _box(ax, 5.3, 4.6, 2.5, 1.0, "BM25-F",
         sublabel="6 fields, IDF\nk1=1.5  b=0.75",
         fill=BRAND_DARK, fg="white", border=BRAND_DARK)
    _box(ax, 8.3, 4.6, 2.0, 1.0, "pool-norm",
         sublabel="scaled to [0,1]\nin candidate pool",
         fill=BRAND_LIGHT, fg=INK, border=BRAND_DARK)

    # Lower branch: semantic
    _box(ax, 5.3, 1.6, 2.5, 1.0, "Model2Vec",
         sublabel="potion-base-8M\n256-d static",
         fill=BRAND_GREEN, fg="white", border=BRAND_DARK)
    _box(ax, 8.3, 1.6, 2.0, 1.0, "pool-norm",
         sublabel="cosine\nscaled to [0,1]",
         fill=BRAND_LIGHT, fg=INK, border=BRAND_DARK)

    # Blend
    _box(ax, 10.8, 3.2, 1.7, 1.0, "blend",
         sublabel="0.55 · L\n+ 0.45 · S",
         fill=BRAND_ORANGE, fg="white", border=BRAND_DARK)

    # Intent prior
    _box(ax, 12.7, 3.2, 1.1, 1.0, "intent\nprior",
         fill=BRAND_BLUE, fg="white", border=BRAND_DARK)

    # Arrows
    _arrow(ax, 2.3, 3.7, 2.8, 3.7, lw=1.0)
    _arrow(ax, 4.8, 3.9, 5.3, 5.0, lw=1.0)
    _arrow(ax, 4.8, 3.5, 5.3, 2.1, lw=1.0)
    _arrow(ax, 7.8, 5.1, 8.3, 5.1, lw=1.0)
    _arrow(ax, 7.8, 2.1, 8.3, 2.1, lw=1.0)
    _arrow(ax, 10.3, 5.0, 10.8, 4.0, lw=1.0)
    _arrow(ax, 10.3, 2.2, 10.8, 3.4, lw=1.0)
    _arrow(ax, 12.5, 3.7, 12.7, 3.7, lw=1.0)

    # Labels for the two branches
    ax.text(6.55, 6.0, "Lexical branch", ha="center", fontsize=8.5,
            fontweight="bold", color=BRAND_DARK)
    ax.text(6.55, 0.95, "Semantic branch", ha="center", fontsize=8.5,
            fontweight="bold", color=BRAND_DARK)

    ax.text(7, 6.6, "Hybrid retrieval inside search_programs",
            ha="center", fontsize=10, fontweight="bold", color=INK)

    fig.tight_layout()
    fig.savefig(OUT / "fig06_hybrid_retrieval.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig06_hybrid_retrieval.pdf")


# ─────────────────────────────────────────────────────────────────────────
# Figure 7 — SSE event lifecycle + Mongo collections
# ─────────────────────────────────────────────────────────────────────────


def fig_sse_lifecycle() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7)
    ax.set_aspect("equal")
    ax.axis("off")

    # Agent runtime column (left)
    _box(ax, 0.3, 4.5, 2.6, 1.6, "Streaming agent",
         sublabel="Agno · GPT-5.4\nResponses API",
         fill=BRAND_BLUE, fg="white", border=BRAND_DARK)

    # SSE adapter (center)
    _box(ax, 3.6, 4.5, 2.6, 1.6, "BaseSSEAdapter",
         sublabel="AgentEvent → wire",
         fill=BRAND_BLUE, fg="white", border=BRAND_DARK)

    # SSE wire (right)
    _box(ax, 6.9, 4.5, 2.6, 1.6, "SSE wire",
         sublabel="session.started\nthinking.* · tool.*\nfinal_response.*",
         fill=BRAND_PAPER, fg=INK, border=GRAY_DARK)

    # React client (far right)
    _box(ax, 10.2, 4.5, 2.6, 1.6, "React client",
         sublabel="Turn[] reducer\nlive timeline",
         fill=BRAND_DARK, fg="white", border=BRAND_DARK)

    # Trace recorder (parallel listener — below adapter)
    _box(ax, 3.6, 1.6, 2.6, 1.4, "TurnTraceRecorder",
         sublabel="parallel listener",
         fill=BRAND_ORANGE, fg="white", border=BRAND_DARK)

    # Mongo collections (bottom right)
    _box(ax, 7.5, 0.4, 6.2, 0.9, "MongoDB",
         sublabel="agent_sessions  ·  conversations_meta  ·  turn_traces",
         fill=BRAND_GREEN, fg="white", border=BRAND_DARK)

    # Arrows
    _arrow(ax, 2.9, 5.3, 3.6, 5.3, lw=1.2)
    _arrow(ax, 6.2, 5.3, 6.9, 5.3, lw=1.2)
    _arrow(ax, 9.5, 5.3, 10.2, 5.3, lw=1.2)
    _arrow(ax, 4.9, 4.5, 4.9, 3.0, lw=0.8)
    _arrow(ax, 6.2, 2.0, 7.5, 1.0, lw=0.8)
    _arrow(ax, 1.6, 4.5, 7.5, 1.0, color=BRAND_GREEN, lw=0.6, style="-|>")

    ax.text(7, 6.6, "SSE event lifecycle and observability fan-out",
            ha="center", fontsize=10, fontweight="bold", color=INK)

    fig.tight_layout()
    fig.savefig(OUT / "fig07_sse_lifecycle.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig07_sse_lifecycle.pdf")


# ─────────────────────────────────────────────────────────────────────────
# Figure 8 — Deployment topology
# ─────────────────────────────────────────────────────────────────────────


def fig_deployment() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 7)
    ax.set_aspect("equal")
    ax.axis("off")

    # VPC outline
    vpc = FancyBboxPatch((1.0, 0.4), 12.0, 5.6,
                         boxstyle="round,pad=0.05,rounding_size=0.15",
                         linewidth=0.8, edgecolor=GRAY_DARK,
                         facecolor=BRAND_PAPER, linestyle=(0, (4, 2)))
    ax.add_patch(vpc)
    ax.text(1.4, 5.65, "AWS  ·  eu-west-1  ·  default VPC, public subnet",
            fontsize=8, color=GRAY_DARK, fontstyle="italic")

    # EC2 instance (the box on the box)
    ec2 = FancyBboxPatch((2.0, 1.2), 7.5, 3.6,
                         boxstyle="round,pad=0.04,rounding_size=0.12",
                         linewidth=1.0, edgecolor=BRAND_DARK,
                         facecolor=BRAND_LIGHT)
    ax.add_patch(ec2)
    ax.text(2.3, 4.45, "EC2 t3.micro · Ubuntu 24.04",
            fontsize=9, fontweight="bold", color=BRAND_DARK)

    _box(ax, 2.4, 3.0, 2.4, 1.2, "Caddy",
         sublabel="Let's Encrypt\nTLS · :80 :443",
         fill=BRAND_BLUE, fg="white", border=BRAND_DARK)
    _box(ax, 5.0, 3.0, 2.0, 1.2, "uvicorn",
         sublabel="FastAPI\nsystemd",
         fill=BRAND_BLUE, fg="white", border=BRAND_DARK)
    _box(ax, 7.2, 3.0, 2.0, 1.2, "Mongo",
         sublabel="docker\ncompose",
         fill=BRAND_GREEN, fg="white", border=BRAND_DARK)
    _box(ax, 2.4, 1.5, 6.8, 0.9, "Elastic IP · DLM daily snapshots · IMDSv2 required",
         fill=BRAND_DARK, fg="white", border=BRAND_DARK)

    # Caddy → uvicorn → Mongo
    _arrow(ax, 4.8, 3.6, 5.0, 3.6, lw=1.2)
    _arrow(ax, 7.0, 3.6, 7.2, 3.6, lw=1.2)

    # SSM access (right side)
    _box(ax, 10.5, 3.5, 2.4, 1.2, "SSM Session\nManager",
         sublabel="no SSH, no\nport 22",
         fill=BRAND_ORANGE, fg="white", border=BRAND_DARK)
    _arrow(ax, 10.5, 4.1, 9.5, 4.1, lw=1.0, color=BRAND_ORANGE)

    # Terraform (bottom right)
    _box(ax, 10.5, 1.5, 2.4, 1.0, "Terraform",
         sublabel="provisions all of\nthe above",
         fill=BRAND_BLUE, fg="white", border=BRAND_DARK)

    ax.text(7, 6.6, "Deployment topology (~$14/mo)",
            ha="center", fontsize=10, fontweight="bold", color=INK)

    fig.tight_layout()
    fig.savefig(OUT / "fig08_deployment.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig08_deployment.pdf")


# ─────────────────────────────────────────────────────────────────────────
# Figure 4 — Wiki on-disk layout
# ─────────────────────────────────────────────────────────────────────────


def fig_wiki_layout() -> None:
    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 8.5)
    ax.set_aspect("equal")
    ax.axis("off")

    # Tree on the left, schema on the right
    tree = [
        (0.5, "wiki/", "bold"),
        (1.0, "├── INDEX.md, README.md, faq.md, glossary.md", "normal"),
        (1.0, "├── meta/", "bold"),
        (1.5, "│   ├── catalog.jsonl       (357 program frontmatter dumps)", "normal"),
        (1.5, "│   ├── subjects.jsonl      (4,606 subject records)", "normal"),
        (1.5, "│   ├── pairings.jsonl      (EN↔ES pair candidates)", "normal"),
        (1.5, "│   ├── embeddings_en.npz   (Model2Vec, 256-d)", "normal"),
        (1.5, "│   └── embeddings_es.npz", "normal"),
        (1.0, "├── en/", "bold"),
        (1.5, "│   ├── INDEX.md, by-area/*.md, by-level/*.md", "normal"),
        (1.5, "│   ├── programs/{slug}/", "bold"),
        (2.0, "│   │   ├── README.md       (YAML frontmatter + overview)", "normal"),
        (2.0, "│   │   ├── goals.md, requirements.md, careers.md", "normal"),
        (2.0, "│   │   └── curriculum.md, methodology.md, faculty.md", "normal"),
        (1.5, "│   └── subjects/{slug}.md  (one per course)", "normal"),
        (1.0, "└── es/   (mirrors en/ with /estudios/ slugs)", "bold"),
    ]
    y = 7.6
    for indent, line, weight in tree:
        ax.text(indent * 0.35 + 0.2, y, line, fontsize=7.5,
                fontfamily="monospace", color=INK,
                fontweight=("bold" if weight == "bold" else "normal"))
        y -= 0.4

    # Frontmatter schema (right side)
    schema_box = FancyBboxPatch((8.0, 1.0), 5.8, 6.0,
                                boxstyle="round,pad=0.05,rounding_size=0.12",
                                linewidth=0.8, edgecolor=BRAND_DARK,
                                facecolor=BRAND_LIGHT)
    ax.add_patch(schema_box)
    ax.text(10.9, 6.5, "Program frontmatter schema",
            ha="center", fontsize=9, fontweight="bold", color=BRAND_DARK)

    fields = [
        "title, slug, canonical_program_id",
        "level, area, official, tags",
        "modality (array), duration, ects",
        "languages_of_instruction (array)",
        "schedule, location, start_date",
        "tuition_status, admissions_contact",
        "official_name, degree_issuer",
        "subject_count, related_programs",
        "equivalent_program_id, pairing_confidence",
        "source_url, source_fetched_at",
        "extractor_version, extractor_mode, last_built_at",
    ]
    y = 6.0
    for f in fields:
        ax.text(8.2, y, "• " + f, fontsize=7.5, fontfamily="monospace", color=INK)
        y -= 0.4

    ax.text(7, 8.1, "Wiki on-disk layout and frontmatter schema",
            ha="center", fontsize=10, fontweight="bold", color=INK)

    fig.tight_layout()
    fig.savefig(OUT / "fig04_wiki_layout.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig04_wiki_layout.pdf")


# ─────────────────────────────────────────────────────────────────────────
# Driver
# ─────────────────────────────────────────────────────────────────────────


def main() -> None:
    print("Generating schematics ...")
    fig_graphical_abstract()
    fig_system_arch()
    fig_crawl_pipeline()
    fig_wiki_layout()
    fig_tool_surface()
    fig_hybrid_retrieval()
    fig_sse_lifecycle()
    fig_deployment()
    print(f"\nAll schematics saved to {OUT}")


if __name__ == "__main__":
    main()
