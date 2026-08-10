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
    "/data/tmp/chuxiao/large_graph_campaign_v1/formal_v8_au_update_scaling/analysis"
)
DEFAULT_OPERATION_UPDATE_ANALYSIS = Path(
    "/data/tmp/chuxiao/large_graph_campaign_v1/formal_v6_au_update_analysis"
)
DEFAULT_COMPONENT_POWER = ROOT / "docs/paper/data/component_power.csv"
DEFAULT_WORKLOAD_ENERGY = ROOT / "docs/paper/data/workload_energy"
DEFAULT_CONTRACT = (
    ROOT / "configs/contracts/large_graph_publication_campaign_fullgraph_v6.json"
)
DEFAULT_MATERIALIZATION_ROOT = Path(
    "/data/tmp/chuxiao/large_graph_campaign_v1/workloads"
)
DEFAULT_RQ3_DATA = ROOT / "docs/paper/data/rq3"
DEFAULT_WALL_TIME_PROJECTION = (
    ROOT / "docs/evidence/formal_v6_large_sssp_runtime_projection_20260730.json"
)
DEFAULT_STOPPED_PREFIX_LOWER_BOUNDS = (
    ROOT / "docs/evidence/formal_v7_stopped_prefix_lower_bounds_20260731.json"
)
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
            "rmat_19_32",
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
    "rmat_19_32": "R19",
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
UPDATE_SCALING_BATCHES = (64, 1_024, 16_384, 131_072)
UPDATE_SCALING_LABEL = {64: "64", 1_024: "1K", 16_384: "16K", 131_072: "128K"}
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
                "group_id": row.get("group_id", ""),
                "dataset_id": row["dataset_id"],
                "dataset_kind": row.get(
                    "dataset_kind",
                    "synthetic" if row["dataset_id"] == "rmat_19_32" else "real",
                ),
                "dataset": DATASET_LABEL[row["dataset_id"]],
                "algorithm": row["algorithm"],
                "competitor": row["competitor"],
                "algorithm_label": ALGORITHM_LABEL[row["algorithm"]],
                "label": (
                    f"{DATASET_LABEL[row['dataset_id']]}-"
                    f"{ALGORITHM_LABEL[row['algorithm']]}"
                ),
                "spine_cycles": int(float(row["spine_cycles"])),
                "k4_cycles": int(float(row["competitor_cycles"])),
                "spine_speedup": float(row["spine_speedup"]),
                "spine_host_wall_seconds": float(row["spine_host_wall_seconds"]),
                "k4_host_wall_seconds": float(row["competitor_host_wall_seconds"]),
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
            or row.get("scenario") != "insert"
            or int(row.get("batch_size", -1)) not in UPDATE_SCALING_BATCHES
        ):
            continue
        batch_size = int(row["batch_size"])
        spine_cycles = int(float(row["spine_structure_update_cycles"]))
        k4_cycles = int(float(row["competitor_structure_update_cycles"]))
        if spine_cycles <= 0 or k4_cycles <= 0:
            continue
        selected.append(
            {
                "scenario": row["scenario"],
                "batch_size": batch_size,
                "label": UPDATE_SCALING_LABEL[batch_size],
                "spine_structure_update_cycles": spine_cycles,
                "k4_structure_update_cycles": k4_cycles,
                "spine_structure_update_mups": batch_size * 150.0 / spine_cycles,
                "k4_structure_update_mups": batch_size * 150.0 / k4_cycles,
            }
        )
    selected.sort(
        key=lambda row: (
            int(row["batch_size"]),
        )
    )
    for index, row in enumerate(selected):
        row["index"] = index
    return selected


