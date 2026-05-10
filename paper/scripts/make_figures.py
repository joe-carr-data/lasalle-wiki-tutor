#!/usr/bin/env python3
"""Generate every data-plot figure in the paper from the saved
paper/data/*.json files. Schematics (architecture, tool surface, etc.)
are not produced here — they live in Typst source as embedded vector
graphics so they stay editable.

Outputs PDFs into paper/figures/.

Usage:
    uv run python paper/scripts/make_figures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

# Publication-friendly defaults
mpl.rcParams.update({
    "font.family": "serif",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linestyle": "-",
    "grid.linewidth": 0.4,
})

DATA = Path("paper/data")
OUT = Path("paper/figures")
OUT.mkdir(parents=True, exist_ok=True)

# Consistent palette: LaSalle brand blue (sky-blue), an orange accent, a
# muted green, a warm gray.
BRAND_BLUE = "#5BA8DA"
BRAND_DARK = "#205C87"
BRAND_ORANGE = "#E89E48"
BRAND_GREEN = "#7CB07C"
GRAY = "#9CA3AF"
GRAY_DARK = "#4B5563"


# ──────────────────────────────────────────────────────────────────────────
# Figure 9 — Corpus coverage: areas + frontmatter completeness
# ──────────────────────────────────────────────────────────────────────────


def fig_corpus_coverage() -> None:
    data = json.loads((DATA / "corpus_coverage.json").read_text())

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 3.6), gridspec_kw={"width_ratios": [1.05, 1.0]})

    # Panel A: area distribution (EN), sorted by count
    areas_en = data["areas_en"]
    items = sorted(areas_en.items(), key=lambda x: -x[1])
    names = [k.replace("-", " ").replace("_", " ") for k, _ in items]
    counts = [v for _, v in items]
    ypos = np.arange(len(names))
    ax1.barh(ypos, counts, color=BRAND_BLUE, edgecolor=BRAND_DARK, linewidth=0.6)
    ax1.set_yticks(ypos)
    ax1.set_yticklabels(names)
    ax1.invert_yaxis()
    ax1.set_xlabel("Number of EN programs")
    ax1.set_title("(a) Programs by subject area (EN catalog)")
    for y, c in zip(ypos, counts):
        ax1.text(c + 0.3, y, str(c), va="center", fontsize=8)
    ax1.grid(False, axis="y")

    # Panel B: frontmatter completeness, sorted ascending so the gaps are visible
    fc = data["frontmatter_completeness_pct"]
    # Exclude the always-100% fields (clutter) — keep the bottom 12 most
    # interesting + ECTS for the contrast story
    interesting = sorted(fc.items(), key=lambda x: x[1])[:12]
    names = [k.replace("_", " ") for k, _ in interesting]
    pcts = [v for _, v in interesting]
    ypos = np.arange(len(names))
    colors = [BRAND_GREEN if p >= 95 else BRAND_BLUE if p >= 70 else BRAND_ORANGE for p in pcts]
    ax2.barh(ypos, pcts, color=colors, edgecolor=BRAND_DARK, linewidth=0.6)
    ax2.set_yticks(ypos)
    ax2.set_yticklabels(names)
    ax2.invert_yaxis()
    ax2.set_xlim(0, 105)
    ax2.set_xlabel("Frontmatter completeness (%)")
    ax2.set_title("(b) Lowest-completeness fields")
    for y, p in zip(ypos, pcts):
        ax2.text(p + 1, y, f"{p:.0f}%", va="center", fontsize=8)
    ax2.grid(False, axis="y")

    fig.tight_layout()
    fig.savefig(OUT / "fig09_corpus_coverage.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig09_corpus_coverage.pdf")


# ──────────────────────────────────────────────────────────────────────────
# Figure 10 — Ranker-mode ablation
# ──────────────────────────────────────────────────────────────────────────


def fig_ablation() -> None:
    data = json.loads((DATA / "ablation_results.json").read_text())
    modes = ["hybrid", "lexical", "semantic", "token_overlap"]
    metrics = ["top1_rate", "top3_rate", "top5_rate"]
    labels = ["top-1", "top-3", "top-5"]

    rows = np.array([[data["modes"][m]["summary"][k] for k in metrics] for m in modes])

    fig, ax = plt.subplots(figsize=(6.0, 3.2))
    x = np.arange(len(modes))
    width = 0.27
    for i, (m, lbl) in enumerate(zip(metrics, labels)):
        ax.bar(
            x + (i - 1) * width,
            rows[:, i],
            width,
            label=lbl,
            color=[BRAND_DARK, BRAND_BLUE, BRAND_GREEN][i],
            edgecolor="white",
            linewidth=0.5,
        )
        for j, v in enumerate(rows[:, i]):
            ax.text(x[j] + (i - 1) * width, v + 1.5, f"{v:.0f}", ha="center", fontsize=7)

    pretty = {"hybrid": "Hybrid (0.55L + 0.45S)", "lexical": "Lexical (BM25-F)", "semantic": "Semantic (Model2Vec)", "token_overlap": "Token-overlap"}
    ax.set_xticks(x)
    ax.set_xticklabels([pretty[m] for m in modes], fontsize=8)
    ax.set_ylabel("Hit rate (%)")
    ax.set_ylim(0, 110)
    ax.set_title("Retrieval ablation across ranker modes (n=20 queries)")
    ax.legend(loc="lower left", frameon=False, ncol=3)
    ax.grid(True, axis="y", alpha=0.25)
    ax.grid(False, axis="x")

    fig.tight_layout()
    fig.savefig(OUT / "fig10_ablation.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig10_ablation.pdf")


# ──────────────────────────────────────────────────────────────────────────
# Figure 11 — Per-tool latency (production traces)
# ──────────────────────────────────────────────────────────────────────────


def fig_latency() -> None:
    data = json.loads((DATA / "latency_raw.json").read_text())
    per_tool = data["per_tool"]
    # Drop tools with n<2 to avoid degenerate "boxes"
    items = sorted(((k, v) for k, v in per_tool.items() if v["count"] >= 2),
                   key=lambda x: -x[1]["median_ms"])
    names = [k for k, _ in items]
    samples = [v["samples"] for _, v in items]
    counts = [v["count"] for _, v in items]

    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    bp = ax.boxplot(
        samples,
        vert=False,
        patch_artist=True,
        widths=0.55,
        showfliers=True,
        flierprops=dict(marker="o", markersize=3, markerfacecolor=GRAY, markeredgecolor=GRAY),
        medianprops=dict(color=BRAND_DARK, linewidth=1.5),
        boxprops=dict(facecolor=BRAND_BLUE, edgecolor=BRAND_DARK, linewidth=0.7),
        whiskerprops=dict(color=BRAND_DARK, linewidth=0.7),
        capprops=dict(color=BRAND_DARK, linewidth=0.7),
    )
    ax.set_yticks(np.arange(1, len(names) + 1))
    ax.set_yticklabels([f"{n}  (n={c})" for n, c in zip(names, counts)], fontsize=8)
    ax.set_xscale("log")
    ax.set_xlabel("Duration (ms, log scale)")
    ax.set_title("Per-tool latency on the live deployment")
    ax.grid(True, axis="x", which="both", alpha=0.25)
    ax.grid(False, axis="y")

    fig.tight_layout()
    fig.savefig(OUT / "fig11_latency.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig11_latency.pdf")


# ──────────────────────────────────────────────────────────────────────────
# Figure 12 — Cost per turn / conversation (donut + histogram)
# ──────────────────────────────────────────────────────────────────────────


def fig_cost() -> None:
    data = json.loads((DATA / "cost_raw.json").read_text())
    s_turn = data["per_turn_cost_usd_summary"]
    s_conv = data["per_conversation_cost_usd_summary"]

    fig, ax = plt.subplots(figsize=(6.0, 3.0))
    metrics = ["min", "median", "p95", "max"]
    turn_vals = [s_turn[m] for m in metrics]
    conv_vals = [s_conv[m] for m in metrics]

    x = np.arange(len(metrics))
    width = 0.36
    ax.bar(x - width / 2, turn_vals, width, label="Per turn", color=BRAND_BLUE, edgecolor=BRAND_DARK, linewidth=0.6)
    ax.bar(x + width / 2, conv_vals, width, label="Per conversation", color=BRAND_ORANGE, edgecolor=BRAND_DARK, linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels([m if m != "p95" else "p95" for m in metrics])
    ax.set_ylabel("Cost (USD)")
    ax.set_title(f"Cost per turn and per conversation (n={data['turns_total']} turns, n={data['conversations_total']} convos)")
    for i, v in enumerate(turn_vals):
        ax.text(i - width / 2, v + 0.002, f"${v:.4f}", ha="center", fontsize=7)
    for i, v in enumerate(conv_vals):
        ax.text(i + width / 2, v + 0.002, f"${v:.4f}", ha="center", fontsize=7)
    ax.legend(frameon=False, loc="upper left")
    ax.grid(True, axis="y", alpha=0.25)
    ax.grid(False, axis="x")
    ax.set_ylim(0, max(max(turn_vals), max(conv_vals)) * 1.18)

    fig.tight_layout()
    fig.savefig(OUT / "fig12_cost.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig12_cost.pdf")


# ──────────────────────────────────────────────────────────────────────────
# Figure 13 — Pairing decomposition: which OR-rule caught each pair
# ──────────────────────────────────────────────────────────────────────────


def fig_pairing() -> None:
    data = json.loads((DATA / "corpus_coverage.json").read_text())
    rules = data["pairing"]["auto_link_rule_breakdown"]
    bands = data["pairing"]["auto_link_score_bands"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 3.0))

    # Panel A: which OR-rule fired
    items = sorted(rules.items(), key=lambda x: -x[1])
    labels = [k for k, _ in items]
    sizes = [v for _, v in items]
    colors = [BRAND_BLUE, BRAND_DARK, BRAND_ORANGE, BRAND_GREEN, GRAY][:len(sizes)]
    wedges, texts, autotexts = ax1.pie(
        sizes,
        labels=labels,
        colors=colors,
        autopct=lambda p: f"{p:.0f}%\n(n={int(round(p * sum(sizes) / 100))})",
        startangle=90,
        wedgeprops=dict(edgecolor="white", linewidth=1.5),
        textprops=dict(fontsize=7),
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontweight("bold")
    ax1.set_title(f"(a) Auto-link rule that fired (n={sum(sizes)} pairs)")

    # Panel B: score-band distribution among auto-linked
    band_order = ["high (≥0.70)", "mid (0.50–0.70)", "low (0.30–0.50)", "very-low (<0.30)"]
    band_vals = [bands.get(b, 0) for b in band_order]
    band_colors = [BRAND_GREEN, BRAND_BLUE, BRAND_ORANGE, GRAY]
    band_labels = ["≥0.70", "0.50–0.70", "0.30–0.50", "<0.30"]
    ypos = np.arange(len(band_order))
    ax2.barh(ypos, band_vals, color=band_colors, edgecolor=BRAND_DARK, linewidth=0.6)
    ax2.set_yticks(ypos)
    ax2.set_yticklabels(band_labels)
    ax2.invert_yaxis()
    ax2.set_xlabel("Number of auto-linked pairs")
    ax2.set_title("(b) Score band distribution")
    for y, v in zip(ypos, band_vals):
        ax2.text(v + 0.5, y, str(v), va="center", fontsize=8)
    ax2.grid(False, axis="y")

    fig.tight_layout()
    fig.savefig(OUT / "fig13_pairing.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig13_pairing.pdf")


# ──────────────────────────────────────────────────────────────────────────
# Figure 14 — Level breakdown: unlinked vs linked
# ──────────────────────────────────────────────────────────────────────────


def fig_unlinked_breakdown() -> None:
    data = json.loads((DATA / "corpus_coverage.json").read_text())
    breakdown = data["pairing"]["unlinked_breakdown_by_level"]
    order = ["bachelor", "master", "specialization", "online", "doctorate", "summer", "other"]
    breakdown = {k: breakdown[k] for k in order if k in breakdown}

    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    names = list(breakdown.keys())
    linked = [breakdown[k]["total"] - breakdown[k]["unlinked"] for k in names]
    unlinked = [breakdown[k]["unlinked"] for k in names]
    x = np.arange(len(names))

    ax.bar(x, linked, label="Linked", color=BRAND_BLUE, edgecolor=BRAND_DARK, linewidth=0.6)
    ax.bar(x, unlinked, bottom=linked, label="Unlinked", color=BRAND_ORANGE, edgecolor=BRAND_DARK, linewidth=0.6)

    for i, k in enumerate(names):
        total = breakdown[k]["total"]
        pct = breakdown[k]["pct_unlinked"]
        ax.text(i, total + 1.5, f"{pct:.0f}% u/l", ha="center", fontsize=7, color=GRAY_DARK)

    ax.set_xticks(x)
    ax.set_xticklabels(names, fontsize=8)
    ax.set_ylabel("Number of EN programs")
    ax.set_title("Linked vs. unlinked EN programs by level")
    ax.legend(frameon=False, loc="upper right")
    ax.grid(True, axis="y", alpha=0.25)
    ax.grid(False, axis="x")
    ax.set_ylim(0, max(breakdown[k]["total"] for k in names) * 1.25)

    fig.tight_layout()
    fig.savefig(OUT / "fig14_unlinked_breakdown.pdf", bbox_inches="tight")
    plt.close(fig)
    print("  fig14_unlinked_breakdown.pdf")


# ──────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────


def main() -> None:
    print("Generating data plots ...")
    fig_corpus_coverage()
    fig_ablation()
    fig_latency()
    fig_cost()
    fig_pairing()
    fig_unlinked_breakdown()
    print(f"\nAll figures saved to {OUT}")


if __name__ == "__main__":
    main()
