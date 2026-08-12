#!/usr/bin/env python3
"""Package the admissible current-FPGA Fig. 10 evidence and diagnostics."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CALIBRATED = (
    ROOT
    / "docs/evaluation_refresh_20260810/fig10_current_v15_with_vertices"
)
DEFAULT_ANALYSIS = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_rq3_20260812/"
    "package_with_vertices/analysis"
)
DEFAULT_OUT = (
    ROOT / "docs/evaluation_refresh_20260810/fig10_current_v15_evidence"
)

BREAKDOWN_GROUPS = (
    (
        "SI",
        (
            ("AU", "current_fpga_v12_au_weighted_sssp_u8"),
            ("SU", "current_fpga_v12_su_weighted_sssp_u8"),
            ("WK", "current_fpga_v12_wk_weighted_sssp_u8"),
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
        "Del",
        (("Syn", "current_fpga_v12_delete_fallback_sssp"),),
    ),
)

MECHANISMS = (
    (
        "sort_frontend",
        "w_sort_records",
        "t_xfer_reduce_cycles",
        "Physical update records",
        "Transfer + reduce cycles",
    ),
    (
        "carry",
        "w_carry_records",
        "t_carry_cycles",
        "Carry payload records",
        "Carry cycles",
    ),
    (
        "physical_resolve_apply",
        "m_phys_records",
        "t_resolve_app_cycles",
        "Physical edge records",
        "Resolve + apply cycles",
    ),
    (
        "seed",
        "m_seed_records",
        "t_seed_cycles",
        "Dirty-source seeds",
        "Seed cycles",
    ),
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV: {path}")
    with path.open("w", encoding="ascii", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    return float(value) if value not in (None, "") else 0.0


def work_value(row: dict[str, str], key: str) -> float:
    if key == "t_xfer_reduce_cycles":
        return number(row, "t_xfer_cycles") + number(row, "t_reduce_cycles")
    if key == "t_resolve_app_cycles":
        return number(row, "t_resolve_cycles") + number(row, "t_app_cycles")
    return number(row, key)


def select_breakdown_rows(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    by_id = {row["execution_id"]: row for row in rows}
    selected: list[dict[str, object]] = []
    for group, entries in BREAKDOWN_GROUPS:
        for tick, execution_id in entries:
            if execution_id not in by_id:
                raise ValueError(f"missing current Fig. 10 execution: {execution_id}")
            row = by_id[execution_id]
            if row.get("timing_admission") != "CALIBRATED_COMPONENT_ENVELOPE":
                raise ValueError(f"unadmitted breakdown execution: {execution_id}")
            if row.get("algorithm") != "weighted_sssp":
                raise ValueError(f"unexpected algorithm in admitted breakdown: {execution_id}")
            selected.append({**row, "figure_group": group, "figure_tick": tick})
    return selected


def mechanism_admission_rows(
    regressions: list[dict[str, str]],
) -> list[dict[str, object]]:
    by_key = {
        (row["role"], row["mechanism"]): row
        for row in regressions
        if row.get("r2", "") != ""
    }
    output: list[dict[str, object]] = []
    for mechanism in (
        "sort_frontend",
        "carry",
        "directory",
        "physical_resolve_apply",
        "seed",
        "switch",
        "drain",
    ):
        all_row = by_key[("all", mechanism)]
        holdout = by_key[("trace_holdout", mechanism)]
        samples = int(holdout["samples"])
        holdout_r2 = float(holdout["r2"])
        if samples >= 3 and holdout_r2 >= 0.9:
            status = "SUPPORTED_HOLDOUT_CORRELATION"
        elif mechanism == "carry" and samples == 2:
            status = "LIMITED_TWO_POINT_HOLDOUT"
        else:
            status = "NOT_SUPPORTED_BY_HOLDOUT_CORRELATION"
        output.append(
            {
                "mechanism": mechanism,
                "status": status,
                "all_samples": int(all_row["samples"]),
                "all_r2": float(all_row["r2"]),
                "holdout_samples": samples,
                "holdout_r2": holdout_r2,
                "holdout_slope": float(holdout["slope"]),
                "holdout_intercept": float(holdout["intercept"]),
            }
        )
    return output


def configure_matplotlib() -> Any:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "monospace",
            "font.size": 8,
            "axes.labelsize": 8.5,
            "axes.linewidth": 0.8,
            "legend.fontsize": 6.8,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "hatch.linewidth": 0.35,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    return plt


def render_breakdown(rows: list[dict[str, object]], output: Path) -> None:
    plt = configure_matplotlib()
    from matplotlib.patches import Patch

    components = (
        (
            (
                "calibrated_t_xfer_cycles",
                "calibrated_t_reduce_cycles",
                "calibrated_t_carry_cycles",
                "calibrated_t_directory_cycles",
            ),
            "Maint.",
            "#a8cf88",
            "xxxxx",
        ),
        (
            ("calibrated_t_seed_cycles", "calibrated_t_switch_cycles"),
            "Seed/pub.",
            "#f1a55b",
            "|||||",
        ),
        (("calibrated_t_resolve_cycles",), "Resolve", "#2f86bd", "/////"),
        (("calibrated_t_app_cycles",), "App", "#b7d6e8", "\\\\\\\\\\"),
        (
            ("calibrated_t_drain_cycles", "calibrated_t_sync_cycles"),
            "Drain",
            "#35a936",
            "xxxxx",
        ),
    )
    positions: list[float] = []
    labels: list[str] = []
    centers: list[tuple[str, float]] = []
    separators: list[float] = []
    cursor = 0.0
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["figure_group"]), []).append(row)
    ordered: list[dict[str, object]] = []
    for group, _entries in BREAKDOWN_GROUPS:
        group_rows = grouped[group]
        start = cursor
        for row in group_rows:
            ordered.append(row)
            positions.append(cursor)
            labels.append(str(row["figure_tick"]))
            cursor += 1.0
        centers.append((group, (start + cursor - 1.0) / 2.0))
        separators.append(cursor - 0.45)
        cursor += 0.68
    separators = separators[:-1]

    figure, axis = plt.subplots(figsize=(3.55, 1.95))
    bottoms = [0.0] * len(ordered)
    handles = []
    for keys, label, color, hatch in components:
        percentages = []
        for row in ordered:
            total = float(row["calibrated_total_cycles"])
            value = sum(float(row[key]) for key in keys)
            percentages.append(100.0 * value / total if total else 0.0)
        axis.bar(
            positions,
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
        handles.append(Patch(facecolor=color, edgecolor="black", hatch=hatch, label=label))
    for separator in separators:
        axis.axvline(separator, color="0.25", linestyle=(0, (2, 1)), linewidth=0.6)
    for group, center in centers:
        axis.text(
            center,
            -0.23,
            group,
            transform=axis.get_xaxis_transform(),
            ha="center",
            va="top",
            clip_on=False,
        )
    axis.set_xticks(positions, labels)
    axis.tick_params(axis="x", length=0, pad=1.5)
    axis.set_ylabel("Calibrated E2E cycles (%)")
    axis.set_ylim(0, 105)
    axis.set_yticks((0, 25, 50, 75, 100))
    axis.grid(axis="y", linestyle="--", color="0.75", linewidth=0.45, zorder=0)
    axis.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.23),
        ncol=5,
        frameon=False,
        handlelength=1.35,
        columnspacing=0.55,
    )
    figure.subplots_adjust(left=0.17, right=0.995, bottom=0.28, top=0.77)
    figure.savefig(output.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.02)
    figure.savefig(output.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)


def render_correlations(
    joined: list[dict[str, str]],
    regressions: list[dict[str, str]],
    output: Path,
) -> None:
    plt = configure_matplotlib()
    fits = {
        (row["role"], row["mechanism"]): row
        for row in regressions
        if row.get("r2", "") != ""
    }
    figure, axes = plt.subplots(2, 2, figsize=(7.1, 4.2))
    role_styles = {
        "trace_calibration": ("#2f86bd", "s", "Calibration"),
        "synthetic_calibration": ("#2f86bd", "^", "Synthetic calibration"),
        "trace_holdout": ("#c5652d", "o", "Holdout"),
    }
    for axis, (mechanism, x_key, y_key, x_label, y_label) in zip(
        axes.flat, MECHANISMS, strict=True
    ):
        for role, (color, marker, label) in role_styles.items():
            points = [
                (work_value(row, x_key), work_value(row, y_key))
                for row in joined
                if row["role"] == role
                and work_value(row, x_key) > 0
                and work_value(row, y_key) > 0
            ]
            if points:
                axis.scatter(
                    [point[0] for point in points],
                    [point[1] for point in points],
                    s=18,
                    marker=marker,
                    facecolors="white",
                    edgecolors=color,
                    linewidths=0.8,
                    label=label,
                    zorder=3,
                )
        holdout = fits[("trace_holdout", mechanism)]
        axis.text(
            0.04,
            0.95,
            f"holdout R2={float(holdout['r2']):.3f}, n={holdout['samples']}",
            transform=axis.transAxes,
            ha="left",
            va="top",
            fontsize=7,
        )
        axis.set_xlabel(x_label)
        axis.set_ylabel(y_label)
        axis.grid(linestyle="--", color="0.78", linewidth=0.4)
    axes[0, 0].legend(loc="lower right", frameon=False, fontsize=6.3)
    figure.tight_layout()
    figure.savefig(output.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.02)
    figure.savefig(output.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibrated-dir", type=Path, default=DEFAULT_CALIBRATED)
    parser.add_argument("--analysis-dir", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    calibrated_dir = args.calibrated_dir.resolve()
    analysis_dir = args.analysis_dir.resolve()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    calibrated_manifest_path = calibrated_dir / "manifest.json"
    calibrated_manifest = read_json(calibrated_manifest_path)
    if calibrated_manifest.get("status") != "PARTIAL_COMPONENT_CALIBRATION":
        raise ValueError("unexpected current Fig. 10 calibration status")
    if calibrated_manifest.get("holdout_status") != "FAIL":
        raise ValueError("current Fig. 10 package must preserve the v15 holdout failure")

    calibrated_path = calibrated_dir / "calibrated_breakdown_rows.csv"
    breakdown = select_breakdown_rows(read_csv(calibrated_path))
    regressions_path = analysis_dir / "rq3_regression_rows.csv"
    work_path = analysis_dir / "rq3_work_rows.csv"
    latency_path = analysis_dir / "rq3_latency_rows.csv"
    metrics_path = analysis_dir / "rq3_e2e_metric_rows.csv"
    summary_path = analysis_dir / "rq3_summary.json"
    regressions = read_csv(regressions_path)
    work_rows = read_csv(work_path)
    latency_by_id = {
        row["execution_id"]: row for row in read_csv(latency_path)
    }
    joined = [
        {**row, **latency_by_id[row["execution_id"]]}
        for row in work_rows
        if row["execution_id"] in latency_by_id
    ]
    if len(joined) != len(work_rows):
        raise ValueError("RQ3 work and latency rows do not close by execution ID")
    mechanisms = mechanism_admission_rows(regressions)
    metrics = read_csv(metrics_path)
    real_holdout = next(row for row in metrics if row["role"] == "real_trace_holdout")

    breakdown_path = output / "admitted_breakdown_rows.csv"
    mechanism_path = output / "mechanism_admission.csv"
    write_csv(breakdown_path, breakdown)
    write_csv(mechanism_path, mechanisms)
    render_breakdown(breakdown, output / "fig10_admitted_breakdown")
    render_correlations(joined, regressions, output / "fig10_realized_work_correlations")
    write_json(
        output / "cost_model_admission.json",
        {
            "status": "DIAGNOSTIC_NOT_ADMITTED",
            "reason": (
                "the current-plugin real-trace holdout has high absolute error and "
                "insufficient coverage for a publication-grade global cost model"
            ),
            "real_trace_holdout_samples": int(real_holdout["samples"]),
            "real_trace_holdout_r2": float(real_holdout["r2"]),
            "real_trace_holdout_median_absolute_error_percent": float(
                real_holdout["median_ape_percent"]
            ),
            "real_trace_holdout_max_absolute_error_percent": float(
                real_holdout["max_ape_percent"]
            ),
        },
    )
    sources = (
        calibrated_manifest_path,
        calibrated_path,
        regressions_path,
        work_path,
        latency_path,
        metrics_path,
        summary_path,
    )
    write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "status": "PARTIAL_COMPONENT_CALIBRATION",
            "admitted_breakdown_rows": len(breakdown),
            "admitted_breakdown_scope": (
                "SSSP shallow insertion, forced carry, and deletion fallback only"
            ),
            "fpga_calibration_scope": "aggregate maintenance and iterative envelopes",
            "within_envelope_scope": "execution-model timestamp attribution",
            "omitted_from_admitted_breakdown": {
                "zero_net": "current HLS lacks the paper zero-net no-repair fast path",
                "pagerank_correction": (
                    "no routed nonzero-iteration Residual PageRank component sample"
                ),
            },
            "whole_machine_holdout_status": "FAIL",
            "sources": [
                {"path": str(path), "sha256": sha256_file(path)} for path in sources
            ],
            "outputs": {
                path.name: sha256_file(path)
                for path in (
                    breakdown_path,
                    mechanism_path,
                    output / "fig10_admitted_breakdown.pdf",
                    output / "fig10_admitted_breakdown.png",
                    output / "fig10_realized_work_correlations.pdf",
                    output / "fig10_realized_work_correlations.png",
                    output / "cost_model_admission.json",
                )
            },
        },
    )
    print(
        f"FIG10_V15_PACKAGE_PARTIAL breakdown={len(breakdown)} "
        f"mechanisms={len(mechanisms)} out={output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