def admitted_operation_update_pairs(
    rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
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
        selected.append(
            {
                "scenario": row["scenario"],
                "batch_size": int(row["batch_size"]),
                "spine_structure_update_cycles": int(
                    float(row["spine_structure_update_cycles"])
                ),
                "k4_structure_update_cycles": int(
                    float(row["competitor_structure_update_cycles"])
                ),
            }
        )
    selected.sort(
        key=lambda row: (
            SCENARIO_ORDER[row["scenario"]],
            int(row["batch_size"]),
        )
    )
    return selected


def all_spine_e2e_rows(
    system_rows: list[dict[str, str]],
    pairs: list[dict[str, Any]],
    wall_time_projection: dict[str, Any],
    stopped_prefix_evidence: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Keep every admitted Spine row and classify any missing K4 evidence."""
    pair_by_case = {
        (row["dataset_id"], row["algorithm"]): row for row in pairs
    }
    execution_projections = {
        row["dataset_id"]: row
        for row in wall_time_projection.get("targets", [])
    }
    preflight_projections = {
        row["dataset_id"]: row
        for row in wall_time_projection.get("preflight_targets", [])
    }
    one_round_screens = {
        row["dataset_id"]: row
        for row in wall_time_projection.get("one_round_screen_targets", [])
    }
    stopped_prefix_bounds = {
        (row["dataset_id"], row["algorithm"]): row
        for row in (stopped_prefix_evidence or {}).get("lower_bounds", [])
    }
    selected: list[dict[str, Any]] = []
    for row in system_rows:
        if (
            row.get("system") != "spine"
            or row.get("scenario") != "insert"
            or row.get("batch_size") != "8"
            or row.get("algorithm") not in ALGORITHM_LABEL
            or row.get("dataset_id") not in DATASET_LABEL
        ):
            continue
        dataset_id = row["dataset_id"]
        algorithm = row["algorithm"]
        pair = pair_by_case.get((dataset_id, algorithm))
        k4_cycles: int | None = None
        k4_status = "pending"
        evidence_kind = "none"
        projection_host_hours: float | None = None
        observed_partial_cycles: int | None = None
        if pair is not None:
            k4_cycles = int(pair["k4_cycles"])
            k4_status = "measured"
            evidence_kind = "completed_execution"
        elif (dataset_id, algorithm) in stopped_prefix_bounds:
            evidence = stopped_prefix_bounds[(dataset_id, algorithm)]
            if int(evidence["spine_cycles"]) != int(float(row["cycles"])):
                raise ValueError(
                    "stopped-prefix evidence has a different Spine denominator: "
                    f"{dataset_id}/{algorithm}"
                )
            k4_cycles = int(evidence["observed_partial_cycles"])
            k4_status = "timeout_strict_lower_bound"
            evidence_kind = str(evidence["claim_class"])
            observed_partial_cycles = k4_cycles
        elif algorithm == "weighted_sssp" and dataset_id in execution_projections:
            evidence = execution_projections[dataset_id]
            k4_cycles = int(evidence["projected_cycles"])
            k4_status = "timeout_projected"
            evidence_kind = "execution_prefix_projection"
            projection_host_hours = float(
                evidence["projected_total_hours_at_observed_rate"]
            )
            observed_partial_cycles = int(evidence["current_cycles"])
        elif algorithm == "weighted_sssp" and dataset_id in preflight_projections:
            evidence = preflight_projections[dataset_id]
            if int(wall_time_projection.get("schema_version", 0)) >= 3:
                if (
                    int(row.get("source_external", -1))
                    != int(evidence["preflight_source_external"])
                    or row.get("source_cohort")
                    != evidence["preflight_source_cohort"]
                ):
                    raise ValueError(
                        "preflight projection source differs from the Spine row: "
                        f"{dataset_id}/{algorithm}"
                    )
            k4_cycles = int(evidence["projected_cycles"])
            k4_status = "timeout_projected"
            evidence_kind = "validated_preflight_projection"
            projection_host_hours = float(
                evidence["projected_total_hours_at_calibration_rate"]
            )
        elif algorithm == "weighted_sssp" and dataset_id in one_round_screens:
            evidence = one_round_screens[dataset_id]
            k4_cycles = int(evidence["projected_cycles"])
            k4_status = "timeout_one_round_screen"
            evidence_kind = "one_round_feasibility_screen"
            projection_host_hours = float(
                evidence["projected_total_hours_at_calibration_rate"]
            )
        elif algorithm == "weighted_sssp":
            raise ValueError(
                "missing K4 SSSP row lacks timeout/projection evidence: "
                f"{dataset_id}"
            )
        spine_cycles = int(float(row["cycles"]))
        selected.append(
            {
                "dataset_id": dataset_id,
                "dataset_kind": row.get("dataset_kind", "real"),
                "dataset": DATASET_LABEL[dataset_id],
                "algorithm": algorithm,
                "algorithm_label": ALGORITHM_LABEL[algorithm],
                "label": f"{DATASET_LABEL[dataset_id]}-{ALGORITHM_LABEL[algorithm]}",
                "spine_cycles": spine_cycles,
                "k4_cycles": "" if k4_cycles is None else k4_cycles,
                "k4_status": k4_status,
                "evidence_kind": evidence_kind,
                "implied_speedup": (
                    "" if k4_cycles is None else k4_cycles / spine_cycles
                ),
                "projection_host_hours": (
                    "" if projection_host_hours is None else projection_host_hours
                ),
                "observed_partial_cycles": (
                    "" if observed_partial_cycles is None else observed_partial_cycles
                ),
            }
        )
    selected.sort(
        key=lambda row: (
            ALGORITHM_ORDER[row["algorithm"]],
            DATASET_ORDER[row["dataset_id"]],
        )
    )
    return selected


def publication_dataset_scope(
    contract: dict[str, Any], materialization_root: Path
) -> dict[str, Any]:
    rows = []
    for dataset in contract["datasets"]:
        dataset_id = str(dataset["dataset_id"])
        path = materialization_root / dataset_id / "materialization_manifest.json"
        manifest = json.loads(path.read_text(encoding="ascii"))
        if manifest.get("dataset_id") != dataset_id:
            raise ValueError(f"materialization dataset mismatch: {path}")
        capacity = manifest.get("capacity")
        if not isinstance(capacity, dict):
            raise ValueError(f"materialization lacks capacity evidence: {path}")
        rows.append(
            {
                "dataset_id": dataset_id,
                "abbreviation": str(dataset["abbreviation"]),
                "vertices": int(capacity["vertices"]),
                "spine_max_vertices": int(capacity["spine_max_vertices"]),
                "spine_full_graph_admitted": bool(
                    capacity["spine_full_graph_admitted"]
                ),
                "manifest": str(path.resolve()),
            }
        )
    maximums = {row["spine_max_vertices"] for row in rows}
    if len(maximums) != 1:
        raise ValueError("materializations disagree on Spine vertex capacity")
    return {
        "catalog_datasets": len(rows),
        "admitted_datasets": sum(
            int(row["spine_full_graph_admitted"]) for row in rows
        ),
        "spine_max_vertices": maximums.pop(),
        "rows": rows,
    }


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
    endpoint_index = next(
        (index for index, row in enumerate(rows) if row["dataset_id"] == "rmat_19_32"),
        None,
    )
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
        if endpoint_index not in {None, 0}:
            axis.axvline(
                float(endpoint_index) - 0.5,
                color="0.35",
                linestyle=":",
                linewidth=1.0,
                zorder=1,
            )
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


def render_all_spine_e2e_figure(
    rows: list[dict[str, Any]], output: Path
) -> None:
    if not rows:
        raise ValueError("formal report has no admitted Spine E2E row")
    plt = configure_matplotlib()
    figure, axes = plt.subplots(3, 1, figsize=(7.4, 7.0))
    width = 0.34
    legend_handles = None
    for axis, algorithm in zip(axes, ALGORITHM_ORDER, strict=True):
        algorithm_rows = [row for row in rows if row["algorithm"] == algorithm]
        positions = list(range(len(algorithm_rows)))
        spine_positions = [position - width / 2 for position in positions]
        k4_positions = [position + width / 2 for position in positions]
        spine_values = [float(row["spine_cycles"]) for row in algorithm_rows]
        axis.bar(
            spine_positions,
            spine_values,
            width,
            facecolor="white",
            edgecolor="#1f77b4",
            hatch="///",
            linewidth=1.0,
            label="Spine measured",
            zorder=3,
        )
        for position, row in zip(k4_positions, algorithm_rows, strict=True):
            status = row["k4_status"]
            if status == "pending":
                axis.annotate(
                    "pending",
                    (position, float(row["spine_cycles"]) * 1.35),
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    color="0.35",
                    rotation=90,
                )
                continue
            value = float(row["k4_cycles"])
            if status == "measured":
                axis.bar(
                    position,
                    value,
                    width,
                    facecolor="white",
                    edgecolor="#d95f02",
                    hatch="\\\\\\",
                    linewidth=1.0,
                    label="G+R measured",
                    zorder=3,
                )
            elif status == "timeout_projected":
                axis.bar(
                    position,
                    value,
                    width,
                    facecolor="white",
                    edgecolor="#d95f02",
                    hatch="xxx",
                    linewidth=1.0,
                    linestyle="--",
                    label="G+R projected total (T/O)",
                    zorder=3,
                )
                axis.annotate(
                    "Proj.\nT/O",
                    (position, value),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=6.5,
                    color="#9c3f00",
                )
            elif status == "timeout_one_round_screen":
                axis.scatter(
                    [position],
                    [value],
                    marker="^",
                    s=38,
                    facecolors="white",
                    edgecolors="#d95f02",
                    linewidths=1.1,
                    label="G+R one-round screen (T/O)",
                    zorder=4,
                )
                axis.annotate(
                    "1-rnd screen\nT/O",
                    (position, value),
                    xytext=(0, 4),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=6.5,
                    color="#9c3f00",
                )
            elif status == "timeout_strict_lower_bound":
                axis.scatter(
                    [position],
                    [value],
                    marker="v",
                    s=42,
                    facecolors="white",
                    edgecolors="#d95f02",
                    linewidths=1.1,
                    label="G+R strict lower bound (T/O)",
                    zorder=4,
                )
                ratio = value / float(row["spine_cycles"])
                axis.annotate(
                    f">{ratio:.1f}x\nT/O",
                    (position, value),
                    xytext=(0, 4),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=6.5,
                    color="#9c3f00",
                )
        endpoint_index = next(
            (
                index
                for index, row in enumerate(algorithm_rows)
                if row["dataset_id"] == "rmat_19_32"
            ),
            None,
        )
        if endpoint_index not in {None, 0}:
            axis.axvline(
                float(endpoint_index) - 0.5,
                color="0.35",
                linestyle=":",
                linewidth=1.0,
                zorder=1,
            )
        positive_values = spine_values + [
            float(row["k4_cycles"])
            for row in algorithm_rows
            if row["k4_cycles"] != ""
        ]
        axis.set_yscale("log")
        axis.set_ylim(min(positive_values) * 0.45, max(positive_values) * 4.0)
        axis.set_ylabel("Device cycles")
        axis.set_title(ALGORITHM_LABEL[algorithm], loc="left", fontsize=9)
        axis.set_xticks(positions, [str(row["dataset"]) for row in algorithm_rows])
        axis.grid(axis="y", linestyle="--", color="0.7", alpha=0.5, zorder=0)
        axis.tick_params(direction="in", top=True, right=True, length=4)
        if legend_handles is None:
            handles, labels = axis.get_legend_handles_labels()
            legend_handles = dict(zip(labels, handles, strict=True))
        else:
            handles, labels = axis.get_legend_handles_labels()
            legend_handles.update(dict(zip(labels, handles, strict=True)))
    from matplotlib.lines import Line2D

    legend_handles["G+R pending"] = Line2D(
        [], [], color="0.35", marker="|", linestyle="None", markersize=9
    )
    legend_order = (
        "Spine measured",
        "G+R measured",
        "G+R projected total (T/O)",
        "G+R one-round screen (T/O)",
        "G+R strict lower bound (T/O)",
        "G+R pending",
    )
    visible_legend_order = [
        label for label in legend_order if label in legend_handles
    ]
    figure.legend(
        [legend_handles[label] for label in visible_legend_order],
        visible_legend_order,
        frameon=False,
        ncols=3,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.01),
        fontsize=7.5,
    )
    axes[-1].set_xlabel("Dataset (R19 is the separate synthetic endpoint)")
    figure.tight_layout(rect=(0.0, 0.0, 1.0, 0.955))
    save_vector_figure(figure, output)
    plt.close(figure)


def render_memory_figure(rows: list[dict[str, Any]], output: Path) -> None:
    if not rows:
        raise ValueError("formal v6 memory report has no complete Spine/K4 pair")
    plt = configure_matplotlib()
    figure, axes = plt.subplots(2, 1, figsize=(7.4, 4.5), sharex=True)
    x_positions = list(range(len(rows)))
    labels = [str(row["label"]) for row in rows]
    endpoint_index = next(
        (index for index, row in enumerate(rows) if row["dataset_id"] == "rmat_19_32"),
        None,
    )
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
        if endpoint_index not in {None, 0}:
            axis.axvline(
                float(endpoint_index) - 0.5,
                color="0.35",
                linestyle=":",
                linewidth=1.0,
                zorder=1,
            )
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


def render_workload_energy_figure(
    system_rows: list[dict[str, str]],
    component_rows: list[dict[str, str]],
    output: Path,
) -> None:
    if not system_rows or not component_rows:
        raise ValueError("workload component-energy evidence is empty")
    plt = configure_matplotlib()
    from matplotlib.patches import Patch

    by_execution: dict[str, dict[str, float]] = {}
    for row in component_rows:
        by_execution.setdefault(row["execution_id"], {})[row["component"]] = float(
            row["energy_uj"]
        )
    by_group: dict[str, dict[str, dict[str, str]]] = {}
    for row in system_rows:
        by_group.setdefault(row["group_id"], {})[row["system"]] = row
    pairs = [
        (systems["spine"], systems["grasu_regraph_k4_shared"])
        for systems in by_group.values()
        if "spine" in systems and "grasu_regraph_k4_shared" in systems
    ]
    pairs.sort(
        key=lambda pair: (
            DATASET_ORDER.get(pair[0]["dataset_id"], 10_000),
            ALGORITHM_ORDER.get(pair[0]["algorithm"], 10_000),
        )
    )
    components = (
        ("hbm_subsystem", "HBM interface", "#4c78a8", "///"),
        ("update_maintenance", "Update", "#f58518", "\\\\\\"),
        ("graph_compute", "Compute", "#54a24b", "|||"),
        ("stream_fifos", "Streams/FIFOs", "#b279a2", "..."),
        ("other_user_logic", "Other logic", "#9d9d9d", "xxx"),
        ("platform_dynamic_energy_uj", "Platform dynamic", "#eeca3b", "++"),
        ("device_static_energy_uj", "Device static", "#72b7b2", "ooo"),
        ("dram_energy_uj", "HBM DRAM", "#e45756", "***"),
    )

    def values(row: dict[str, str]) -> dict[str, float]:
        result = dict(by_execution[row["execution_id"]])
        for key in (
            "platform_dynamic_energy_uj",
            "device_static_energy_uj",
            "dram_energy_uj",
        ):
            result[key] = float(row[key])
        return result

    figure, axes = plt.subplots(2, 1, figsize=(7.5, 6.2), sharex=True)
    x_positions = list(range(len(pairs)))
    width = 0.34
    labels = [
        f"{DATASET_LABEL.get(spine['dataset_id'], spine['dataset_id'])}\n"
        f"{ALGORITHM_LABEL.get(spine['algorithm'], spine['algorithm'])}"
        for spine, _ in pairs
    ]
    for offset, system_index, label, color, hatch in (
        (-width / 2, 0, "Spine", "#1f77b4", "///"),
        (width / 2, 1, "G+R K4", "#d95f02", "\\\\\\"),
    ):
        totals = [
            float(pair[system_index]["total_estimated_energy_uj"]) / 1_000.0
            for pair in pairs
        ]
        axes[0].bar(
            [position + offset for position in x_positions],
            totals,
            width,
            facecolor="white",
            edgecolor=color,
            linewidth=1.0,
            hatch=hatch,
            label=label,
        )
        bottoms = [0.0] * len(pairs)
        for key, component_label, component_color, component_hatch in components:
            shares = []
            for pair in pairs:
                row = pair[system_index]
                total = float(row["total_estimated_energy_uj"])
                shares.append(100.0 * values(row).get(key, 0.0) / total)
            axes[1].bar(
                [position + offset for position in x_positions],
                shares,
                width,
                bottom=bottoms,
                facecolor="white",
                edgecolor=component_color,
                linewidth=0.7,
                hatch=component_hatch,
            )
            bottoms = [left + right for left, right in zip(bottoms, shares, strict=True)]
    axes[0].set_yscale("log")
    axes[0].set_ylabel("Estimated energy (mJ)")
    axes[0].legend(frameon=False, ncols=2)
    axes[1].set_ylabel("Component share (%)")
    axes[1].set_ylim(0.0, 100.0)
    axes[1].set_xticks(x_positions, labels)
    axes[1].legend(
        handles=[
            Patch(
                facecolor="white",
                edgecolor=color,
                hatch=hatch,
                label=label,
            )
            for _, label, color, hatch in components
        ],
        frameon=False,
        ncols=4,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.22),
        fontsize=7.5,
    )
    for axis in axes:
        axis.grid(axis="y", linestyle="--", color="0.65", alpha=0.5, zorder=0)
        axis.tick_params(direction="in", top=True, right=True, length=4)
    figure.tight_layout(rect=(0, 0.08, 1, 1))
    save_vector_figure(figure, output)
    plt.close(figure)


def render_simulator_runtime_figure(
    rows: list[dict[str, Any]], output: Path
) -> None:
    if not rows:
        raise ValueError("formal v6 runtime report has no complete Spine/K4 pair")
    plt = configure_matplotlib()
    figure, axes = plt.subplots(2, 1, figsize=(7.4, 4.5), sharex=True)
    x_positions = list(range(len(rows)))
    labels = [str(row["label"]) for row in rows]
    width = 0.34
    endpoint_index = next(
        (index for index, row in enumerate(rows) if row["dataset_id"] == "rmat_19_32"),
        None,
    )
    spine_wall = [float(row["spine_host_wall_seconds"]) for row in rows]
    k4_wall = [float(row["k4_host_wall_seconds"]) for row in rows]
    spine_rate = [
        float(row["spine_cycles"]) / wall / 1000.0 if wall > 0.0 else 0.0
        for row, wall in zip(rows, spine_wall, strict=True)
    ]
    k4_rate = [
        float(row["k4_cycles"]) / wall / 1000.0 if wall > 0.0 else 0.0
        for row, wall in zip(rows, k4_wall, strict=True)
    ]
    for axis, spine_values, k4_values, ylabel in (
        (axes[0], spine_wall, k4_wall, "Host wall time (s)"),
        (axes[1], spine_rate, k4_rate, "Simulator throughput (kcycle/s)"),
    ):
        axis.bar(
            [position - width / 2 for position in x_positions],
            spine_values,
            width,
            facecolor="white",
            edgecolor="#1f77b4",
            hatch="///",
            linewidth=1.0,
            label="Spine",
        )
        axis.bar(
            [position + width / 2 for position in x_positions],
            k4_values,
            width,
            facecolor="white",
            edgecolor="#d95f02",
            hatch="\\\\\\",
            linewidth=1.0,
            label="G+R K4-shared",
        )
        positive = [value for value in spine_values + k4_values if value > 0.0]
        if positive and max(positive) / min(positive) >= 10.0:
            axis.set_yscale("log")
        if endpoint_index not in {None, 0}:
            axis.axvline(
                float(endpoint_index) - 0.5,
                color="0.35",
                linestyle=":",
                linewidth=1.0,
            )
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", linestyle="--", color="0.65", alpha=0.5, zorder=0)
        axis.tick_params(direction="in", top=True, right=True, length=4)
    axes[0].legend(frameon=False, ncols=2, loc="upper left")
    axes[1].set_xticks(x_positions, labels, rotation=30, ha="right")
    axes[1].set_xlabel("Dataset-algorithm pair")
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
        [float(row["spine_structure_update_mups"]) for row in rows],
        width,
        facecolor="white",
        edgecolor="#1f77b4",
        linewidth=1.0,
        hatch="///",
        label="Spine",
    )
    axis.bar(
        [position + width / 2 for position in x_positions],
        [float(row["k4_structure_update_mups"]) for row in rows],
        width,
        facecolor="white",
        edgecolor="#d95f02",
        linewidth=1.0,
        hatch="\\\\\\",
        label="G+R K4-shared",
    )
    axis.set_yscale("log")
    axis.set_ylabel("Structure-update throughput (M updates/s)")
    axis.set_xticks(x_positions, [str(row["label"]) for row in rows])
    axis.set_xlabel("User mutations per insertion batch")
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
    for index, row in enumerate(rows):
        if index and row["dataset_id"] == "rmat_19_32":
            lines.append(r"\midrule")
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


def wall_time_feasibility_tex(projection: dict[str, Any]) -> str:
    targets = list(projection.get("targets", []))
    if not targets:
        raise ValueError("wall-time projection requires at least one target")
    calibration_count = len(projection.get("calibration_rows", []))
    observed = ", ".join(
        f"{tex_escape(DATASET_LABEL.get(row['dataset_id'], row['dataset_id']))} "
        f"{float(row['projected_total_hours_at_observed_rate']):.1f} h"
        for row in targets
    )
    optimistic = ", ".join(
        f"{tex_escape(DATASET_LABEL.get(row['dataset_id'], row['dataset_id']))} "
        f"{float(row['optimistic_remaining_hours_10x_less_work_2x_rate']):.1f} h"
        for row in targets
    )
    wall_budget = float(targets[0]["wall_budget_hours"])
    preflight_targets = list(projection.get("preflight_targets", []))
    preflight_text = ""
    if preflight_targets:
        preflight_summary = ", ".join(
            f"{tex_escape(DATASET_LABEL.get(row['dataset_id'], row['dataset_id']))} "
            f"source {int(row['preflight_source_external'])}, "
            f"{int(row['oracle_minimum_supersteps'])} supersteps, "
            f"{float(row['projected_total_hours_at_calibration_rate']):.1f} h"
            for row in preflight_targets
        )
        preflight_text = (
            " The validated source-matched preflights report "
            f"{preflight_summary}. Their total-cycle estimates multiply validated "
            "oracle work by the median completed-run cycles/edge-round; they are "
            "projections, not completed cycle simulations."
        )
    one_round_targets = list(projection.get("one_round_screen_targets", []))
    one_round_text = ""
    if one_round_targets:
        projected = ", ".join(
            f"{tex_escape(DATASET_LABEL.get(row['dataset_id'], row['dataset_id']))} "
            f"{float(row['projected_total_hours_at_calibration_rate']):.1f} h"
            for row in one_round_targets
        )
        one_round_text = (
            f" For the remaining {len(one_round_targets)} unlaunched real graphs, "
            "a conservative one-round screen uses the smallest completed-run "
            "cycles/edge-round and the largest completed-run simulator rate. "
            f"Even the mandatory first full-graph round projects {projected}; "
            "these screened rows were not launched and are not performance data."
        )
    return rf"""\paragraph{{Full-graph wall-time feasibility.}}
An execution-feasibility model fitted to {calibration_count} completed,
correctness-admitted K4-shared SSSP rows projects total host times of {observed}
at the observed cycle rates. Even a stress test with ten times less work and
twice the observed simulator rate leaves {optimistic}, compared with the
{wall_budget:.0f} h campaign budget. Those full-graph executions were therefore
soft-stopped by policy. Their partial cycles and memory requests are retained
only as host-runtime evidence and never enter accelerator-performance
aggregates.{preflight_text}{one_round_text}"""


def behavior_transition_tex(
    coverage_rows: list[dict[str, str]],
) -> str:
    invalidated = [
        row
        for row in coverage_rows
        if row.get("coverage_status")
        == "invalidated_by_behavior_transition"
    ]
    if not invalidated:
        return ""
    invalidated.sort(
        key=lambda row: (
            DATASET_ORDER.get(row.get("dataset_id", ""), 10_000),
            ALGORITHM_ORDER.get(row.get("algorithm", ""), 10_000),
        )
    )
    labels = ", ".join(
        f"{tex_escape(DATASET_LABEL.get(row['dataset_id'], row['dataset_id']))}-"
        f"{tex_escape(ALGORITHM_LABEL.get(row['algorithm'], row['algorithm']))}"
        for row in invalidated
    )
    return rf"""\paragraph{{Behavior-transition coverage.}}
The following {len(invalidated)} prior Spine rows are deliberately absent
until identical-case successors pass with identical final state: {labels}.
They are not failures, zeros, or inputs to any aggregate."""


def render_tex(
    summary: dict[str, Any],
    pairs: list[dict[str, Any]],
    all_spine_rows: list[dict[str, Any]],
    update_pairs: list[dict[str, Any]],
    dataset_scope: dict[str, Any],
    rq3_summary: dict[str, Any],
    wall_time_projection: dict[str, Any],
    transition_coverage_rows: list[dict[str, str]] | None = None,
    *,
    report_version: str = "v6",
    artifact_prefix: str = "formal_v6",
    data_subdir: str = "formal_v6_primary",
) -> str:
    excluded = [
        row for row in dataset_scope["rows"]
        if not row["spine_full_graph_admitted"]
    ]
    excluded_text = ", ".join(
        f"{tex_escape(row['abbreviation'])} ({row['vertices']:,} vertices)"
        for row in excluded
    )
    wall_time_text = wall_time_feasibility_tex(wall_time_projection)
    transition_text = behavior_transition_tex(transition_coverage_rows or [])
    rq3_holdout = rq3_summary["e2e_metrics"]["real_trace_holdout"]
    return rf"""\documentclass[10pt]{{article}}
\usepackage[margin=0.72in]{{geometry}}
\usepackage{{booktabs}}
\usepackage{{graphicx}}
\usepackage{{float}}
\usepackage[hidelinks]{{hyperref}}
\hypersetup{{pdftitle={{Spine Formal-{report_version} Primary Dynamic-Graph Results}}}}
\title{{\textbf{{Spine Formal-{report_version} Primary Dynamic-Graph Results}}\\
\large Correctness-Gated Spine vs. GraSU+ReGraph K4-shared}}
\author{{Chuxiao Han}}
\date{{Live snapshot, July 2026}}
\IfFileExists{{data/{data_subdir}/pair_table.tex}}{{
  \newcommand{{\vdatadir}}{{data/{data_subdir}}}
  \newcommand{{\rqdatadir}}{{data/rq3}}
  \newcommand{{\vfigdir}}{{../figures}}
}}{{
  \newcommand{{\vdatadir}}{{docs/paper/data/{data_subdir}}}
  \newcommand{{\rqdatadir}}{{docs/paper/data/rq3}}
  \newcommand{{\vfigdir}}{{docs/figures}}
}}
\begin{{document}}
\maketitle
\begin{{abstract}}
This live report contains {summary['observed_executions']} of
{summary['expected_executions']} expected formal-{report_version} executions and
{len(pairs)} complete Spine/K4-shared pairs. Missing bars are unfinished,
policy-stopped, or behavior-transition-invalidated executions awaiting an
identical-case successor, never zero-valued measurements. Every admitted row
passes architecture-precision and independent mathematical oracles, full
final-state comparison, and request, response, and DRAM conservation.
\end{{abstract}}

\section{{Measurement contract}}
\begin{{table}}[H]
\centering
\small
\input{{\vdatadir/measurement_table.tex}}
\caption{{Measurement windows observed in admitted formal-{report_version} rows.}}
\end{{table}}

\paragraph{{Dataset scope.}}
The frozen corpus contains {dataset_scope['catalog_datasets']} real datasets;
{dataset_scope['admitted_datasets']} enter the full-graph comparison. The
remaining datasets, {excluded_text}, exceed the frozen Spine capacity of
{dataset_scope['spine_max_vertices']:,} vertices. They are capacity exclusions,
not failed or selectively removed performance rows, and no slices replace them
in the full-graph aggregate.

\paragraph{{Synthetic endpoint.}}
R19-32 (524,288 vertices and 15,483,485 unique directed edges) is reported as
a separate scalability endpoint. It is never included in a real-dataset
aggregate; the figures and cycle table place it after a dotted or ruled
separator.

\paragraph{{SSSP interpretation.}}
Spine starts from a verified persisted old-graph SSSP state and measures the
accepted update, automatic active-source discovery, incremental propagation,
and drain. The conversion-free GraSU+ReGraph baseline performs its declared
complete ReGraph execution because it has no equivalent persisted incremental
SSSP state. This is an architecture-level dynamic-service comparison, not an
identical-kernel microbenchmark.

\paragraph{{Claim boundary.}}
The frozen full matrix remains partial while expected rows are unfinished,
policy-stopped, or behavior-transition-invalidated; a row must complete or
receive a declared scope exclusion before the matrix can be called complete.
Device cycles, accepted memory bytes, and
DRAMSim3 HBM energy are simulator outputs. They do not claim cycle-for-cycle
FPGA calibration, on-chip dynamic energy, or total board power.

{transition_text}

{wall_time_text}

\paragraph{{Machine-checked evidence audit.}}
All {summary['evidence_audit']['observed_executions']} observed executions pass
their individual architecture and mathematical correctness gates, closed AXI/HBM
arbitration and traffic ledgers, and DRAM request conservation. Component-level
activity is present for all observed executions
({summary['evidence_audit']['component_activity_rows']} normalized component rows).

\clearpage
\section{{Current primary comparison}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/{artifact_prefix}_all_spine_e2e.pdf}}
\caption{{Absolute insertion-batch-8 device cycles for all
{len(all_spine_rows)} correctness-admitted current-version Spine rows. Blue
bars and unmarked orange bars are completed executions. Cross-hatched G+R bars
  marked Proj./T/O are total-cycle feasibility projections derived either from
  stopped execution prefixes or from validated source-matched host preflights;
  they are not measured performance. Upward triangles are conservative one-round
  feasibility screens, not total-cycle predictions. Downward triangles for
  SO CC and ResPR are strict monotonic device-cycle lower bounds from stopped
  incomplete executions; they are neither completed results nor projected totals.
The invalidated prior-version HW row and queued OK row have no admitted Spine
result and are therefore absent.}}
\end{{figure}}

\noindent\textit{{Projection method.}}
For a source-matched preflight row, we compute
$C_{{\mathrm{{proj}}}}=\mathrm{{median}}_i
\{{C_i/(E_iS_i)\}}\,E_{{\mathrm{{target}}}}S_{{\mathrm{{target}}}}$.
The unit cost is fitted from three completed, correctness-admitted K4-shared
SSSP executions; the target edge count and minimum superstep count come from
the complete-graph host oracle using the same source cohort as Spine. These
values are feasibility projections, not completed simulations, and are
excluded from measured cross-architecture aggregates.

\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/{artifact_prefix}_primary_ratios.pdf}}
\caption{{Ratios for complete insertion-batch-8 pairs. Values above one favor
Spine for E2E latency and indicate that GraSU+ReGraph uses more memory traffic
or HBM energy in the other panels. R19, when complete, appears to the right of
the dotted separator and is not part of the real-dataset population.}}
\end{{figure}}

