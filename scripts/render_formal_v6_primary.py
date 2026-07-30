#!/usr/bin/env python3
"""Render the clean formal-v6 primary comparison as vector figures and TeX data."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANALYSIS = Path(
    "/data/tmp/chuxiao/large_graph_campaign_v1/formal_v6_primary_analysis"
)
DEFAULT_UPDATE_ANALYSIS = Path(
    "/data/tmp/chuxiao/large_graph_campaign_v1/formal_v6_au_update_analysis"
)
DEFAULT_COMPONENT_POWER = ROOT / "docs/paper/data/component_power.csv"
DATASET_ORDER = {
    name: index
    for index, name in enumerate(
        (
            "sx_askubuntu",
            "sx_superuser",
            "wiki_talk_temporal",
            "sx_stackoverflow",
            "soc_pokec",
            "soc_livejournal1",
            "ljournal_2008",
            "hollywood_2009",
            "soc_orkut",
        )
    )
}
DATASET_LABEL = {
    "sx_askubuntu": "AU",
    "sx_superuser": "SU",
    "wiki_talk_temporal": "WK",
    "sx_stackoverflow": "SO",
    "soc_pokec": "PK",
    "soc_livejournal1": "LJ",
    "ljournal_2008": "LJ08",
    "hollywood_2009": "HW",
    "soc_orkut": "OK",
}
ALGORITHM_ORDER = {
    "weighted_sssp": 0,
    "connected_components": 1,
    "thresholded_residual_pagerank": 2,
}
ALGORITHM_LABEL = {
    "weighted_sssp": "SSSP",
    "connected_components": "CC",
    "thresholded_residual_pagerank": "ResPR",
}
SCENARIO_ORDER = {"insert": 0, "delete": 1, "weight_change": 2}
SCENARIO_LABEL = {"insert": "Ins", "delete": "Del", "weight_change": "Wgt"}
METRICS = (
    ("spine_speedup", "Spine E2E speedup", "#1f77b4", "///"),
    ("memory_ratio", "G+R / Spine memory bytes", "#ff7f0e", "\\\\\\"),
    ("energy_ratio", "G+R / Spine HBM energy", "#2ca02c", "|||"),
)
FIGURE_TIMESTAMP = datetime(2026, 7, 30, tzinfo=timezone.utc)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open(encoding="ascii", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="ascii")
        return
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def normalize_svg(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(line.rstrip() for line in lines) + "\n", encoding="utf-8")


def admitted_pairs(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        if (
            row.get("competitor") != "grasu_regraph_k4_shared"
            or row.get("scenario") != "insert"
            or row.get("batch_size") != "8"
            or row.get("algorithm") not in ALGORITHM_LABEL
            or row.get("dataset_id") not in DATASET_LABEL
        ):
            continue
        spine_memory = float(row["spine_memory_bytes"])
        spine_energy = float(row["spine_dram_energy_pj"])
        selected.append(
            {
                "dataset_id": row["dataset_id"],
                "dataset": DATASET_LABEL[row["dataset_id"]],
                "algorithm": row["algorithm"],
                "algorithm_label": ALGORITHM_LABEL[row["algorithm"]],
                "label": (
                    f"{DATASET_LABEL[row['dataset_id']]}-"
                    f"{ALGORITHM_LABEL[row['algorithm']]}"
                ),
                "spine_cycles": int(float(row["spine_cycles"])),
                "k4_cycles": int(float(row["competitor_cycles"])),
                "spine_speedup": float(row["spine_speedup"]),
                "spine_memory_bytes": int(float(row["spine_memory_bytes"])),
                "k4_memory_bytes": int(float(row["competitor_memory_bytes"])),
                "spine_discontinuous_fraction": float(
                    row["spine_random_request_fraction"]
                ),
                "k4_discontinuous_fraction": float(
                    row["competitor_random_request_fraction"]
                ),
                "memory_ratio": (
                    float(row["competitor_memory_bytes"]) / spine_memory
                    if spine_memory > 0.0
                    else 0.0
                ),
                "energy_ratio": (
                    float(row["competitor_dram_energy_pj"]) / spine_energy
                    if spine_energy > 0.0
                    else 0.0
                ),
            }
        )
    selected.sort(
        key=lambda row: (
            DATASET_ORDER[row["dataset_id"]],
            ALGORITHM_ORDER[row["algorithm"]],
        )
    )
    for index, row in enumerate(selected):
        row["index"] = index
    return selected


def admitted_update_pairs(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        if (
            row.get("dataset_id") != "sx_askubuntu"
            or row.get("algorithm") != "weighted_sssp"
            or row.get("competitor") != "grasu_regraph_k4_shared"
            or row.get("scenario") not in SCENARIO_ORDER
            or row.get("batch_size") not in {"1", "8", "64"}
        ):
            continue
        batch_size = int(row["batch_size"])
        spine_cycles = int(float(row["spine_update_cycles"]))
        k4_cycles = int(float(row["competitor_update_cycles"]))
        if spine_cycles <= 0 or k4_cycles <= 0:
            continue
        selected.append(
            {
                "scenario": row["scenario"],
                "batch_size": batch_size,
                "label": f"{SCENARIO_LABEL[row['scenario']]}-{batch_size}",
                "spine_update_cycles": spine_cycles,
                "k4_update_cycles": k4_cycles,
                "spine_update_mups": batch_size * 150.0 / spine_cycles,
                "k4_update_mups": batch_size * 150.0 / k4_cycles,
            }
        )
    selected.sort(
        key=lambda row: (
            SCENARIO_ORDER[row["scenario"]],
            int(row["batch_size"]),
        )
    )
    for index, row in enumerate(selected):
        row["index"] = index
    return selected


def configure_matplotlib() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans", "sans-serif"],
            "font.size": 9,
            "axes.labelsize": 10,
            "axes.linewidth": 1.1,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "hatch.linewidth": 0.9,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.hashsalt": "spine-formal-v6",
        }
    )
    return plt


def save_vector_figure(figure: Any, output: Path) -> None:
    figure.savefig(
        output.with_suffix(".pdf"),
        bbox_inches="tight",
        metadata={"CreationDate": FIGURE_TIMESTAMP, "ModDate": FIGURE_TIMESTAMP},
    )
    figure.savefig(
        output.with_suffix(".svg"),
        bbox_inches="tight",
        metadata={"Date": "2026-07-30"},
    )
    normalize_svg(output.with_suffix(".svg"))


def render_ratio_figure(rows: list[dict[str, Any]], output: Path) -> None:
    if not rows:
        raise ValueError("formal v6 report has no complete Spine/K4 pair")
    plt = configure_matplotlib()
    figure, axes = plt.subplots(3, 1, figsize=(7.4, 5.6), sharex=True)
    x_positions = list(range(len(rows)))
    labels = [str(row["label"]) for row in rows]
    for axis, (key, ylabel, color, hatch) in zip(axes, METRICS, strict=True):
        values = [float(row[key]) for row in rows]
        axis.bar(
            x_positions,
            values,
            width=0.58,
            facecolor="white",
            edgecolor=color,
            linewidth=0.0,
            hatch=hatch,
            zorder=2,
        )
        axis.bar(
            x_positions,
            values,
            width=0.58,
            facecolor="none",
            edgecolor="black",
            linewidth=0.9,
            zorder=3,
        )
        axis.axhline(1.0, color="black", linestyle="--", linewidth=0.9, zorder=1)
        positive = [value for value in values if value > 0.0]
        if positive and max(positive) / min(positive) >= 10.0:
            axis.set_yscale("log")
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", linestyle="--", color="0.65", alpha=0.5, zorder=0)
        axis.tick_params(direction="in", top=True, right=True, length=4)
        for position, value in zip(x_positions, values, strict=True):
            axis.annotate(
                f"{value:.2g}x",
                (position, value),
                xytext=(0, 3),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=7,
            )
    axes[-1].set_xticks(x_positions, labels, rotation=30, ha="right")
    axes[-1].set_xlabel("Dataset-algorithm pair")
    figure.tight_layout()
    save_vector_figure(figure, output)
    plt.close(figure)


def render_memory_figure(rows: list[dict[str, Any]], output: Path) -> None:
    if not rows:
        raise ValueError("formal v6 memory report has no complete Spine/K4 pair")
    plt = configure_matplotlib()
    figure, axes = plt.subplots(2, 1, figsize=(7.4, 4.5), sharex=True)
    x_positions = list(range(len(rows)))
    labels = [str(row["label"]) for row in rows]
    width = 0.34

    spine_mib = [float(row["spine_memory_bytes"]) / (1024.0**2) for row in rows]
    k4_mib = [float(row["k4_memory_bytes"]) / (1024.0**2) for row in rows]
    axes[0].bar(
        [position - width / 2 for position in x_positions],
        spine_mib,
        width,
        facecolor="white",
        edgecolor="#1f77b4",
        hatch="///",
        linewidth=1.0,
        label="Spine",
    )
    axes[0].bar(
        [position + width / 2 for position in x_positions],
        k4_mib,
        width,
        facecolor="white",
        edgecolor="#d95f02",
        hatch="\\\\\\",
        linewidth=1.0,
        label="G+R K4-shared",
    )
    positive = [value for value in spine_mib + k4_mib if value > 0.0]
    if positive and max(positive) / min(positive) >= 10.0:
        axes[0].set_yscale("log")
    axes[0].set_ylabel("Accepted backend traffic (MiB)")
    axes[0].legend(frameon=False, ncols=2, loc="upper left")

    axes[1].bar(
        [position - width / 2 for position in x_positions],
        [float(row["spine_discontinuous_fraction"]) for row in rows],
        width,
        facecolor="white",
        edgecolor="#1f77b4",
        hatch="///",
        linewidth=1.0,
    )
    axes[1].bar(
        [position + width / 2 for position in x_positions],
        [float(row["k4_discontinuous_fraction"]) for row in rows],
        width,
        facecolor="white",
        edgecolor="#d95f02",
        hatch="\\\\\\",
        linewidth=1.0,
    )
    axes[1].set_ylabel("Discontinuous request fraction")
    axes[1].set_ylim(0.0, 1.05)
    axes[1].set_xticks(x_positions, labels, rotation=30, ha="right")
    axes[1].set_xlabel("Dataset-algorithm pair")
    for axis in axes:
        axis.grid(axis="y", linestyle="--", color="0.65", alpha=0.5, zorder=0)
        axis.tick_params(direction="in", top=True, right=True, length=4)
    figure.tight_layout()
    save_vector_figure(figure, output)
    plt.close(figure)


def render_component_power_figure(
    rows: list[dict[str, str]], output: Path
) -> None:
    if not rows:
        raise ValueError("component-power evidence is empty")
    plt = configure_matplotlib()
    figure, axis = plt.subplots(figsize=(7.4, 3.5))
    x_positions = list(range(len(rows)))
    labels = [row["label"] for row in rows]
    components = (
        ("hbm_subsystem", "HBM subsystem", "#4c78a8", "///"),
        ("update_maintenance", "Update / maintenance", "#f58518", "\\\\\\"),
        ("graph_compute", "Graph compute", "#54a24b", "|||"),
        ("stream_fifos", "Streams / FIFOs", "#b279a2", "..."),
        ("other_user_logic", "Other user logic", "#9d9d9d", "xxx"),
    )
    bottoms = [0.0 for _ in rows]
    for key, label, color, hatch in components:
        values = [float(row[key]) for row in rows]
        axis.bar(
            x_positions,
            values,
            bottom=bottoms,
            width=0.58,
            facecolor="white",
            edgecolor=color,
            linewidth=1.0,
            hatch=hatch,
            label=label,
        )
        bottoms = [left + right for left, right in zip(bottoms, values, strict=True)]
    axis.set_ylabel("User-level hierarchy power (W)")
    axis.set_xticks(x_positions, labels, rotation=18, ha="right")
    axis.grid(axis="y", linestyle="--", color="0.65", alpha=0.5, zorder=0)
    axis.tick_params(direction="in", top=True, right=True, length=4)
    axis.legend(
        frameon=False,
        ncols=3,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.24),
        fontsize=8,
    )
    figure.tight_layout()
    save_vector_figure(figure, output)
    plt.close(figure)


def render_update_figure(rows: list[dict[str, Any]], output: Path) -> None:
    if not rows:
        raise ValueError("formal v6 update report has no complete Spine/K4 pair")
    plt = configure_matplotlib()
    figure, axis = plt.subplots(figsize=(7.4, 3.5))
    x_positions = list(range(len(rows)))
    width = 0.34
    axis.bar(
        [position - width / 2 for position in x_positions],
        [float(row["spine_update_mups"]) for row in rows],
        width,
        facecolor="white",
        edgecolor="#1f77b4",
        linewidth=1.0,
        hatch="///",
        label="Spine",
    )
    axis.bar(
        [position + width / 2 for position in x_positions],
        [float(row["k4_update_mups"]) for row in rows],
        width,
        facecolor="white",
        edgecolor="#d95f02",
        linewidth=1.0,
        hatch="\\\\\\",
        label="G+R K4-shared",
    )
    axis.set_yscale("log")
    axis.set_ylabel("Update-only throughput (M updates/s)")
    axis.set_xticks(x_positions, [str(row["label"]) for row in rows])
    axis.set_xlabel("Operation and user mutations per batch")
    axis.grid(axis="y", linestyle="--", color="0.65", alpha=0.5, zorder=0)
    axis.tick_params(direction="in", top=True, right=True, length=4)
    axis.legend(frameon=False, ncols=2, loc="upper left")
    figure.tight_layout()
    save_vector_figure(figure, output)
    plt.close(figure)


def tex_escape(value: object) -> str:
    return str(value).replace("_", r"\_")


def write_pair_table(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        r"\begin{tabular}{llrrr}",
        r"\toprule",
        r"Data & Algorithm & Spine cyc & G+R K4 cyc & Speedup \\",
        r"\midrule",
    ]
    for row in rows:
        lines.append(
            f"{tex_escape(row['dataset'])} & {tex_escape(row['algorithm_label'])} & "
            f"{row['spine_cycles']:,} & {row['k4_cycles']:,} & "
            f"{row['spine_speedup']:.2f}$\\times$ \\\\"
        )
    lines.extend((r"\bottomrule", r"\end{tabular}"))
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def write_measurement_table(path: Path, rows: list[dict[str, str]]) -> None:
    windows = sorted(
        {
            (
                row.get("algorithm", ""),
                row.get("system", ""),
                row.get("measurement_window", "unspecified"),
                row.get("algorithm_warm_start", "False"),
            )
            for row in rows
        }
    )
    lines = [
        r"\begin{tabular}{llll}",
        r"\toprule",
        r"Algorithm & System & Window & Warm state \\",
        r"\midrule",
    ]
    for algorithm, system, window, warm in windows:
        lines.append(
            f"{tex_escape(ALGORITHM_LABEL.get(algorithm, algorithm))} & "
            f"{tex_escape('Spine' if system == 'spine' else 'G+R K4-shared')} & "
            f"{tex_escape(window)} & {tex_escape(warm)} \\\\"
        )
    lines.extend((r"\bottomrule", r"\end{tabular}"))
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def render_tex(
    summary: dict[str, Any],
    pairs: list[dict[str, Any]],
    update_pairs: list[dict[str, Any]],
) -> str:
    return rf"""\documentclass[10pt]{{article}}
