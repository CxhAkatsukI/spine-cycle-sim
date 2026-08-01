#!/usr/bin/env python3
"""Render setup-inclusive persistent-update throughput figures."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/persistent_update_campaign_20260731"
DATA_DIR = ROOT / "docs/paper/data"
FIGURE_DIR = ROOT / "docs/figures"
FIGURE_BASE = FIGURE_DIR / "persistent_update_setup_inclusive"

CROSS_DATASETS = (
    ("au", "AU"),
    ("su", "SU"),
    ("wk", "WK"),
    ("so", "SO"),
    ("pk", "PK"),
)
BATCH_CASES = (1000, 100, 10)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _system_rows(comparison: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = comparison["rows"]
    if not isinstance(rows, list):
        raise ValueError(f"invalid comparison row shape in {comparison}")
    by_system = {row["system"]: row for row in rows}
    return by_system["spine"], by_system["grasu_regraph"]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _kups(row: dict[str, Any]) -> float:
    return float(row["modeled_host_inclusive_updates_per_second"]) / 1_000.0


def load_cross_dataset_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, label in CROSS_DATASETS:
        comparison = _load_json(EVIDENCE / "cross_dataset" / key / "comparison.json")
        spine, grasu = _system_rows(comparison)
        rows.append(
            {
                "dataset": label,
                "logical_updates": int(comparison["logical_updates"]),
                "batch_count": int(comparison["batch_count"]),
                "spine_kups": _kups(spine),
                "grasu_kups": _kups(grasu),
                "spine_speedup": float(
                    comparison["spine_speedup"]["modeled_host_inclusive"]
                ),
            }
        )
    return rows


def load_batch_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch_count in BATCH_CASES:
        comparison = _load_json(
            EVIDENCE
            / "batch_sensitivity"
            / f"b{batch_count}"
            / "comparison.json"
        )
        spine, grasu = _system_rows(comparison)
        logical_updates = int(comparison["logical_updates"])
        rows.append(
            {
                "batch_count": batch_count,
                "updates_per_batch": logical_updates / batch_count,
                "logical_updates": logical_updates,
                "spine_kups": _kups(spine),
                "grasu_kups": _kups(grasu),
                "spine_speedup": float(
                    comparison["spine_speedup"]["modeled_host_inclusive"]
                ),
            }
        )
    return rows


def configure_matplotlib() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "monospace",
            "font.monospace": ["DejaVu Sans Mono", "Liberation Mono", "monospace"],
            "font.size": 7.2,
            "axes.labelsize": 7.4,
            "axes.titlesize": 7.6,
            "axes.linewidth": 0.75,
            "legend.fontsize": 6.7,
            "xtick.labelsize": 6.8,
            "ytick.labelsize": 6.8,
            "hatch.linewidth": 0.35,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    return plt


def style_axis(axis: Any, *, grid_axis: str = "y") -> None:
    axis.tick_params(direction="in", top=False, right=True, length=3.0, width=0.75)
    axis.grid(axis=grid_axis, linestyle="--", color="0.72", alpha=0.55, zorder=0)
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.75)


def compact_number(value: float) -> str:
    if value >= 10_000:
        return f"{value / 1000:.0f}K"
    if value >= 1000:
        return f"{value / 1000:.1f}K"
    return f"{value:.0f}"


def render(cross_rows: list[dict[str, Any]], batch_rows: list[dict[str, Any]]) -> None:
    plt = configure_matplotlib()
    import numpy as np
    from matplotlib.ticker import FuncFormatter

    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(1, 2, figsize=(3.55, 1.95))

    spine_color = "#2f86bd"
    grasu_color = "#c5652d"
    spine_fill = "#d7eaf4"
    grasu_fill = "#f3d8c6"

    labels = [row["dataset"] for row in cross_rows]
    x = np.arange(len(labels))
    width = 0.34
    axes[0].bar(
        x - width / 2,
        [row["spine_kups"] for row in cross_rows],
        width,
        label="Spine",
        color=spine_fill,
        edgecolor=spine_color,
        linewidth=0.75,
        hatch="////",
        zorder=3,
    )
    axes[0].bar(
        x + width / 2,
        [row["grasu_kups"] for row in cross_rows],
        width,
        label="G+R",
        color=grasu_fill,
        edgecolor=grasu_color,
        linewidth=0.75,
        hatch="\\\\\\\\",
        zorder=3,
    )
    axes[0].set_yscale("log")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels)
    axes[0].set_ylabel("K updates/s")
    axes[0].set_title("(a) 10 batches")
    axes[0].set_ylim(0.02, 10.0)
    axes[0].yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    style_axis(axes[0])

    sorted_batch = sorted(batch_rows, key=lambda row: row["updates_per_batch"])
    updates_per_batch = [row["updates_per_batch"] for row in sorted_batch]
    axes[1].plot(
        updates_per_batch,
        [row["spine_kups"] for row in sorted_batch],
        color=spine_color,
        marker="s",
        markersize=3.2,
        markerfacecolor="white",
        markeredgewidth=0.75,
        linewidth=0.95,
        label="Spine",
        zorder=3,
    )
    axes[1].plot(
        updates_per_batch,
        [row["grasu_kups"] for row in sorted_batch],
        color=grasu_color,
        marker="o",
        markersize=3.2,
        markerfacecolor="white",
        markeredgewidth=0.75,
        linewidth=0.95,
        label="G+R",
        zorder=3,
    )
    axes[1].set_xscale("log")
    axes[1].set_xticks(updates_per_batch)
    axes[1].set_xticklabels([compact_number(value) for value in updates_per_batch])
    axes[1].set_ylim(70, 165)
    axes[1].set_xlabel("updates/batch")
    axes[1].set_title("(b) fixed 131K updates")
    style_axis(axes[1])

    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.55, 1.04),
        ncol=2,
        frameon=False,
        handlelength=1.5,
        columnspacing=1.0,
    )
    figure.subplots_adjust(left=0.14, right=0.995, bottom=0.22, top=0.80, wspace=0.36)
    figure.savefig(FIGURE_BASE.with_suffix(".pdf"), bbox_inches="tight")
    figure.savefig(FIGURE_BASE.with_suffix(".svg"), bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    cross_rows = load_cross_dataset_rows()
    batch_rows = load_batch_rows()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _write_csv(DATA_DIR / "persistent_update_setup_cross_dataset.csv", cross_rows)
    _write_csv(DATA_DIR / "persistent_update_setup_batch_sensitivity.csv", batch_rows)
    render(cross_rows, batch_rows)


if __name__ == "__main__":
    main()