\begin{{table}}[H]
\centering
\small
\input{{\vdatadir/pair_table.tex}}
\caption{{Absolute device cycles. Only cross-system final-state-matched pairs
enter this table. R19 is separated from the real datasets by a rule.}}
\end{{table}}

\clearpage
\section{{Memory traffic and request locality}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/{artifact_prefix}_memory_locality.pdf}}
\caption{{Absolute accepted-backend traffic and request-stream locality for
the same complete pairs. A request is discontinuous when its accepted address
does not continue the previous request from the same initiator, operation, and
logical HBM channel. This is not a DRAM row-buffer-miss metric. R19 is a
separate synthetic endpoint.}}
\end{{figure}}

\clearpage
\section{{Structure-update throughput}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/{artifact_prefix}_update_throughput.pdf}}
\caption{{Correctness-gated AskUbuntu full-graph insertion throughput at
batch sizes $2^6$, $2^{{10}}$, $2^{{14}}$, and $2^{{17}}$. The current snapshot
contains {len(update_pairs)} of 4 planned batch points. Spine counts maintenance through its
drained completion boundary; G+R counts GraSU PMA update completion. Both
exclude graph-algorithm iterations, equivalent to setting max-iter to zero.}}
\end{{figure}}

\paragraph{{Window boundary.}}
This figure isolates graph-structure mutation. The counters come from dedicated
correctness-gated executions and stop at each architecture's serial
update-phase boundary. We use source vertex 0, which remains isolated after all
four batches, solely to shorten the post-update SSSP correctness drain. Both
architectures enforce an update--barrier--compute order, so this source choice
cannot affect the recorded update phase. For Spine the phase includes required
level selection, L0/carry work, metadata publication, and drain; it excludes
reader, propagation, convergence, and algorithm drain. For G+R it includes the
GraSU PMA update and excludes ReGraph execution. It must not be read as
end-to-end dynamic graph service latency.