\usepackage[margin=0.72in]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{graphicx}}
\usepackage{{float}}
\usepackage[hidelinks]{{hyperref}}
\hypersetup{{pdftitle={{Spine Formal-v6 Primary Dynamic-Graph Results}}}}
\title{{\textbf{{Spine Formal-v6 Primary Dynamic-Graph Results}}\\
\large Correctness-Gated Spine vs. GraSU+ReGraph K4-shared}}
\author{{Chuxiao Han}}
\date{{Live snapshot, July 2026}}
\IfFileExists{{data/formal_v6_primary/pair_table.tex}}{{
  \newcommand{{\vdatadir}}{{data/formal_v6_primary}}
  \newcommand{{\vfigdir}}{{../figures}}
}}{{
  \newcommand{{\vdatadir}}{{docs/paper/data/formal_v6_primary}}
  \newcommand{{\vfigdir}}{{docs/figures}}
}}
\begin{{document}}
\maketitle
\begin{{abstract}}
This live report contains {summary['observed_executions']} of
{summary['expected_executions']} expected formal-v6 executions and
{len(pairs)} complete Spine/K4-shared pairs. Missing bars are still-running
or queued executions, never zero-valued measurements. Every admitted row
passes architecture-precision and independent mathematical oracles, full
final-state comparison, and request, response, and DRAM conservation.
\end{{abstract}}

