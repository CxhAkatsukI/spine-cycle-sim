#!/usr/bin/env python3
"""Freeze and render the hardware-backed evaluation refresh figures."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "evaluation_refresh_20260810"
DATASET_ORDER = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")
ALGORITHM_ORDER = ("weighted_sssp", "connected_components", "residual_pagerank")
ALGORITHM_LABEL = {
    "weighted_sssp": "Weighted SSSP",
    "connected_components": "Connected Components",
    "residual_pagerank": "Residual PageRank",
    "full_pagerank": "Full PageRank, compact FPGA",
}
CASE_PREFIX = {
    "au": "AU",
    "su": "SU",
    "wk": "WK",
    "so": "SO",
    "pk": "PK",
    "lj": "LJ",
    "lj08": "LJ08",
    "r19": "R19",
}
FULLPR_CASE = {
    "amazon_insert": "AM",
    "web_google_insert": "WG",
    "flickr_insert": "FL",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def dataset_from_case(case: str) -> str:
    prefix = case.split("_", 1)[0]
    if prefix not in CASE_PREFIX:
        raise ValueError(f"unrecognized full-graph case: {case}")
    return CASE_PREFIX[prefix]


def collect_fullgraph_rows(integration_root: Path) -> tuple[list[dict[str, object]], list[Path]]:
    evidence = integration_root / "docs" / "evidence" / "sharded_k4_fullgraph_20260806"
    sources = {
        "weighted_sssp": evidence / "sssp_fullgraph_u55c" / "aggregate_3runs.tsv",
        "connected_components": evidence / "cc_fullgraph_u55c" / "aggregate_3runs.tsv",
        "residual_pagerank": evidence / "respr_fullgraph_u55c" / "aggregate_3runs.tsv",
    }
    rows: list[dict[str, object]] = []
    for algorithm, path in sources.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        for source_row in read_tsv(path):
            dataset = dataset_from_case(source_row["case"])
            rows.append(
                {
                    "algorithm": algorithm,
                    "dataset": dataset,
                    "scope": "full_graph",
                    "samples": int(source_row["samples"]),
                    "speedup_median": float(source_row["setup_speedup_median"]),
                    "speedup_min": float(source_row["setup_speedup_min"]),
                    "speedup_max": float(source_row["setup_speedup_max"]),
                    "timing_window": "setup_inclusive_dynamic_latency",
                    "evidence": "routed_u55c",
                }
            )
    rows.sort(
        key=lambda row: (
            ALGORITHM_ORDER.index(str(row["algorithm"])),
            DATASET_ORDER.index(str(row["dataset"])),
        )
    )
    return rows, list(sources.values())


def collect_compact_fullpr_rows(summary_paths: list[Path]) -> tuple[list[dict[str, object]], list[Path]]:
    by_case: dict[str, list[float]] = {}
    for path in summary_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        for row in read_tsv(path):
            if row["algorithm"] != "full_pagerank" or row["comparison_status"] != "ADMITTED":
                continue
            by_case.setdefault(row["case"], []).append(
                float(row["setup_speedup_gr_over_spine"])
            )
    rows: list[dict[str, object]] = []
    for case, dataset in FULLPR_CASE.items():
        values = by_case.get(case, [])
        if len(values) != len(summary_paths):
            raise ValueError(f"FullPR case {case} has {len(values)} admitted samples")
        rows.append(
            {
                "algorithm": "full_pagerank",
                "dataset": dataset,
                "scope": "compact_one_partition",
                "samples": len(values),
                "speedup_median": statistics.median(values),
                "speedup_min": min(values),
                "speedup_max": max(values),
                "timing_window": "setup_inclusive_dynamic_latency",
                "evidence": "routed_u55c_k4_shared",
            }
        )
    return rows, summary_paths


def configure_matplotlib() -> None:
    mpl.rcParams.update(
        {
            "font.family": "monospace",
            "font.monospace": ["TX Typewriter", "Nimbus Mono PS", "DejaVu Sans Mono"],
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
            "hatch.linewidth": 0.45,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def render_fig7(rows: list[dict[str, object]], output_base: Path) -> None:
    configure_matplotlib()
    blue = "#2A7F9E"
    orange = "#D66A00"
    ink = "#202428"
    floor = 0.01
    figure, axes = plt.subplots(4, 1, figsize=(3.55, 4.15))
    algorithms = (*ALGORITHM_ORDER, "full_pagerank")
    for index, (axis, algorithm) in enumerate(zip(axes, algorithms)):
        selected = [row for row in rows if row["algorithm"] == algorithm]
        labels = [str(row["dataset"]) for row in selected]
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
            linewidth=0.75,
            hatch="///",
            zorder=3,
        )
        for position, row, color in zip(x, selected, colors):
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
        axis.set_yticks([0.01, 0.1, 1, 10, 100, 1000])
        axis.set_yticklabels([".01", ".1", "1", "10", "1e2", "1e3"])
        axis.set_xticks(x)
        axis.set_xticklabels(labels)
        axis.tick_params(axis="x", length=0)
        axis.grid(axis="y", which="major", color="#D2D5D7", linestyle="--", linewidth=0.45, zorder=0)
        axis.minorticks_off()
        axis.set_title(f"({chr(ord('a') + index)}) {ALGORITHM_LABEL[algorithm]}", pad=3.0, fontweight="bold")
        for spine in axis.spines.values():
            spine.set_color(ink)
            spine.set_linewidth(0.7)
    figure.supylabel("Speedup (G+R / Delta.hls)", x=0.012, fontsize=6.8)
    figure.legend(
        handles=[
            Patch(facecolor="white", edgecolor=blue, hatch="///", label="Delta.hls faster"),
            Patch(facecolor="white", edgecolor=orange, hatch="///", label="G+R faster"),
        ],
        loc="upper center",
        bbox_to_anchor=(0.58, 1.005),
        ncol=2,
        frameon=False,
        handlelength=1.35,
        columnspacing=1.0,
    )
    figure.subplots_adjust(left=0.18, right=0.99, bottom=0.06, top=0.94, hspace=0.62)
    output_base.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_base.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.02)
    figure.savefig(output_base.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--integration-root",
        type=Path,
        default=Path("/home/chuxiao/grasu-regraph-integration"),
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--fullpr-summary",
        type=Path,
        action="append",
        default=[],
        help="repeatable compact FullPR FPGA summary.tsv",
    )
    args = parser.parse_args()
    fullpr_summaries = args.fullpr_summary or [
        Path("/data/tmp/chuxiao/matched_fpga_fullpr_k4_real_20260805/summary.tsv"),
        Path("/data/tmp/chuxiao/matched_fpga_fullpr_k4_real_20260805_repeat2/summary.tsv"),
        Path("/data/tmp/chuxiao/matched_fpga_fullpr_k4_real_20260805_repeat3/summary.tsv"),
    ]
    fullgraph, fullgraph_sources = collect_fullgraph_rows(args.integration_root.resolve())
    fullpr, fullpr_sources = collect_compact_fullpr_rows(
        [path.resolve() for path in fullpr_summaries]
    )
    rows = fullgraph + fullpr
    data_path = args.out_dir / "data" / "fig7_fpga_speedup.csv"
    write_csv(data_path, rows)
    render_fig7(rows, args.out_dir / "figures" / "fig7_fpga_speedup_candidate")
    sources = fullgraph_sources + fullpr_sources
    provenance = {
        "status": "PASS",
        "figure": "fig7_fpga_speedup_candidate",
        "timing_window": "setup_inclusive_dynamic_latency",
        "source_files": [
            {"path": str(path.resolve()), "sha256": sha256(path.resolve())}
            for path in sources
        ],
        "data_csv": str(data_path.resolve()),
        "data_csv_sha256": sha256(data_path),
        "limitations": [
            "Panels a-c use destination-sharded K4 full-graph hardware.",
            "Panel d uses compact one-partition K4-shared hardware until the sharded FullPR route is available.",
            "No projected or timeout-bounded value enters the figure.",
        ],
    }
    provenance_path = args.out_dir / "provenance" / "fig7.json"
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"FIG7_REFRESH_PASS rows={len(rows)} out={args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