\paragraph{{Operation coverage.}}
The separate insertion, deletion, and weight-change grid at batches 1, 8, and
64 remains in \texttt{{update\_operation\_pairs.csv}} and in the fallback/RQ3
evidence. It is not mixed into this scaling plot because non-monotonic SSSP
updates exercise a bounded full-rebuild policy rather than direct insertion.

\clearpage
\section{{Simulator execution cost}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/{artifact_prefix}_simulator_runtime.pdf}}
\caption{{Host wall time and simulated-device-cycle throughput for the
correctness-matched pairs. These are simulator engineering diagnostics under
the recorded campaign concurrency, not accelerator latency or a
cross-architecture performance metric.}}
\end{{figure}}

\paragraph{{Use boundary.}}
Wall time establishes experiment feasibility and identifies simulator
optimization targets. Architecture claims use device cycles and the shared
memory model; they never use host wall time.

\clearpage
\section{{RQ3: realized work and latency}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/rq3_latency_breakdown.pdf}}
\caption{{Direct ten-stage, exclusive critical-path composition for zero-net,
shallow insertion, deep carry, residual PageRank correction, and SSSP/CC
nonmonotonic fallback. The six maintenance stages are counted in the execution
core; overlapping resolve/app intervals are assigned to the component gating
their completion. For residual PageRank, $T_{{seed}}$ also contains the serial
device correction/seed interval. Every bar closes exactly to E2E device cycles.}}
\end{{figure}}