\section{{Measurement contract}}
\begin{{table}}[H]
\centering
\small
\input{{\vdatadir/measurement_table.tex}}
\caption{{Measurement windows observed in admitted formal-v6 rows.}}
\end{{table}}

\paragraph{{SSSP interpretation.}}
Spine starts from a verified persisted old-graph SSSP state and measures the
accepted update, automatic active-source discovery, incremental propagation,
and drain. The conversion-free GraSU+ReGraph baseline performs its declared
complete ReGraph execution because it has no equivalent persisted incremental
SSSP state. This is an architecture-level dynamic-service comparison, not an
identical-kernel microbenchmark.

\paragraph{{Claim boundary.}}
The report is partial until all expected rows finish. Device cycles, accepted
memory bytes, and DRAMSim3 HBM energy are simulator outputs. They do not claim
cycle-for-cycle FPGA calibration, on-chip dynamic energy, or total board power.

\clearpage
\section{{Current primary comparison}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/formal_v6_primary_ratios.pdf}}
\caption{{Ratios for complete insertion-batch-8 pairs. Values above one favor
Spine for E2E latency and indicate that GraSU+ReGraph uses more memory traffic
or HBM energy in the other panels.}}
\end{{figure}}

\begin{{table}}[H]
\centering
\small
\input{{\vdatadir/pair_table.tex}}
\caption{{Absolute device cycles. Only cross-system final-state-matched pairs
enter this table.}}
\end{{table}}

