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
FIG8_CROSS_DATA = ROOT / "docs" / "paper" / "data" / "persistent_update_setup_cross_dataset.csv"
FIG8_BATCH_DATA = ROOT / "docs" / "paper" / "data" / "persistent_update_setup_batch_sensitivity.csv"
FIG9_PAIR_DATA = ROOT / "docs" / "paper" / "data" / "formal_v7_primary" / "pairs.csv"
FIG10_LATENCY_DATA = ROOT / "docs" / "paper" / "data" / "rq3" / "rq3_latency_rows.csv"
FIG10_SUMMARY_DATA = ROOT / "docs" / "paper" / "data" / "rq3" / "rq3_summary.json"
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
FIG9_DATASET_ORDER = ("AU", "SU", "WK")
FIG8_CROSS_FILENAME = "persistent_update_setup_cross_dataset.csv"
FIG8_BATCH_FILENAME = "persistent_update_setup_batch_sensitivity.csv"
FIG8_MANIFEST_FILENAME = "persistent_update_setup_manifest.json"
FIG10_LATENCY_FILENAME = "rq3_latency_rows.csv"
FIG10_SUMMARY_FILENAME = "rq3_summary.json"
FIG10_COMPONENTS = (
    (
        ("t_xfer_cycles", "t_reduce_cycles", "t_carry_cycles", "t_directory_cycles"),
        "Maint.",
        "#9BC47C",
        "xxxxxx",
    ),
    (("t_seed_cycles", "t_switch_cycles"), "Seed/pub.", "#E39A52", "||||||"),
    (("t_resolve_cycles",), "Resolve", "#2F86BD", "//////"),
    (("t_app_cycles",), "App", "#B7D6E8", "\\\\\\\\\\\\"),
    (("t_drain_cycles", "t_sync_cycles"), "Drain", "#35A936", "xxxxxx"),
)
FIG10_GROUPS = (
    (
        "ZN",
        (
            ("Syn", "rq3_zero_net_cc_u2"),
        ),
    ),
    (
        "SI",
        (
            ("A-S", "53d8ac095d6b4bb6739f"),
            ("L-S", "980c084e249992cc626c"),
            ("S-S", "b76a15fdd98228a1da6e"),
        ),
    ),
    (
        "Carry",
        (
            ("L1", "rq3_trace_carry_l1_e8"),
            ("L3", "rq3_trace_carry_l3_e8"),
            ("L5", "rq3_trace_carry_l5_e8"),
        ),
    ),
    (
        "PR-corr",
        (
            ("FL", "rq3_flickr_residual_correction_u8_eps1e6"),
            ("SU", "3f8e9fc7157d096b8488"),
            ("WK", "d310ed825d5fef3de031"),
        ),
    ),
    (
        "Del",
        (
            ("AU", "087ea93d578261400aa6"),
            ("SU", "12b7427a1e2f4185c8c9"),
            ("WK", "383e63c5d7f96cdd4774"),
        ),
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source, delimiter="\t"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def number(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    return float(value) if value not in ("", None) else 0.0


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
    global mpl, plt, Patch
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

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


def render_fig8(
    cross_rows: list[dict[str, str]],
    batch_rows: list[dict[str, str]],
    output_base: Path,
) -> None:
    configure_matplotlib()
    blue = "#2A7F9E"
    orange = "#D66A00"
    ink = "#202428"
    figure, axes = plt.subplots(1, 2, figsize=(3.55, 1.55))

    cross_rows = [row for row in cross_rows if row["dataset"] in ("AU", "SU", "WK", "SO", "PK")]
    x = list(range(len(cross_rows)))
    axes[0].bar(
        x,
        [float(row["spine_speedup"]) for row in cross_rows],
        width=0.58,
        facecolor="white",
        edgecolor=blue,
        linewidth=0.72,
        hatch="///",
        zorder=3,
    )
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([row["dataset"] for row in cross_rows])
    axes[0].set_title("(a) Dataset", pad=4.5, fontweight="bold")
    axes[0].set_ylabel("Throughput speedup")

    batch_rows = sorted(batch_rows, key=lambda row: float(row["updates_per_batch"]))
    x = list(range(len(batch_rows)))
    axes[1].plot(
        x,
        [float(row["spine_speedup"]) for row in batch_rows],
        marker="s",
        markersize=3.2,
        linewidth=0.9,
        color=orange,
        zorder=4,
    )
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(
        [f"{float(row['updates_per_batch'])/1000:.1f}k" for row in batch_rows]
    )
    axes[1].set_title("(b) Batch size", pad=4.5, fontweight="bold")
    axes[1].set_xlabel("updates/batch")

    for axis in axes:
        axis.axhline(1.0, color=ink, linestyle="--", linewidth=0.62, zorder=2)
        axis.set_ylim(0.0, max(axis.get_ylim()[1], 3.1))
        axis.set_yticks((0, 1, 2, 3))
        axis.grid(axis="y", color="#D2D5D7", linestyle="--", linewidth=0.45, zorder=0)
        axis.tick_params(axis="x", length=0)
        for spine in axis.spines.values():
            spine.set_color(ink)
            spine.set_linewidth(0.7)
    axes[1].legend(
        handles=[
            Patch(facecolor="white", edgecolor=blue, hatch="///", label="cross-dataset"),
            Patch(facecolor=orange, edgecolor=orange, label="batch sweep"),
        ],
        loc="upper center",
        bbox_to_anchor=(-0.12, 1.30),
        ncol=2,
        frameon=False,
        handlelength=1.25,
        columnspacing=0.8,
    )
    figure.subplots_adjust(left=0.14, right=0.99, bottom=0.24, top=0.80, wspace=0.34)
    output_base.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_base.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.02)
    figure.savefig(output_base.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)


def collect_fig9_rows() -> tuple[list[dict[str, object]], Path, str]:
    rows = []
    for row in read_csv(FIG9_PAIR_DATA):
        if row["algorithm"] not in FIG9_ALGORITHM_ORDER:
            continue
        if row["dataset"] not in FIG9_DATASET_ORDER:
            continue
        rows.append(
            {
                "dataset": row["dataset"],
                "algorithm": row["algorithm"],
                "algorithm_label": FIG9_ALGORITHM_LABEL[row["algorithm"]],
                "memory_ratio_gr_over_spine": float(row["memory_ratio"]),
                "hbm_energy_ratio_gr_over_spine": float(row["energy_ratio"]),
                "spine_memory_bytes": int(float(row["spine_memory_bytes"])),
                "gr_memory_bytes": int(float(row["k4_memory_bytes"])),
            }
        )
    rows.sort(
        key=lambda row: (
            FIG9_ALGORITHM_ORDER.index(str(row["algorithm"])),
            FIG9_DATASET_ORDER.index(str(row["dataset"])),
        )
    )
    return rows, FIG9_PAIR_DATA, "INTERIM_ARCHIVED_SIMULATOR_DATA"


def collect_fig8_rows(
    data_dir: Path | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[Path], str]:
    if data_dir is None:
        cross_path = FIG8_CROSS_DATA
        batch_path = FIG8_BATCH_DATA
        status = "INTERIM_ARCHIVED_SIMULATOR_DATA"
        sources = [cross_path, batch_path]
    else:
        cross_path = data_dir / FIG8_CROSS_FILENAME
        batch_path = data_dir / FIG8_BATCH_FILENAME
        manifest_path = data_dir / FIG8_MANIFEST_FILENAME
        manifest = read_json(manifest_path)
        status = str(manifest.get("status", ""))
        if status != "PASS_CURRENT_MODEL_DATA":
            raise ValueError(
                "Fig. 8 current data must include "
                f"{FIG8_MANIFEST_FILENAME} with status=PASS_CURRENT_MODEL_DATA"
            )
        if manifest.get("metric") != "setup_inclusive_update_only_throughput":
            raise ValueError("Fig. 8 manifest has the wrong metric")
        sources = [cross_path, batch_path, manifest_path]
    return read_csv(cross_path), read_csv(batch_path), sources, status


def collect_fig9_rows_from_campaign(
    analysis_dir: Path,
) -> tuple[list[dict[str, object]], Path, str]:
    path = analysis_dir / "pair_rows.csv"
    if not path.is_file():
        raise FileNotFoundError(path)
    rows = []
    dataset_label = {
        "sx_askubuntu": "AU",
        "sx_superuser": "SU",
        "wiki_talk_temporal": "WK",
        "au": "AU",
        "su": "SU",
        "wk": "WK",
    }
    for row in read_csv(path):
        if row.get("competitor") != "grasu_regraph_k4_shared":
            continue
        if row["algorithm"] not in FIG9_ALGORITHM_ORDER:
            continue
        dataset = dataset_label.get(row["dataset_id"])
        if dataset not in FIG9_DATASET_ORDER:
            continue
        spine_memory = float(row["spine_memory_bytes"])
        competitor_memory = float(row["competitor_memory_bytes"])
        rows.append(
            {
                "dataset": dataset,
                "algorithm": row["algorithm"],
                "algorithm_label": FIG9_ALGORITHM_LABEL[row["algorithm"]],
                "memory_ratio_gr_over_spine": (
                    competitor_memory / spine_memory if spine_memory else 0.0
                ),
                "hbm_energy_ratio_gr_over_spine": float(row["spine_energy_advantage"]),
                "spine_memory_bytes": int(spine_memory),
                "gr_memory_bytes": int(competitor_memory),
            }
        )
    rows.sort(
        key=lambda row: (
            FIG9_ALGORITHM_ORDER.index(str(row["algorithm"])),
            FIG9_DATASET_ORDER.index(str(row["dataset"])),
        )
    )
    expected = len(FIG9_ALGORITHM_ORDER) * len(FIG9_DATASET_ORDER)
    manifest_path = analysis_dir / "manifest.json"
    manifest_status = (
        str(read_json(manifest_path).get("status", ""))
        if manifest_path.is_file()
        else ""
    )
    if len(rows) == expected and manifest_status == "PASS_CURRENT_MODEL_DATA":
        status = "PASS_CURRENT_MODEL_DATA"
    elif len(rows) == expected:
        status = "PASS_CAMPAIGN_ANALYSIS"
    else:
        status = "PARTIAL_CAMPAIGN_ANALYSIS"
    return rows, path, status


def render_fig9(rows: list[dict[str, object]], output_base: Path) -> None:
    configure_matplotlib()
    dataset_style = {
        "AU": ("#2A7F9E", "///"),
        "SU": ("#D66A00", "\\\\\\"),
        "WK": ("#3B8A3E", "|||"),
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
        for dataset in FIG9_DATASET_ORDER:
            positions[(algorithm, dataset)] = cursor
            cursor += 0.62
        group_centers.append((start + cursor - 0.62) / 2.0)
        cursor += 0.48

    for axis, (metric, title, ylabel) in zip(axes, metrics, strict=True):
        for row in rows:
            color, hatch = dataset_style[str(row["dataset"])]
            axis.bar(
                positions[(str(row["algorithm"]), str(row["dataset"]))],
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
    axes[1].legend(
        handles=[
            Patch(facecolor="white", edgecolor=color, hatch=hatch, label=dataset)
            for dataset, (color, hatch) in dataset_style.items()
        ],
        loc="upper center",
        bbox_to_anchor=(-0.12, 1.31),
        ncol=3,
        frameon=False,
        handlelength=1.2,
        columnspacing=0.8,
    )
    figure.subplots_adjust(left=0.15, right=0.99, bottom=0.20, top=0.78, wspace=0.45)
    output_base.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_base.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.02)
    figure.savefig(output_base.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)


def collect_fig10_rows() -> list[dict[str, object]]:
    return collect_fig10_rows_from_path(FIG10_LATENCY_DATA)


def _first_fig10_match(
    rows: list[dict[str, str]],
    *,
    group: str,
    tick: str,
    **criteria: str,
) -> dict[str, object] | None:
    for row in rows:
        if all(row.get(key) == value for key, value in criteria.items()):
            selected = dict(row)
            selected["figure_group"] = group
            selected["figure_tick"] = tick
            return selected
    return None


def collect_fig10_rows_from_path(latency_path: Path) -> list[dict[str, object]]:
    all_rows = read_csv(latency_path)
    selected_ids = {
        execution_id
        for _, entries in FIG10_GROUPS
        for _, execution_id in entries
    }
    rows = [row for row in all_rows if row["execution_id"] in selected_ids]
    by_id = {row["execution_id"]: row for row in rows}
    missing = sorted(selected_ids - set(by_id))
    if not missing:
        ordered: list[dict[str, object]] = []
        for group, entries in FIG10_GROUPS:
            for tick, execution_id in entries:
                row = dict(by_id[execution_id])
                row["figure_group"] = group
                row["figure_tick"] = tick
                ordered.append(row)
        return ordered

    current_version = next(
        (
            version
            for version in ("v12", "v11")
            if any(
                row.get("execution_id", "").startswith(
                    f"current_fpga_{version}_"
                )
                for row in all_rows
            )
        ),
        None,
    )
    if current_version is not None:
        dynamic_specs = (
            (
                "SI",
                (
                    (
                        "AU",
                        {
                            "case_class": "shallow_insertion",
                            "algorithm": "weighted_sssp",
                            "dataset_id": "au",
                        },
                    ),
                    (
                        "SU",
                        {
                            "case_class": "shallow_insertion",
                            "algorithm": "weighted_sssp",
                            "dataset_id": "su",
                        },
                    ),
                    (
                        "WK",
                        {
                            "case_class": "shallow_insertion",
                            "algorithm": "weighted_sssp",
                            "dataset_id": "wk",
                        },
                    ),
                ),
            ),
            (
                "Carry",
                (
                    ("L1", {"execution_id": "rq3_trace_carry_l1_e8"}),
                    ("L3", {"execution_id": "rq3_trace_carry_l3_e8"}),
                    ("L5", {"execution_id": "rq3_trace_carry_l5_e8"}),
                ),
            ),
            (
                "PR-corr",
                (
                    (
                        "U1",
                        {
                            "execution_id": (
                                f"current_fpga_{current_version}_flickr_respr_correction_u1"
                            )
                        },
                    ),
                    (
                        "U8",
                        {
                            "execution_id": (
                                f"current_fpga_{current_version}_flickr_respr_correction_u8"
                            )
                        },
                    ),
                    (
                        "U64",
                        {
                            "execution_id": (
                                f"current_fpga_{current_version}_flickr_respr_correction_u64"
                            )
                        },
                    ),
                ),
            ),
            (
                "Del",
                (
                    (
                        "Syn",
                        {
                            "execution_id": (
                                f"current_fpga_{current_version}_delete_fallback_sssp"
                            )
                        },
                    ),
                ),
            ),
        )
    else:
        dynamic_specs = (
        (
            "ZN",
            (
                ("Syn", {"case_class": "zero_net"}),
            ),
        ),
        (
            "SI",
            (
                (
                    "AU",
                    {
                        "case_class": "shallow_insertion",
                        "algorithm": "weighted_sssp",
                        "dataset_id": "sx_askubuntu",
                    },
                ),
                (
                    "SU",
                    {
                        "case_class": "shallow_insertion",
                        "algorithm": "weighted_sssp",
                        "dataset_id": "sx_superuser",
                    },
                ),
                (
                    "WK",
                    {
                        "case_class": "shallow_insertion",
                        "algorithm": "weighted_sssp",
                        "dataset_id": "wiki_talk_temporal",
                    },
                ),
            ),
        ),
        (
            "Carry",
            (
                ("L1", {"execution_id": "rq3_trace_carry_l1_e8"}),
                ("L3", {"execution_id": "rq3_trace_carry_l3_e8"}),
                ("L5", {"execution_id": "rq3_trace_carry_l5_e8"}),
            ),
        ),
        (
            "PR-corr",
            (
                ("FL", {"execution_id": "rq3_flickr_residual_correction_u8_eps1e6"}),
                (
                    "SU",
                    {
                        "case_class": "pagerank_correction",
                        "dataset_id": "sx_superuser",
                    },
                ),
                (
                    "WK",
                    {
                        "case_class": "pagerank_correction",
                        "dataset_id": "wiki_talk_temporal",
                    },
                ),
            ),
        ),
        (
            "Del",
            (
                ("Syn", {"case_class": "deletion_fallback"}),
            ),
        ),
        )
    ordered = []
    missing_dynamic = []
    for group, entries in dynamic_specs:
        for tick, criteria in entries:
            row = _first_fig10_match(all_rows, group=group, tick=tick, **criteria)
            if row is None:
                missing_dynamic.append(f"{group}/{tick}")
            else:
                ordered.append(row)
    if missing_dynamic:
        raise ValueError(
            "missing Fig10 RQ3 executions after dynamic selection: "
            f"{missing_dynamic}; fixed-id misses were {missing}"
        )
    return ordered


def collect_fig10_inputs(data_dir: Path | None) -> tuple[list[dict[str, object]], list[Path], str]:
    if data_dir is None:
        latency_path = FIG10_LATENCY_DATA
        summary_path = FIG10_SUMMARY_DATA
        status = "INTERIM_ARCHIVED_SIMULATOR_DATA"
    else:
        latency_path = data_dir / FIG10_LATENCY_FILENAME
        summary_path = data_dir / FIG10_SUMMARY_FILENAME
        status = "PASS_CURRENT_MODEL_DATA"
    return collect_fig10_rows_from_path(latency_path), [latency_path, summary_path], status


def render_fig10(rows: list[dict[str, object]], output_base: Path) -> None:
    configure_matplotlib()
    selected = rows
    tick_labels: list[str] = []
    x_positions: list[float] = []
    group_centers: list[tuple[str, float]] = []
    separators: list[float] = []
    cursor = 0.0
    groups = []
    for row in selected:
        group_label = str(row["figure_group"])
        if not groups or groups[-1][0] != group_label:
            groups.append((group_label, []))
        groups[-1][1].append(row)
    for group_label, entries in groups:
        start = cursor
        for row in entries:
            tick_labels.append(str(row["figure_tick"]))
            x_positions.append(cursor)
            cursor += 1.0
        end = cursor - 1.0
        group_centers.append((group_label, (start + end) / 2.0))
        separators.append(end + 0.55)
        cursor += 0.68
    separators = separators[:-1]

    figure, axis = plt.subplots(figsize=(3.55, 1.95))
    bottoms = [0.0] * len(selected)
    legend = []
    for keys, label, color, hatch in FIG10_COMPONENTS:
        percentages = []
        for row in selected:
            total = number(row, "total_cycles")
            component = sum(number(row, key) for key in keys)
            percentages.append(100.0 * component / total if total else 0.0)
        axis.bar(
            x_positions,
            percentages,
            bottom=bottoms,
            width=0.58,
            color=color,
            edgecolor="black",
            linewidth=0.22,
            hatch=hatch,
            zorder=2,
        )
        bottoms = [left + right for left, right in zip(bottoms, percentages, strict=True)]
        legend.append(Patch(facecolor=color, edgecolor="black", hatch=hatch, label=label))
    for separator in separators:
        axis.axvline(
            separator,
            color="black",
            linestyle=(0, (2.0, 1.1)),
            linewidth=0.65,
            ymin=-0.11,
            ymax=1.0,
            clip_on=False,
            zorder=4,
        )
    for group_label, center in group_centers:
        axis.text(
            center,
            -0.22,
            group_label,
            transform=axis.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=7.2,
            clip_on=False,
        )
    axis.set_xlim(min(x_positions) - 0.65, max(x_positions) + 0.65)
    axis.set_xticks(x_positions)
    axis.set_xticklabels(tick_labels)
    axis.set_ylabel("E2E cycles (%)")
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
        bbox_to_anchor=(0.5, 1.25),
        ncol=5,
        frameon=False,
        handlelength=1.45,
        handletextpad=0.35,
        columnspacing=0.58,
        borderaxespad=0.0,
    )
    figure.subplots_adjust(left=0.15, right=0.995, bottom=0.27, top=0.76)
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
    parser.add_argument(
        "--campaign-analysis-dir",
        type=Path,
        help="optional publication campaign analysis directory used to refresh Fig. 9",
    )
    parser.add_argument(
        "--fig8-data-dir",
        type=Path,
        help=(
            "optional current-model directory containing "
            f"{FIG8_CROSS_FILENAME} and {FIG8_BATCH_FILENAME}"
        ),
    )
    parser.add_argument(
        "--fig10-data-dir",
        type=Path,
        help=(
            "optional current-model RQ3 directory containing "
            f"{FIG10_LATENCY_FILENAME} and {FIG10_SUMMARY_FILENAME}"
        ),
    )
    parser.add_argument(
        "--allow-partial-campaign-fig9",
        action="store_true",
        help="render Fig. 9 from partial campaign pair rows instead of falling back",
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
    write_json(args.out_dir / "provenance" / "fig7.json", provenance)

    fig8_cross_rows, fig8_batch_rows, fig8_sources, fig8_status = collect_fig8_rows(
        args.fig8_data_dir.resolve() if args.fig8_data_dir is not None else None
    )
    write_csv(args.out_dir / "data" / "fig8_update_cross_dataset.csv", fig8_cross_rows)
    write_csv(args.out_dir / "data" / "fig8_update_batch_sensitivity.csv", fig8_batch_rows)
    render_fig8(
        fig8_cross_rows,
        fig8_batch_rows,
        args.out_dir / "figures" / "fig8_update_throughput_candidate",
    )
    write_json(
        args.out_dir / "provenance" / "fig8.json",
        {
            "status": fig8_status,
            "figure": "fig8_update_throughput_candidate",
            "timing_window": "setup_inclusive_update_throughput",
            "source_files": [
                {"path": str(path.resolve()), "sha256": sha256(path.resolve())}
                for path in fig8_sources
            ],
            "limitations": [
                (
                    "Uses archived update-only setup-inclusive simulator evidence."
                    if fig8_status.startswith("INTERIM")
                    else "Uses current-model setup-inclusive simulator evidence."
                ),
                (
                    "Should be regenerated after the sharded-K4 calibration refresh is complete."
                    if fig8_status.startswith("INTERIM")
                    else "Admitted as current-model refresh input."
                ),
            ],
        },
    )

    fig9_rows: list[dict[str, object]]
    fig9_source: Path
    fig9_status: str
    if args.campaign_analysis_dir is not None:
        candidate_rows, fig9_source, fig9_status = collect_fig9_rows_from_campaign(
            args.campaign_analysis_dir.resolve()
        )
        if fig9_status in {"PASS_CAMPAIGN_ANALYSIS", "PASS_CURRENT_MODEL_DATA"} or (
            candidate_rows and args.allow_partial_campaign_fig9
        ):
            fig9_rows = candidate_rows
        else:
            candidate_count = len(candidate_rows)
            fig9_rows, fig9_source, fig9_status = collect_fig9_rows()
            fig9_status = (
                "INTERIM_ARCHIVED_SIMULATOR_DATA_CAMPAIGN_FALLBACK_"
                f"candidate_rows_{candidate_count}"
            )
    else:
        fig9_rows, fig9_source, fig9_status = collect_fig9_rows()
    fig9_data = args.out_dir / "data" / "fig9_memory_energy_rows.csv"
    write_csv(fig9_data, fig9_rows)
    render_fig9(fig9_rows, args.out_dir / "figures" / "fig9_memory_energy_candidate")
    write_json(
        args.out_dir / "provenance" / "fig9.json",
        {
            "status": fig9_status,
            "figure": "fig9_memory_energy_candidate",
            "source_files": [
                {"path": str(fig9_source.resolve()), "sha256": sha256(fig9_source)}
            ],
            "data_csv": str(fig9_data.resolve()),
            "data_csv_sha256": sha256(fig9_data),
            "limitations": [
                "Memory and HBM-energy ratios come from the shared simulator ledger, not routed FPGA power.",
                "Rows are limited to AU/SU/WK and differential algorithms to keep the panel readable.",
            ],
        },
    )

    fig10_rows, fig10_sources, fig10_status = collect_fig10_inputs(
        args.fig10_data_dir.resolve() if args.fig10_data_dir is not None else None
    )
    fig10_data = args.out_dir / "data" / "fig10_rq3_breakdown_rows.csv"
    write_csv(fig10_data, fig10_rows)
    render_fig10(fig10_rows, args.out_dir / "figures" / "fig10_rq3_breakdown_candidate")
    write_json(
        args.out_dir / "provenance" / "fig10.json",
        {
            "status": fig10_status,
            "figure": "fig10_rq3_breakdown_candidate",
            "source_files": [
                {"path": str(path.resolve()), "sha256": sha256(path.resolve())}
                for path in fig10_sources
            ],
            "data_csv": str(fig10_data.resolve()),
            "data_csv_sha256": sha256(fig10_data),
            "normalization": "Each stacked bar is normalized to 100% of its own end-to-end device-cycle interval.",
            "label_key": {
                "ZN": "zero-net update",
                "SI": "shallow insertion",
                "AU/SU/WK": "AskUbuntu/Superuser/WikiTalk current-model rows",
                "L1/L3/L5": "synthetic deep-carry traces that force carry through level 1, 3, or 5",
                "PR-corr": "PageRank residual correction",
                "FL/SU/WK": "Flickr/Superuser/WikiTalk PageRank correction rows",
                "Del": "synthetic SSSP deletion-fallback row",
            },
        },
    )

    print(f"EVALUATION_REFRESH_PASS fig7_rows={len(rows)} out={args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