\begin{{table}}[H]
\centering
\small
\input{{\rqdatadir/representative_table.tex}}
\caption{{Deterministically selected maximum-cycle representative of each
eligible realized-work class.}}
\end{{table}}

\clearpage
\section{{RQ3: cost-model validation}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/rq3_work_correlations.pdf}}
\caption{{Direct execution counters versus mechanism-local cycles across
{rq3_summary['work_rows']} dual-oracle-admitted executions. Blue squares are
calibration cases and red circles are holdout traces.}}
\end{{figure}}

\begin{{table}}[H]
\centering
\small
\input{{\rqdatadir/regression_table.tex}}
\caption{{Realized-work regressions. Carry work includes old payload reads,
merge inputs, and output rewrites; cursor inspection is reported separately.}}
\end{{table}}

\paragraph{{Interpretation.}}
The seven panels report every requested realized-work relation, including weak
sort-only and drain-only relations rather than hiding them. The slope and $R^2$
table distinguishes mechanisms that transfer across mixed trace classes from
those that need a richer topology- or contention-aware predictor.

\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/rq3_e2e_cost_model.pdf}}
\caption{{Calibration-only nonnegative realized-work model versus measured E2E
cycles, plus absolute residuals. The holdout contains
{int(rq3_holdout['samples'])} real-trace executions that never participate in
fitting; holdout $R^2={float(rq3_holdout['r2']):.3f}$, median absolute error
${float(rq3_holdout['median_ape_percent']):.1f}\%$, mean absolute error
${float(rq3_holdout['mape_percent']):.1f}\%$, and maximum absolute error
${float(rq3_holdout['max_ape_percent']):.1f}\%$.}}
\end{{figure}}