\clearpage
\section{{Memory traffic and request locality}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/formal_v6_memory_locality.pdf}}
\caption{{Absolute accepted-backend traffic and request-stream locality for
the same complete pairs. A request is discontinuous when its accepted address
does not continue the previous request from the same initiator, operation, and
logical HBM channel. This is not a DRAM row-buffer-miss metric.}}
\end{{figure}}

\clearpage
\section{{Update-only throughput}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/formal_v6_update_throughput.pdf}}
\caption{{Correctness-gated AskUbuntu weighted-SSSP update-phase throughput.
The current snapshot contains {len(update_pairs)} of 9 planned operation--batch
pairs. Ins uses the full materialized graph; Del and Wgt use the declared
64K-edge non-monotonic fallback slice. Missing points are not zeros.}}
\end{{figure}}

\paragraph{{Window boundary.}}
This figure isolates graph-structure maintenance cycles and therefore exposes
GraSU's PMA update advantage. It must not be read as end-to-end dynamic graph
service latency, which also includes differential discovery and propagation.

\clearpage
\section{{Implementation-level power attribution}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/formal_v6_component_power.pdf}}
\caption{{Vivado post-route vectorless hierarchy power at 150 MHz. The four
bars are distinct routed builds; the Spine evidence covers SSSP only. Values
use Vivado default activity with Low confidence and establish component
attribution, not workload-calibrated energy or board power.}}
\end{{figure}}

