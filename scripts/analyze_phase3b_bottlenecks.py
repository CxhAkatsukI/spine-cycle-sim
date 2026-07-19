#!/usr/bin/env python3
"""Classify Phase 3B HW bottlenecks and D-stage prediction trust."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_hw_dstage_tile_timing import (  # noqa: E402
    PREDICTION_FIELDS,
    load_dataset,
    numeric,
    prediction_rows,
    summarize_predictions,
)
from spine_cycle_sim.calibration.maintenance import DEFAULT_FREQ_MHZ  # noqa: E402

DEFAULT_MODEL_FIT = (
    ROOT
    / "results/dstage_phase3a4_replay_analysis_weighted_20260719_160621/fit.json"
)

REPORT_FIELDS = [
    "case",
    "sweep",
    "successful_repeats",
    "trusted_status",
    "gap_class",
    "bottleneck",
    "median_kernel_e2e_ms",
    "median_maint_ms",
    "median_conv_span_ms",
    "median_reader_ms",
    "maint_share_pct",
    "dstage_share_pct",
    "reader_share_of_dstage_pct",
    "actual_cycles",
    "predicted_cycles",
    "error_pct",
    "abs_error_pct",
    "replay_proxy",
    "median_input_edges",
    "median_persisted",
    "median_batches",
    "median_target_level",
    "median_active_sources",
    "median_active_records",
    "median_touched_tiles",
    "median_fast_path_tiles",
    "median_full_path_tiles",
    "tile_fast_count",
    "tile_full_count",
    "tile_fallback_count",
    "tile_fast_work",
    "tile_full_work",
    "tile_full_swept_words",
    "tile_max_work",
    "tile_clipped_ranges",
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_rows(path: Path, rows: list[dict[str, Any]], preferred: list[str]) -> None:
    keys = set(preferred)
    for row in rows:
        keys.update(row)
    fieldnames = preferred + sorted(keys.difference(preferred))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def pct(numerator: float | None, denominator: float | None) -> float:
    if numerator is None or denominator is None or denominator <= 0.0:
        return 0.0
    return numerator / denominator * 100.0


def replay_proxy(row: dict[str, Any]) -> float:
    value = numeric(row, "active_records_x_touched_tiles")
    if value is not None:
        return value
    active = numeric(row, "median_active_records") or 0.0
    touched = numeric(row, "median_touched_tiles") or 0.0
    return active * touched


def is_multibatch_or_level(row: dict[str, Any]) -> bool:
    batches = numeric(row, "median_batches") or 0.0
    target_level = numeric(row, "median_target_level") or 0.0
    sweep = str(row.get("sweep", ""))
    return batches > 1.0 or target_level > 0.0 or "multibatch" in sweep


def classify_bottleneck(row: dict[str, Any]) -> str:
    maint = numeric(row, "median_maint_ms")
    dstage = numeric(row, "median_conv_span_ms")
    reader = numeric(row, "median_reader_ms")
    fast_tiles = numeric(row, "median_fast_path_tiles") or numeric(row, "tile_fast_count") or 0.0
    full_tiles = numeric(row, "median_full_path_tiles") or numeric(row, "tile_full_count") or 0.0
    proxy = replay_proxy(row)

    if maint is not None and dstage is not None:
        if maint >= dstage * 1.25:
            return "maintenance_dominant"
        if dstage >= maint * 1.25:
            if reader is not None and reader >= dstage * 0.85:
                if proxy >= 65_536:
                    return "dstage_reader_replay_dominant"
                return "dstage_reader_dominant"
            if full_tiles > fast_tiles:
                return "dstage_full_tile_dominant"
            if proxy >= 65_536:
                return "dstage_replay_dominant"
            return "dstage_compute_or_fixed_dominant"
    if full_tiles > 0 and fast_tiles > 0:
        return "mixed_fast_full"
    return "balanced_or_small_fixed"


def classify_gap(row: dict[str, Any], trusted_threshold_pct: float) -> str:
    success = numeric(row, "successful_repeats") or 0.0
    repeats = numeric(row, "repeats") or success
    abs_error = numeric(row, "abs_error_pct")
    if success < repeats:
        return "hw_failure_or_timeout"
    if is_multibatch_or_level(row):
        return "multibatch_level_state_diagnostic"
    if abs_error is None:
        return "missing_prediction"
    if abs_error <= trusted_threshold_pct:
        return "within_current_dstage_model"
    proxy = replay_proxy(row)
    reader_share = numeric(row, "reader_share_of_dstage_pct") or 0.0
    fast_tiles = numeric(row, "median_fast_path_tiles") or numeric(row, "tile_fast_count") or 0.0
    full_tiles = numeric(row, "median_full_path_tiles") or numeric(row, "tile_full_count") or 0.0
    max_work = numeric(row, "tile_max_work") or 0.0
    sweep = str(row.get("sweep", ""))
    if proxy > 65_536:
        return "replay_fallback_extrapolation_gap"
    if "multi_partition" in sweep:
        return "multi_partition_interaction_gap"
    if fast_tiles > 0 and full_tiles > 0:
        return "mixed_fast_full_interaction_gap"
    if full_tiles > 0 and proxy <= 128.0:
        return "large_full_tile_low_replay_gap"
    if full_tiles > 0 and max_work >= 4097.0:
        return "full_tile_work_shape_gap"
    if fast_tiles > 1 and proxy <= 128.0:
        return "small_multitile_fixed_overhead_gap"
    if reader_share >= 85.0:
        return "reader_stream_or_axi_gap"
    return "unclassified_dstage_gap"


def trusted_status(row: dict[str, Any], trusted_threshold_pct: float, max_threshold_pct: float) -> str:
    gap = str(row.get("gap_class", ""))
    abs_error = numeric(row, "abs_error_pct")
    if gap == "hw_failure_or_timeout":
        return "failed"
    if gap == "multibatch_level_state_diagnostic":
        return "diagnostic_out_of_scope"
    if abs_error is None:
        return "unknown"
    if abs_error <= trusted_threshold_pct:
        return "trusted"
    if abs_error <= max_threshold_pct:
        return "borderline"
    return "untrusted"


def enrich_predictions(
    rows: list[dict[str, Any]],
    trusted_threshold_pct: float,
    max_threshold_pct: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        updated = dict(row)
        kernel = numeric(updated, "median_kernel_e2e_ms")
        maint = numeric(updated, "median_maint_ms")
        dstage = numeric(updated, "median_conv_span_ms")
        reader = numeric(updated, "median_reader_ms")
        updated["maint_share_pct"] = pct(maint, kernel)
        updated["dstage_share_pct"] = pct(dstage, kernel)
        updated["reader_share_of_dstage_pct"] = pct(reader, dstage)
        updated["replay_proxy"] = replay_proxy(updated)
        updated["bottleneck"] = classify_bottleneck(updated)
        updated["gap_class"] = classify_gap(updated, trusted_threshold_pct)
        updated["trusted_status"] = trusted_status(
            updated,
            trusted_threshold_pct,
            max_threshold_pct,
        )
        out.append(updated)
    return out


def count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field, ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def summarize_by_sweep(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("sweep", "")), []).append(row)
    out: list[dict[str, Any]] = []
    for sweep, group in sorted(grouped.items()):
        errors = [
            numeric(row, "abs_error_pct")
            for row in group
            if numeric(row, "abs_error_pct") is not None
        ]
        clean = [float(error) for error in errors if error is not None]
        out.append(
            {
                "sweep": sweep,
                "samples": len(group),
                "median_abs_error_pct": statistics.median(clean) if clean else "",
                "max_abs_error_pct": max(clean) if clean else "",
                "trusted": sum(row.get("trusted_status") == "trusted" for row in group),
                "borderline": sum(
                    row.get("trusted_status") == "borderline" for row in group
                ),
                "untrusted": sum(row.get("trusted_status") == "untrusted" for row in group),
                "diagnostic_out_of_scope": sum(
                    row.get("trusted_status") == "diagnostic_out_of_scope"
                    for row in group
                ),
            }
        )
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hw-dir", type=Path, required=True)
    parser.add_argument("--model-fit", type=Path, default=DEFAULT_MODEL_FIT)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_FREQ_MHZ)
    parser.add_argument("--trusted-threshold-pct", type=float, default=20.0)
    parser.add_argument("--max-threshold-pct", type=float, default=25.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir or args.hw_dir / "phase3b_bottleneck_report"
    out_dir.mkdir(parents=True, exist_ok=True)

    fit = read_json(args.model_fit)
    model = fit.get("model", fit)
    rows = load_dataset(args.hw_dir)
    predictions = prediction_rows(rows, model, args.freq_mhz)
    report_rows = enrich_predictions(
        predictions,
        args.trusted_threshold_pct,
        args.max_threshold_pct,
    )
    prediction_summary = summarize_predictions(
        predictions,
        args.max_threshold_pct,
    )
    sweep_summary = summarize_by_sweep(report_rows)
    summary = {
        "hw_dir": str(args.hw_dir),
        "model_fit": str(args.model_fit),
        "freq_mhz": args.freq_mhz,
        "trusted_threshold_pct": args.trusted_threshold_pct,
        "max_threshold_pct": args.max_threshold_pct,
        "prediction": prediction_summary,
        "trusted_status_counts": count_by(report_rows, "trusted_status"),
        "gap_class_counts": count_by(report_rows, "gap_class"),
        "bottleneck_counts": count_by(report_rows, "bottleneck"),
        "outliers": [
            {
                "case": row["case"],
                "sweep": row["sweep"],
                "abs_error_pct": numeric(row, "abs_error_pct"),
                "gap_class": row["gap_class"],
                "bottleneck": row["bottleneck"],
            }
            for row in report_rows
            if (numeric(row, "abs_error_pct") or 0.0) > args.max_threshold_pct
        ],
    }

    write_rows(out_dir / "predictions.csv", predictions, PREDICTION_FIELDS)
    write_rows(out_dir / "bottleneck_report.csv", report_rows, REPORT_FIELDS)
    write_rows(out_dir / "sweep_summary.csv", sweep_summary, ["sweep"])
    write_json(out_dir / "summary.json", summary)
    print(
        "phase3b_report: "
        f"samples={prediction_summary.get('samples')} "
        f"median_abs_pct_error={prediction_summary.get('median_abs_pct_error')} "
        f"max_abs_pct_error={prediction_summary.get('max_abs_pct_error')}"
    )
    print(f"trusted_status_counts={summary['trusted_status_counts']}")
    print(f"bottleneck_counts={summary['bottleneck_counts']}")
    print(f"wrote report: {out_dir / 'bottleneck_report.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