\paragraph{{RQ3 boundary.}}
These correlations validate internal cost structure and bottleneck attribution;
they are not cycle-for-cycle FPGA calibration or proof that one scalar predicts
every topology. The timed device boundary starts with an already-resident sorted
update buffer: host DMA and an external FLiMS sort are not included. Current
$T_{{seed}}$ measures maintenance dirty-source publication and, for residual
PageRank, the serial device correction interval covering resident rank/degree
reads, physical-edge scans, seed writes, and active-list publication before
propagation. The host supplies only the immutable oracle/work trace.

\clearpage
\section{{Implementation-level power attribution}}
\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/{artifact_prefix}_component_power.pdf}}
\caption{{Vivado post-route vectorless hierarchy power at 150 MHz. The four
bars are distinct routed builds; the Spine evidence covers SSSP only. Values
use Vivado default activity with Low confidence and establish component
attribution, not workload-calibrated energy or board power.}}
\end{{figure}}

\paragraph{{Energy boundary.}}
The workload-specific HBM energy ratios in Figure 1 come from DRAMSim3 and are
paired with the exact executions plotted there. The routed bars above establish
implementation-level component power but retain Vivado's Low-confidence
vectorless activity assumption.

\begin{{figure}}[H]
\centering
\includegraphics[width=0.98\linewidth]{{\vfigdir/{artifact_prefix}_workload_energy.pdf}}
\caption{{Complete workload-duration energy ledger for the nine matched
SSSP, CC, and residual-PageRank pairs. DRAM energy comes from each exact
DRAMSim3 command stream. FPGA hierarchy components use execution-driven active
cycles multiplied by routed vectorless power; platform dynamic and device
static use the full measured interval. All ledgers close. This is a modeled
energy estimate, not RTL-SAIF or board-power measurement. Spine CC/Residual and
G+R CC use explicitly recorded routed-algorithm proxies.}}
\end{{figure}}