\paragraph{{Energy boundary.}}
The workload-specific HBM energy ratios in Figure 1 come from DRAMSim3 and are
paired with the exact executions plotted there. The vectorless powers above
must not be multiplied by the v6 latency to claim total workload energy.
Workload-calibrated on-chip dynamic energy remains open because equivalent
per-event energy models and complete activity counters are not yet available
for every routed algorithm build.
\end{{document}}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument(
        "--update-analysis-dir", type=Path, default=DEFAULT_UPDATE_ANALYSIS
    )
    parser.add_argument(
        "--figure-dir", type=Path, default=ROOT / "docs/figures"
    )
    parser.add_argument(
        "--data-dir", type=Path, default=ROOT / "docs/paper/data/formal_v6_primary"
    )
    parser.add_argument(
        "--tex", type=Path, default=ROOT / "docs/paper/formal_v6_primary_results.tex"
    )
    parser.add_argument(
        "--component-power", type=Path, default=DEFAULT_COMPONENT_POWER
    )
    args = parser.parse_args()
    summary = json.loads(
        (args.analysis_dir / "summary.json").read_text(encoding="ascii")
    )
    pairs = admitted_pairs(read_csv(args.analysis_dir / "pair_rows.csv"))
    update_pairs = admitted_update_pairs(
        read_csv(args.update_analysis_dir / "pair_rows.csv")
    )
    system_rows = read_csv(args.analysis_dir / "system_rows.csv")
    args.figure_dir.mkdir(parents=True, exist_ok=True)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    render_ratio_figure(pairs, args.figure_dir / "formal_v6_primary_ratios")
    render_memory_figure(pairs, args.figure_dir / "formal_v6_memory_locality")
    render_component_power_figure(
        read_csv(args.component_power),
        args.figure_dir / "formal_v6_component_power",
    )
    render_update_figure(
        update_pairs, args.figure_dir / "formal_v6_update_throughput"
    )
    write_csv(args.data_dir / "pairs.csv", pairs)
    write_csv(args.data_dir / "update_pairs.csv", update_pairs)
    write_pair_table(args.data_dir / "pair_table.tex", pairs)
    write_measurement_table(args.data_dir / "measurement_table.tex", system_rows)
    (args.data_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    args.tex.write_text(render_tex(summary, pairs, update_pairs), encoding="ascii")
    print(
        f"PASS formal-v6 report inputs: observed={summary['observed_executions']} "
        f"pairs={len(pairs)} update_pairs={len(update_pairs)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
