#!/usr/bin/env python3
"""Fit and validate a tile-level D-stage timing model from HW logs."""

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

from spine_cycle_sim.calibration.maintenance import DEFAULT_FREQ_MHZ  # noqa: E402

TILE_FEATURES = [
    "median_active_records",
    "active_records_x_touched_tiles",
    "fast_records_x_tiles",
    "full_records_x_tiles",
    "partition_count_x_active_records",
    "tile_fast_count",
    "tile_full_count",
    "tile_fallback_count",
    "tile_mixed_path",
    "tile_partition_count",
    "tile_multi_partition",
    "tile_max_partition_tile_count",
    "tile_fast_work",
    "tile_full_work",
    "tile_fast_gathered_words",
    "tile_full_swept_words",
    "tile_scattered_words",
    "tile_max_work",
    "tile_max_clipped_ranges",
    "tile_max_partition_work",
    "tile_max_partition_swept_words",
    "tile_clipped_ranges",
    "full_work_per_active_record",
    "full_work_per_full_tile",
]

PREDICTION_FIELDS = [
    "case",
    "sweep",
    "successful_repeats",
    "median_conv_span_ms",
    "actual_cycles",
    "predicted_cycles",
    "error_pct",
    "abs_error_pct",
    *TILE_FEATURES,
]