\paragraph{{Energy interpretation.}}
This result has the same separation of concerns used throughout the report:
the cycle simulator supplies workload activity and duration, DRAMSim3 supplies
HBM-device energy, and implementation tools supply component power. CACTI
selected-SRAM ASIC projections remain a separate ledger and are not summed
with FPGA BRAM/URAM power. The largest remaining confidence upgrade is
algorithm-matched routed builds with RTL-derived SAIF activity.
\end{{document}}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument(
        "--update-analysis-dir", type=Path, default=DEFAULT_UPDATE_ANALYSIS
    )
    parser.add_argument(
        "--operation-update-analysis-dir",
        type=Path,
        default=DEFAULT_OPERATION_UPDATE_ANALYSIS,
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
    parser.add_argument(
        "--workload-energy-dir", type=Path, default=DEFAULT_WORKLOAD_ENERGY
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--materialization-root",
        type=Path,
        default=DEFAULT_MATERIALIZATION_ROOT,
    )
    parser.add_argument("--rq3-data-dir", type=Path, default=DEFAULT_RQ3_DATA)
    parser.add_argument(
        "--wall-time-projection",
        type=Path,
        default=DEFAULT_WALL_TIME_PROJECTION,
    )
    parser.add_argument(
        "--stopped-prefix-lower-bounds",
        type=Path,
        default=DEFAULT_STOPPED_PREFIX_LOWER_BOUNDS,
    )
    parser.add_argument("--report-version", default="v6")
    parser.add_argument("--artifact-prefix", default="formal_v6")
    args = parser.parse_args()
    summary = json.loads(
        (args.analysis_dir / "summary.json").read_text(encoding="ascii")
    )
    pairs = admitted_pairs(read_csv(args.analysis_dir / "pair_rows.csv"))
    update_pairs = admitted_update_pairs(
        read_csv(args.update_analysis_dir / "pair_rows.csv")
    )
    operation_update_pairs = admitted_operation_update_pairs(
        read_csv(args.operation_update_analysis_dir / "pair_rows.csv")
    )
    contract = json.loads(args.contract.read_text(encoding="ascii"))
    dataset_scope = publication_dataset_scope(contract, args.materialization_root)
    rq3_summary = json.loads(
        (args.rq3_data_dir / "rq3_summary.json").read_text(encoding="ascii")
    )
    rq3_summary["e2e_metrics"] = {
        row["role"]: row
        for row in read_csv(args.rq3_data_dir / "rq3_e2e_metric_rows.csv")
    }
    wall_time_projection = json.loads(
        args.wall_time_projection.read_text(encoding="ascii")
    )
    stopped_prefix_evidence = (
        json.loads(args.stopped_prefix_lower_bounds.read_text(encoding="ascii"))
        if args.stopped_prefix_lower_bounds.is_file()
        else {"lower_bounds": []}
    )
    for path in (
        args.rq3_data_dir / "representative_table.tex",
        args.rq3_data_dir / "regression_table.tex",
        args.figure_dir / "rq3_latency_breakdown.pdf",
        args.figure_dir / "rq3_work_correlations.pdf",
        args.figure_dir / "rq3_e2e_cost_model.pdf",
        args.workload_energy_dir / "system_energy.csv",
        args.workload_energy_dir / "component_energy.csv",
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    system_rows = read_csv(args.analysis_dir / "system_rows.csv")
    coverage_rows = read_csv(args.analysis_dir / "execution_coverage_rows.csv")
    all_spine_rows = all_spine_e2e_rows(
        system_rows, pairs, wall_time_projection, stopped_prefix_evidence
    )
    args.figure_dir.mkdir(parents=True, exist_ok=True)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    if not args.report_version or not args.artifact_prefix:
        raise ValueError("report version and artifact prefix must be nonempty")
    render_ratio_figure(
        pairs, args.figure_dir / f"{args.artifact_prefix}_primary_ratios"
    )
    render_all_spine_e2e_figure(
        all_spine_rows,
        args.figure_dir / f"{args.artifact_prefix}_all_spine_e2e",
    )
    render_memory_figure(
        pairs, args.figure_dir / f"{args.artifact_prefix}_memory_locality"
    )
    render_component_power_figure(
        read_csv(args.component_power),
        args.figure_dir / f"{args.artifact_prefix}_component_power",
    )
    render_workload_energy_figure(
        read_csv(args.workload_energy_dir / "system_energy.csv"),
        read_csv(args.workload_energy_dir / "component_energy.csv"),
        args.figure_dir / f"{args.artifact_prefix}_workload_energy",
    )
    render_simulator_runtime_figure(
        pairs, args.figure_dir / f"{args.artifact_prefix}_simulator_runtime"
    )
    render_update_figure(
        update_pairs, args.figure_dir / f"{args.artifact_prefix}_update_throughput"
    )
    write_csv(args.data_dir / "pairs.csv", pairs)
    write_csv(args.data_dir / "all_spine_e2e.csv", all_spine_rows)
    write_csv(args.data_dir / "update_pairs.csv", update_pairs)
    write_csv(
        args.data_dir / "update_operation_pairs.csv", operation_update_pairs
    )
    write_pair_table(args.data_dir / "pair_table.tex", pairs)
    write_measurement_table(args.data_dir / "measurement_table.tex", system_rows)
    for source_name, output_name in (
        ("system_rows.csv", "system_rows.csv"),
        ("component_activity_rows.csv", "component_activity.csv"),
        ("execution_coverage_rows.csv", "execution_coverage.csv"),
        ("correctness_groups.csv", "correctness_groups.csv"),
        ("capacity_exclusion_rows.csv", "capacity_exclusions.csv"),
        ("superseded_result_rows.csv", "superseded_results.csv"),
    ):
        write_csv(
            args.data_dir / output_name,
            read_csv(args.analysis_dir / source_name),
        )
    (args.data_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    (args.data_dir / "dataset_scope.json").write_text(
        json.dumps(dataset_scope, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    (args.data_dir / "wall_time_feasibility.json").write_text(
        json.dumps(wall_time_projection, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    args.tex.write_text(
        render_tex(
            summary,
            pairs,
            all_spine_rows,
            update_pairs,
            dataset_scope,
            rq3_summary,
            wall_time_projection,
            transition_coverage_rows=coverage_rows,
            report_version=args.report_version,
            artifact_prefix=args.artifact_prefix,
            data_subdir=args.data_dir.name,
        ),
        encoding="ascii",
    )
    print(
        f"PASS formal-{args.report_version} report inputs: "
        f"observed={summary['observed_executions']} "
        f"pairs={len(pairs)} update_pairs={len(update_pairs)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
