#!/usr/bin/env python3
"""Validate frozen evidence and render the complete Figure 7--10 handoff."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PROVENANCE = ROOT / "provenance"
FIGURES = ROOT / "figures"
REFERENCE = ROOT / "reference" / "GraphyFlow_Plot.zip"

TXTT_PREAMBLE = (
    r"\usepackage{txfonts}"
    r"\renewcommand{\rmdefault}{txtt}"
    r"\renewcommand{\sfdefault}{txtt}"
    r"\renewcommand{\ttdefault}{txtt}"
    r"\renewcommand{\familydefault}{\ttdefault}"
)
DATASET_ORDER = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")
ALGORITHM_ORDER = ("weighted_sssp", "connected_components", "residual_pagerank")
ALGORITHM_LABEL = {
    "weighted_sssp": "Weighted SSSP",
    "connected_components": "Connected Components",
    "residual_pagerank": "Residual PageRank",
    "full_pagerank": "Full PageRank, compact FPGA",
}
FIG9_ALGORITHM_ORDER = (
    "weighted_sssp",
    "connected_components",
    "thresholded_residual_pagerank",
)
FIG9_ALGORITHM_LABEL = {
    "weighted_sssp": "SSSP",
    "connected_components": "CC",
    "thresholded_residual_pagerank": "ResPR",
}
FIG10_GROUP_ORDER = (
    "Zero-net",
    "Shallow insert",
    "Deep carry",
    "PR correction",
    "Deletion fallback",
)
FIG10_TICKS = {
    "Zero-net": ("Syn",),
    "Shallow insert": ("AU", "SU", "WK"),
    "Deep carry": ("L1", "L3", "L5"),
    "PR correction": ("FL", "SU", "WK"),
    "Deletion fallback": ("Syn",),
}
FIG10_STAGES = (
    ("maintenance_percent", "Maint.", "#A8CF88", "xxxxxxxx"),
    ("seed_publication_percent", "Seed/pub.", "#F1A55B", "||||||||"),
    ("resolve_percent", "Resolve", "#2F86BD", "////////"),
    ("application_percent", "App", "#B7D6E8", "\\\\\\\\\\\\\\\\"),
    ("drain_sync_percent", "Drain", "#35A936", "xxxxxxxx"),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="ascii", newline="") as source:
        return list(csv.DictReader(source))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_inputs() -> dict[str, list[dict[str, str]]]:
    paths = {
        "fig7": DATA / "fig7_fpga_speedup.csv",
        "fig8_cross": DATA / "fig8_update_cross_dataset.csv",
        "fig8_batch": DATA / "fig8_update_batch_sensitivity.csv",
        "fig9": DATA / "fig9_memory_energy_rows.csv",
        "fig10": DATA / "fig10_normalized_breakdown_rows.csv",
    }
    rows = {key: read_csv(path) for key, path in paths.items()}
    provenance = {
        key: read_json(PROVENANCE / f"{key}.json")
        for key in ("fig7", "fig8", "fig9", "fig10")
    }

    require(provenance["fig7"].get("status") == "PASS", "Figure 7 is not admitted")
    require(
        provenance["fig7"].get("data_csv_sha256") == sha256(paths["fig7"]),
        "Figure 7 data hash mismatch",
    )
    expected_fig7 = {
        (algorithm, dataset)
        for algorithm in ALGORITHM_ORDER
        for dataset in DATASET_ORDER
    } | {
        ("full_pagerank", dataset) for dataset in ("AM", "WG", "FL")
    }
    observed_fig7 = {(row["algorithm"], row["dataset"]) for row in rows["fig7"]}
    require(observed_fig7 == expected_fig7, "Figure 7 algorithm/dataset coverage mismatch")
    require(
        all(row["timing_window"] == "setup_inclusive_dynamic_latency" for row in rows["fig7"]),
        "Figure 7 mixes timing windows",
    )

    fig8_manifest = provenance["fig8"]
    require(fig8_manifest.get("status") == "PASS_CURRENT_MODEL_DATA", "Figure 8 is not admitted")
    require(
        fig8_manifest.get("metric") == "setup_inclusive_update_only_throughput",
        "Figure 8 metric mismatch",
    )
    fig8_hashes = fig8_manifest.get("output_files", {})
    require(
        fig8_hashes.get("persistent_update_setup_cross_dataset.csv")
        == sha256(paths["fig8_cross"]),
        "Figure 8 cross-dataset hash mismatch",
    )
    require(
        fig8_hashes.get("persistent_update_setup_batch_sensitivity.csv")
        == sha256(paths["fig8_batch"]),
        "Figure 8 batch-sweep hash mismatch",
    )
    require([row["dataset"] for row in rows["fig8_cross"]] == ["AU", "SU", "WK", "SO", "PK"], "Figure 8 dataset order mismatch")
    require([int(float(row["updates_per_batch"])) for row in rows["fig8_batch"]] == [64, 512, 4096], "Figure 8 batch coverage mismatch")

    fig9_manifest = provenance["fig9"]
    require(fig9_manifest.get("status") == "PASS_CURRENT_MODEL_DATA", "Figure 9 is not admitted")
    require(fig9_manifest.get("rows") == 9 and fig9_manifest.get("missing") == [], "Figure 9 evidence is incomplete")
    require(
        fig9_manifest.get("metric") == "accepted_backend_bytes_and_bound_channel_dramsim3_energy",
        "Figure 9 metric mismatch",
    )
    expected_fig9 = {
        (algorithm, dataset)
        for algorithm in FIG9_ALGORITHM_ORDER
        for dataset in ("AU", "SU", "WK")
    }
    require(
        {(row["algorithm"], row["dataset"]) for row in rows["fig9"]} == expected_fig9,
        "Figure 9 algorithm/dataset coverage mismatch",
    )

    fig10_manifest = provenance["fig10"]
    require(fig10_manifest.get("status") == "PASS_SIMULATOR_PREDICTED", "Figure 10 is not admitted")
    require(fig10_manifest.get("rows") == 11, "Figure 10 must contain eleven bars")
    require(
        fig10_manifest.get("outputs", {}).get("normalized_breakdown_rows.csv")
        == sha256(paths["fig10"]),
        "Figure 10 data hash mismatch",
    )
    observed_fig10 = {
        (row["figure_group"], row["figure_tick"]) for row in rows["fig10"]
    }
    expected_fig10 = {
        (group, tick) for group in FIG10_GROUP_ORDER for tick in FIG10_TICKS[group]
    }
    require(observed_fig10 == expected_fig10, "Figure 10 workload coverage mismatch")
    require(len({row["plugin_sha256"] for row in rows["fig10"]}) == 1, "Figure 10 mixes simulator plugins")
    for row in rows["fig10"]:
        percentage = sum(float(row[key]) for key, _label, _color, _hatch in FIG10_STAGES)
        require(math.isclose(percentage, 100.0, abs_tol=1e-6), f"Figure 10 normalization mismatch: {row['execution_id']}")

    require(REFERENCE.is_file(), "GraphyFlow reference archive is missing")
    require(
        sha256(REFERENCE) == "a1b053bbd7c20cd9ce5c79d44a11027327da1c72a402487f5c8c659b71c18a27",
        "GraphyFlow reference archive hash mismatch",
    )
    return rows


def configure_matplotlib() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "text.usetex": True,
            "text.latex.preamble": TXTT_PREAMBLE,
            "font.family": "monospace",
            "font.size": 6.4,
            "axes.labelsize": 6.6,
            "axes.titlesize": 6.8,
            "xtick.labelsize": 6.0,
            "ytick.labelsize": 6.0,
            "legend.fontsize": 6.0,
            "axes.linewidth": 0.7,
            "xtick.major.width": 0.65,
            "ytick.major.width": 0.65,
            "xtick.major.size": 2.3,
            "ytick.major.size": 2.3,
            "hatch.linewidth": 0.38,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    return plt


def save_figure(figure: Any, output: Path, *, dpi: int = 300) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "Creator": "spine-cycle-sim figure7_10_handoff_v1/render_all.py",
        "CreationDate": None,
        "ModDate": None,
    }
    figure.savefig(
        output.with_suffix(".pdf"),
        bbox_inches="tight",
        pad_inches=0.02,
        metadata=metadata,
    )
    figure.savefig(
        output.with_suffix(".png"),
        dpi=dpi,
        bbox_inches="tight",
        pad_inches=0.02,
    )


def render_fig7(plt: Any, rows: list[dict[str, str]]) -> None:
    from matplotlib.patches import Patch

    blue = "#2A7F9E"
    orange = "#D66A00"
    ink = "#202428"
    floor = 0.01
    figure, axes = plt.subplots(4, 1, figsize=(3.55, 4.15))
    algorithms = (*ALGORITHM_ORDER, "full_pagerank")
    for index, (axis, algorithm) in enumerate(zip(axes, algorithms, strict=True)):
        selected = [row for row in rows if row["algorithm"] == algorithm]
        values = [float(row["speedup_median"]) for row in selected]
        colors = [blue if value >= 1.0 else orange for value in values]
        x = list(range(len(selected)))
        axis.bar(
            x,
            [max(value - floor, 1e-12) for value in values],
            bottom=floor,
            width=0.58,
            facecolor="white",
            edgecolor=colors,
            linewidth=0.72,
            hatch="////",
            zorder=3,
        )
        for position, row, color in zip(x, selected, colors, strict=True):
            median = float(row["speedup_median"])
            low = float(row["speedup_min"])
            high = float(row["speedup_max"])
            axis.errorbar(
                position,
                median,
                yerr=[[median - low], [high - median]],
                fmt="none",
                ecolor=color,
                elinewidth=0.65,
                capsize=1.5,
                capthick=0.65,
                zorder=5,
            )
        axis.axhline(1.0, color=ink, linestyle="--", linewidth=0.65, zorder=2)
        axis.set_yscale("log")
        axis.set_ylim(floor, 3000)
        axis.set_yticks((0.01, 0.1, 1, 10, 100, 1000))
        axis.set_yticklabels((".01", ".1", "1", "10", "1e2", "1e3"))
        axis.set_xticks(x)
        axis.set_xticklabels([row["dataset"] for row in selected])
        axis.tick_params(axis="x", length=0)
        axis.grid(axis="y", which="major", color="#D2D5D7", linestyle="--", linewidth=0.45, zorder=0)
        axis.minorticks_off()
        axis.set_title(f"({chr(ord('a') + index)}) {ALGORITHM_LABEL[algorithm]}", pad=3.0, fontweight="bold")
        for spine in axis.spines.values():
            spine.set_color(ink)
            spine.set_linewidth(0.7)
    figure.supylabel("Speedup (G+R / Delta.hls)", x=0.012, fontsize=6.8)
    figure.legend(
        handles=(
            Patch(facecolor="white", edgecolor=blue, hatch="////", label="Delta.hls faster"),
            Patch(facecolor="white", edgecolor=orange, hatch="////", label="G+R faster"),
        ),
        loc="upper center",
        bbox_to_anchor=(0.58, 1.005),
        ncol=2,
        frameon=False,
        handlelength=1.35,
        columnspacing=1.0,
    )
    figure.subplots_adjust(left=0.18, right=0.99, bottom=0.06, top=0.94, hspace=0.62)
    save_figure(figure, FIGURES / "fig7_fpga_speedup")
    plt.close(figure)


def render_fig8(
    plt: Any,
    cross_rows: list[dict[str, str]],
    batch_rows: list[dict[str, str]],
) -> None:
    import matplotlib as mpl
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    blue = "#2A7F9E"
    orange = "#D66A00"
    ink = "#202428"
    figure, axes = plt.subplots(1, 2, figsize=(3.55, 1.55))
    x = list(range(len(cross_rows)))
    cross_speedups = [float(row["spine_speedup"]) for row in cross_rows]
    axes[0].bar(
        x,
        cross_speedups,
        width=0.58,
        facecolor="white",
        edgecolor=blue,
        linewidth=0.72,
        hatch="////",
        zorder=3,
    )
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([row["dataset"] for row in cross_rows])
    axes[0].set_title("(a) Dataset", pad=4.5, fontweight="bold")
    axes[0].set_ylabel("Throughput speedup")

    batch_rows = sorted(batch_rows, key=lambda row: float(row["updates_per_batch"]))
    x = list(range(len(batch_rows)))
    batch_speedups = [float(row["spine_speedup"]) for row in batch_rows]
    axes[1].plot(
        x,
        batch_speedups,
        marker="s",
        markersize=3.2,
        linewidth=0.9,
        color=orange,
        zorder=4,
    )
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([f"{float(row['updates_per_batch']) / 1000:.1f}k" for row in batch_rows])
    axes[1].set_title("(b) Batch size", pad=4.5, fontweight="bold")
    axes[1].set_xlabel("updates/batch")
    for axis, values in zip(axes, (cross_speedups, batch_speedups), strict=True):
        axis.axhline(1.0, color=ink, linestyle="--", linewidth=0.62, zorder=2)
        axis.set_ylim(0.0, max(values) * 1.14)
        axis.yaxis.set_major_locator(mpl.ticker.MaxNLocator(nbins=5, min_n_ticks=4))
        axis.grid(axis="y", color="#D2D5D7", linestyle="--", linewidth=0.45, zorder=0)
        axis.tick_params(axis="x", length=0)
        for spine in axis.spines.values():
            spine.set_color(ink)
            spine.set_linewidth(0.7)
    figure.legend(
        handles=(
            Patch(facecolor="white", edgecolor=blue, hatch="////", label="cross-dataset"),
            Line2D((0,), (0,), color=orange, marker="s", linewidth=0.9, markersize=3.2, label="batch sweep"),
        ),
        loc="upper center",
        bbox_to_anchor=(0.56, 1.01),
        ncol=2,
        frameon=False,
        handlelength=1.25,
        columnspacing=0.8,
    )
    figure.subplots_adjust(left=0.14, right=0.99, bottom=0.24, top=0.80, wspace=0.34)
    save_figure(figure, FIGURES / "fig8_update_throughput")
    plt.close(figure)


def render_fig9(plt: Any, rows: list[dict[str, str]]) -> None:
    import matplotlib as mpl
    from matplotlib.patches import Patch

    dataset_style = {
        "AU": ("#2A7F9E", "////"),
        "SU": ("#D66A00", "\\\\\\\\"),
        "WK": ("#3B8A3E", "||||"),
    }
    ink = "#202428"
    figure, axes = plt.subplots(1, 2, figsize=(3.55, 1.65))
    metrics = (
        ("memory_ratio_gr_over_spine", "(a) Accepted bytes", "G+R / Delta.hls bytes"),
        ("hbm_energy_ratio_gr_over_spine", "(b) HBM energy", "G+R / Delta.hls energy"),
    )
    group_centers: list[float] = []
    positions: dict[tuple[str, str], float] = {}
    cursor = 0.0
    for algorithm in FIG9_ALGORITHM_ORDER:
        start = cursor
        for dataset in ("AU", "SU", "WK"):
            positions[(algorithm, dataset)] = cursor
            cursor += 0.62
        group_centers.append((start + cursor - 0.62) / 2.0)
        cursor += 0.48
    for axis, (metric, title, ylabel) in zip(axes, metrics, strict=True):
        for row in rows:
            color, hatch = dataset_style[row["dataset"]]
            axis.bar(
                positions[(row["algorithm"], row["dataset"])],
                float(row[metric]),
                width=0.43,
                facecolor="white",
                edgecolor=color,
                linewidth=0.72,
                hatch=hatch,
                zorder=3,
            )
        axis.axhline(1.0, color=ink, linestyle="--", linewidth=0.62, zorder=2)
        axis.set_yscale("log")
        values = [float(row[metric]) for row in rows]
        axis.set_ylim(max(0.1, min(values) * 0.55), max(values) * 2.2)
        axis.yaxis.set_major_locator(mpl.ticker.LogLocator(base=10, numticks=5))
        axis.yaxis.set_minor_locator(mpl.ticker.NullLocator())
        axis.set_xticks(group_centers)
        axis.set_xticklabels([FIG9_ALGORITHM_LABEL[algorithm] for algorithm in FIG9_ALGORITHM_ORDER])
        axis.set_ylabel(ylabel)
        axis.set_title(title, pad=4.5, fontweight="bold")
        axis.grid(axis="y", which="major", color="#D2D5D7", linestyle="--", linewidth=0.45, zorder=0)
        axis.tick_params(axis="x", length=0)
        for spine in axis.spines.values():
            spine.set_color(ink)
            spine.set_linewidth(0.7)
    figure.legend(
        handles=tuple(
            Patch(facecolor="white", edgecolor=color, hatch=hatch, label=dataset)
            for dataset, (color, hatch) in dataset_style.items()
        ),
        loc="upper center",
        bbox_to_anchor=(0.56, 1.01),
        ncol=3,
        frameon=False,
        handlelength=1.2,
        columnspacing=0.8,
    )
    figure.subplots_adjust(left=0.15, right=0.99, bottom=0.20, top=0.78, wspace=0.45)
    save_figure(figure, FIGURES / "fig9_memory_energy")
    plt.close(figure)


def render_fig10(plt: Any, rows: list[dict[str, str]]) -> None:
    from matplotlib.patches import Patch

    by_key = {(row["figure_group"], row["figure_tick"]): row for row in rows}
    selected: list[dict[str, str]] = []
    tick_labels: list[str] = []
    x_positions: list[float] = []
    group_centers: list[tuple[str, float]] = []
    separators: list[float] = []
    cursor = 0.0
    for group in FIG10_GROUP_ORDER:
        start = cursor
        for tick in FIG10_TICKS[group]:
            selected.append(by_key[(group, tick)])
            tick_labels.append(tick)
            x_positions.append(cursor)
            cursor += 1.0
        end = cursor - 1.0
        group_centers.append((group, (start + end) / 2.0))
        separators.append(end + 0.55)
        cursor += 0.68
    separators = separators[:-1]

    figure, axis = plt.subplots(figsize=(3.55, 2.08))
    bottoms = [0.0] * len(selected)
    legend = []
    for key, label, color, hatch in FIG10_STAGES:
        values = [float(row[key]) for row in selected]
        axis.bar(
            x_positions,
            values,
            bottom=bottoms,
            width=0.58,
            color=color,
            edgecolor="black",
            linewidth=0.22,
            hatch=hatch,
            zorder=2,
        )
        bottoms = [left + right for left, right in zip(bottoms, values, strict=True)]
        legend.append(Patch(facecolor=color, edgecolor="black", hatch=hatch, label=label))
    for separator in separators:
        axis.axvline(
            separator,
            color="black",
            linestyle=(0, (2.0, 1.1)),
            linewidth=0.58,
            ymin=-0.12,
            ymax=1.0,
            clip_on=False,
            zorder=4,
        )
    display_labels = {
        "Zero-net": "Zero-net",
        "Shallow insert": "Shallow\ninsert",
        "Deep carry": "Deep\ncarry",
        "PR correction": "PR\ncorrection",
        "Deletion fallback": "Deletion\nfallback",
    }
    for group, center in group_centers:
        axis.text(
            center,
            -0.23,
            display_labels[group],
            transform=axis.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=6.8,
            linespacing=0.9,
            clip_on=False,
        )
    axis.set_xlim(min(x_positions) - 0.65, max(x_positions) + 0.65)
    axis.set_xticks(x_positions)
    axis.set_xticklabels(tick_labels)
    axis.set_ylabel("Simulated E2E cycles (\\%)")
    axis.set_ylim(0.0, 108.0)
    axis.set_yticks((0, 25, 50, 75, 100))
    axis.tick_params(axis="x", top=False, bottom=False, length=0, pad=1.4)
    axis.tick_params(axis="y", direction="in", right=True, length=2.8, width=0.7)
    axis.grid(axis="y", linestyle=(0, (2.0, 1.1)), color="0.72", alpha=0.65, linewidth=0.48, zorder=0)
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)
    axis.legend(
        handles=legend,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.245),
        ncol=5,
        frameon=False,
        handlelength=1.35,
        handletextpad=0.3,
        columnspacing=0.48,
        borderaxespad=0.0,
    )
    figure.subplots_adjust(left=0.16, right=0.995, bottom=0.3, top=0.75)
    save_figure(figure, FIGURES / "fig10_simulator_breakdown")
    plt.close(figure)


def render_overview(plt: Any) -> None:
    sources = (
        ("Figure 7", FIGURES / "fig7_fpga_speedup.png"),
        ("Figure 8", FIGURES / "fig8_update_throughput.png"),
        ("Figure 9", FIGURES / "fig9_memory_energy.png"),
        ("Figure 10", FIGURES / "fig10_simulator_breakdown.png"),
    )
    figure, axes = plt.subplots(2, 2, figsize=(8.0, 7.2))
    for axis, (title, path) in zip(axes.flat, sources, strict=True):
        axis.imshow(plt.imread(path))
        axis.set_title(title, fontsize=9, pad=4)
        axis.axis("off")
    figure.tight_layout(pad=0.8)
    figure.savefig(FIGURES / "preview_all.png", dpi=180, bbox_inches="tight", pad_inches=0.04)
    plt.close(figure)


def write_package_manifest() -> None:
    input_paths = sorted((*DATA.glob("*.csv"), *PROVENANCE.glob("*.json"), REFERENCE))
    output_paths = sorted(FIGURES.glob("*"))
    write_json(
        ROOT / "manifest.json",
        {
            "schema_version": 1,
            "status": "PASS_COMPLETE_FIGURE_7_10_HANDOFF",
            "renderer": "render_all.py",
            "figures": {
                "7": "routed U55C setup-inclusive dynamic latency speedup",
                "8": "setup-inclusive update-only throughput speedup",
                "9": "simulator accepted bytes and bound-channel DRAMSim3 energy ratios",
                "10": "normalized simulator-predicted E2E stage attribution",
            },
            "inputs": {str(path.relative_to(ROOT)): sha256(path) for path in input_paths},
            "outputs": {str(path.relative_to(ROOT)): sha256(path) for path in output_paths},
        },
    )


def main() -> int:
    rows = validate_inputs()
    plt = configure_matplotlib()
    render_fig7(plt, rows["fig7"])
    render_fig8(plt, rows["fig8_cross"], rows["fig8_batch"])
    render_fig9(plt, rows["fig9"])
    render_fig10(plt, rows["fig10"])
    render_overview(plt)
    write_package_manifest()
    print(f"FIGURE_7_10_HANDOFF_PASS out={ROOT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