def read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_rows(path: Path, rows: list[dict[str, Any]], preferred: list[str]) -> None:
    keys = set(preferred)
    for row in rows:
        keys.update(row.keys())
    fieldnames = preferred + sorted(keys.difference(preferred))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def numeric(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def target_cycles(row: dict[str, Any], freq_mhz: float) -> float | None:
    span_ms = numeric(row, "median_conv_span_ms")
    if span_ms is None:
        return None
    return span_ms * freq_mhz * 1000.0


def successful_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        success = numeric(row, "successful_repeats")
        repeats = numeric(row, "repeats")
        if success is None or repeats is None or success < repeats:
            continue
        if numeric(row, "median_conv_span_ms") is None:
            continue
        out.append(row)
    return out


def tile_features_by_case(tile_rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_repeat: dict[tuple[str, int], dict[str, float]] = {}
    partition_totals: dict[tuple[str, int], dict[int, dict[str, float]]] = {}
    for row in tile_rows:
        case = str(row["case"])
        repeat = int(float(row.get("repeat", 0) or 0))
        key = (case, repeat)
        out = by_repeat.setdefault(
            key,
            {
                "tile_fast_count": 0.0,
                "tile_full_count": 0.0,
                "tile_fallback_count": 0.0,
                "tile_has_fallback": 0.0,
                "tile_fast_work": 0.0,
                "tile_full_work": 0.0,
                "tile_clipped_ranges": 0.0,
                "tile_max_clipped_ranges": 0.0,
                "tile_fast_gathered_words": 0.0,
                "tile_full_swept_words": 0.0,
                "tile_scattered_words": 0.0,
                "tile_max_work": 0.0,
                "tile_mixed_path": 0.0,
                "tile_partition_count": 0.0,
                "tile_multi_partition": 0.0,
                "tile_max_partition_work": 0.0,
                "tile_max_partition_swept_words": 0.0,
                "tile_max_partition_tile_count": 0.0,
            },
        )
        partition = int(float(row.get("partition", 0) or 0))
        per_partition = partition_totals.setdefault(key, {}).setdefault(
            partition,
            {"work": 0.0, "swept_words": 0.0, "tile_count": 0.0},
        )
        path = str(row.get("path", ""))
        tile_work = numeric(row, "tile_work") or 0.0
        clipped_ranges = numeric(row, "clipped_ranges") or 0.0
        out["tile_max_work"] = max(out["tile_max_work"], tile_work)
        out["tile_clipped_ranges"] += clipped_ranges
        out["tile_max_clipped_ranges"] = max(
            out["tile_max_clipped_ranges"],
            clipped_ranges,
        )
        if numeric(row, "fallback_used") or 0.0:
            out["tile_fallback_count"] += 1.0
            out["tile_has_fallback"] = 1.0
        per_partition["work"] += tile_work
        per_partition["swept_words"] += numeric(row, "swept_vertex_words") or 0.0
        per_partition["tile_count"] += 1.0
        if path == "fast":
            out["tile_fast_count"] += 1.0
            out["tile_fast_work"] += tile_work
            out["tile_fast_gathered_words"] += numeric(row, "gathered_vertex_words") or 0.0
            out["tile_scattered_words"] += numeric(row, "scattered_vertex_words") or 0.0
        else:
            out["tile_full_count"] += 1.0
            out["tile_full_work"] += tile_work
            out["tile_full_swept_words"] += numeric(row, "swept_vertex_words") or 0.0
    for features in by_repeat.values():
        if features["tile_fast_count"] > 0 and features["tile_full_count"] > 0:
            features["tile_mixed_path"] = 1.0
    for key, features in by_repeat.items():
        partitions = partition_totals.get(key, {})
        features["tile_partition_count"] = float(len(partitions))
        features["tile_multi_partition"] = 1.0 if len(partitions) > 1 else 0.0
        if partitions:
            features["tile_max_partition_work"] = max(
                values["work"] for values in partitions.values()
            )
            features["tile_max_partition_swept_words"] = max(
                values["swept_words"] for values in partitions.values()
            )
            features["tile_max_partition_tile_count"] = max(
                values["tile_count"] for values in partitions.values()
            )

    by_case: dict[str, dict[str, float]] = {}
    for case in sorted({case for case, _ in by_repeat}):
        rows = [features for (row_case, _), features in by_repeat.items() if row_case == case]
        by_case[case] = {
            feature: statistics.median(row[feature] for row in rows)
            for feature in TILE_FEATURES
            if feature.startswith("tile_")
        }
    return by_case


def merge_features(summary_rows: list[dict[str, Any]], tile_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tile_by_case = tile_features_by_case(tile_rows)
    merged: list[dict[str, Any]] = []
    for row in summary_rows:
        case = str(row["case"])
        out = dict(row)
        out.update(tile_by_case.get(case, {}))
        for feature in TILE_FEATURES:
            out.setdefault(feature, 0.0)
        active_records = numeric(out, "median_active_records") or 0.0
        fast_tiles = numeric(out, "tile_fast_count") or 0.0
        full_tiles = numeric(out, "tile_full_count") or 0.0
        partition_count = numeric(out, "tile_partition_count") or 0.0
        full_work = numeric(out, "tile_full_work") or 0.0
        touched_tiles = (
            fast_tiles
            + full_tiles
        )
        out["active_records_x_touched_tiles"] = active_records * touched_tiles
        out["fast_records_x_tiles"] = active_records * fast_tiles
        out["full_records_x_tiles"] = active_records * full_tiles
        out["partition_count_x_active_records"] = active_records * partition_count
        out["full_work_per_active_record"] = full_work / max(1.0, active_records)
        out["full_work_per_full_tile"] = full_work / max(1.0, full_tiles)
        merged.append(out)
    return merged


def fit_weight(target: float, weight_mode: str) -> float:
    if target <= 0:
        return 1.0
    if weight_mode == "none":
        return 1.0
    if weight_mode == "sqrt_relative":
        return 1.0 / target
    if weight_mode == "relative":
        return 1.0 / (target * target)
    raise ValueError(f"unknown weight mode: {weight_mode}")


def fit_model(
    rows: list[dict[str, Any]],
    features: list[str],
    freq_mhz: float,
    alpha: float,
    weight_mode: str,
) -> dict[str, Any]:
    records: list[tuple[list[float], float]] = []
    active_features = [
        feature
        for feature in features
        if any((numeric(row, feature) or 0.0) != 0.0 for row in rows)
    ]
    for row in rows:
        y = target_cycles(row, freq_mhz)
        if y is None:
            continue
        xs = [numeric(row, feature) or 0.0 for feature in active_features]
        records.append((xs, y))
    if len(records) < 2:
        raise SystemExit("not enough calibration rows with median_conv_span_ms")

    columns = list(zip(*(record[0] for record in records)))
    means = [statistics.mean(column) for column in columns]
    stds = [statistics.pstdev(column) or 1.0 for column in columns]
    x_rows = [
        [1.0, *[(value - means[index]) / stds[index] for index, value in enumerate(xs)]]
        for xs, _ in records
    ]
    ys = [y for _, y in records]
    dim = len(active_features) + 1
    xtx = [[0.0 for _ in range(dim)] for _ in range(dim)]
    xty = [0.0 for _ in range(dim)]
    for x_row, y in zip(x_rows, ys):
        weight = fit_weight(y, weight_mode)
        for i in range(dim):
            xty[i] += weight * x_row[i] * y
            for j in range(dim):
                xtx[i][j] += weight * x_row[i] * x_row[j]
    for i in range(1, dim):
        xtx[i][i] += alpha
    beta = solve_linear(xtx, xty)
    return {
        "target": "median_conv_span_ms",
        "target_units": "cycles",
        "backend": "tile_schedule_v1",
        "freq_mhz": freq_mhz,
        "alpha": alpha,
        "weight_mode": weight_mode,
        "features": active_features,
        "means": dict(zip(active_features, means)),
        "stds": dict(zip(active_features, stds)),
        "intercept": beta[0],
        "standardized_coefficients": {
            feature: beta[index + 1] for index, feature in enumerate(active_features)
        },
    }


def predict(model: dict[str, Any], row: dict[str, Any]) -> float:
    pred = float(model["intercept"])
    for feature in model["features"]:
        value = numeric(row, feature) or 0.0
        mean = float(model["means"][feature])
        std = float(model["stds"][feature]) or 1.0
        coef = float(model["standardized_coefficients"][feature])
        pred += coef * ((value - mean) / std)
    return pred


def prediction_rows(rows: list[dict[str, Any]], model: dict[str, Any], freq_mhz: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        actual = target_cycles(row, freq_mhz)
        if actual is None or actual == 0.0:
            continue
        pred = predict(model, row)
        error_pct = (pred - actual) / actual * 100.0
        updated = dict(row)
        updated.update(
            {
                "actual_cycles": actual,
                "predicted_cycles": pred,
                "error_pct": error_pct,
                "abs_error_pct": abs(error_pct),
            }
        )
        out.append(updated)
    return out


def summarize_predictions(rows: list[dict[str, Any]], max_threshold_pct: float) -> dict[str, Any]:
    errors = [numeric(row, "abs_error_pct") for row in rows]
    clean = [error for error in errors if error is not None]
    if not clean:
        return {"samples": 0}
    return {
        "samples": len(clean),
        "median_abs_pct_error": statistics.median(clean),
        "max_abs_pct_error": max(clean),
        "within_10_pct": sum(error <= 10.0 for error in clean),
        "within_20_pct": sum(error <= 20.0 for error in clean),
        "outliers_over_threshold": [
            row["case"]
            for row in rows
            if (numeric(row, "abs_error_pct") or 0.0) > max_threshold_pct
        ],
    }


def solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    aug = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        if abs(aug[pivot][col]) < 1.0e-12:
            aug[pivot][col] = 1.0e-12
        aug[col], aug[pivot] = aug[pivot], aug[col]
        denom = aug[col][col]
        for item in range(col, n + 1):
            aug[col][item] /= denom
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            for item in range(col, n + 1):
                aug[row][item] -= factor * aug[col][item]
    return [aug[row][n] for row in range(n)]


def load_dataset(directory: Path) -> list[dict[str, Any]]:
    summary = directory / "summary.csv"
    tile_schedule = directory / "tile_schedule.csv"
    if not summary.exists():
        raise SystemExit(f"missing summary.csv: {summary}")
    if not tile_schedule.exists():
        raise SystemExit(f"missing tile_schedule.csv: {tile_schedule}")
    return merge_features(successful_rows(read_rows(summary)), read_rows(tile_schedule))


def load_datasets(directories: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory in directories:
        rows.extend(load_dataset(directory))
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-dir", type=Path, action="append", required=True)
    parser.add_argument("--holdout-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_FREQ_MHZ)
    parser.add_argument("--alpha", type=float, default=1.0e-6)
    parser.add_argument(
        "--weight-mode",
        choices=["none", "sqrt_relative", "relative"],
        default="none",
        help="Regression weighting. sqrt_relative uses 1/target_cycles.",
    )
    parser.add_argument("--max-threshold-pct", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir or args.calibration_dir[0] / "tile_timing_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    calibration_rows = load_datasets(args.calibration_dir)
    model = fit_model(
        calibration_rows,
        TILE_FEATURES,
        args.freq_mhz,
        args.alpha,
        args.weight_mode,
    )
    calibration_predictions = prediction_rows(calibration_rows, model, args.freq_mhz)
    calibration_report = summarize_predictions(
        calibration_predictions,
        args.max_threshold_pct,
    )
    fit: dict[str, Any] = {
        "model": model,
        "calibration": calibration_report,
        "calibration_dirs": [str(path) for path in args.calibration_dir],
    }
    write_rows(
        out_dir / "calibration_predictions.csv",
        calibration_predictions,
        PREDICTION_FIELDS,
    )
    print(
        "calibration: "
        f"samples={calibration_report.get('samples')} "
        f"median_abs_pct_error={calibration_report.get('median_abs_pct_error')} "
        f"max_abs_pct_error={calibration_report.get('max_abs_pct_error')}"
    )

    if args.holdout_dir:
        holdout_rows = load_dataset(args.holdout_dir)
        holdout_predictions = prediction_rows(holdout_rows, model, args.freq_mhz)
        holdout_report = summarize_predictions(holdout_predictions, args.max_threshold_pct)
        fit["holdout"] = holdout_report
        write_rows(
            out_dir / "holdout_predictions.csv",
            holdout_predictions,
            PREDICTION_FIELDS,
        )
        print(
            "holdout: "
            f"samples={holdout_report.get('samples')} "
            f"median_abs_pct_error={holdout_report.get('median_abs_pct_error')} "
            f"max_abs_pct_error={holdout_report.get('max_abs_pct_error')} "
            f"within_10={holdout_report.get('within_10_pct')}/{holdout_report.get('samples')} "
            f"within_20={holdout_report.get('within_20_pct')}/{holdout_report.get('samples')}"
        )

    write_json(out_dir / "fit.json", fit)
    print(f"wrote fit: {out_dir / 'fit.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
