#!/usr/bin/env python3
"""Fit and validate a D-stage timing model from HW readiness/calibration logs."""

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

DEFAULT_FEATURES = [
    "median_active_records",
    "median_gathered_vertex_words",
    "median_swept_vertex_words",
    "median_scattered_vertex_words",
    "median_fast_path_tiles",
    "median_full_path_tiles",
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
    *DEFAULT_FEATURES,
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


def fit_model(rows: list[dict[str, Any]], features: list[str], freq_mhz: float, alpha: float) -> dict[str, Any]:
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
        for i in range(dim):
            xty[i] += x_row[i] * y
            for j in range(dim):
                xtx[i][j] += x_row[i] * x_row[j]
    for i in range(1, dim):
        xtx[i][i] += alpha
    beta = solve_linear(xtx, xty)
    model = {
        "target": "median_conv_span_ms",
        "target_units": "cycles",
        "freq_mhz": freq_mhz,
        "alpha": alpha,
        "features": active_features,
        "means": dict(zip(active_features, means)),
        "stds": dict(zip(active_features, stds)),
        "intercept": beta[0],
        "standardized_coefficients": {
            feature: beta[index + 1] for index, feature in enumerate(active_features)
        },
    }
    return model


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration-dir", type=Path, required=True)
    parser.add_argument("--holdout-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_FREQ_MHZ)
    parser.add_argument("--alpha", type=float, default=1.0e-6)
    parser.add_argument("--max-threshold-pct", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir or args.calibration_dir / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    calibration_summary = args.calibration_dir / "summary.csv"
    if not calibration_summary.exists():
        raise SystemExit(f"missing calibration summary.csv: {calibration_summary}")
    calibration_rows = successful_rows(read_rows(calibration_summary))
    model = fit_model(calibration_rows, DEFAULT_FEATURES, args.freq_mhz, args.alpha)
    calibration_predictions = prediction_rows(calibration_rows, model, args.freq_mhz)
    calibration_report = summarize_predictions(calibration_predictions, args.max_threshold_pct)

    fit: dict[str, Any] = {
        "model": model,
        "calibration": calibration_report,
    }
    write_rows(out_dir / "calibration_predictions.csv", calibration_predictions, PREDICTION_FIELDS)

    if args.holdout_dir:
        holdout_summary = args.holdout_dir / "summary.csv"
        if not holdout_summary.exists():
            raise SystemExit(f"missing holdout summary.csv: {holdout_summary}")
        holdout_rows = successful_rows(read_rows(holdout_summary))
        holdout_predictions = prediction_rows(holdout_rows, model, args.freq_mhz)
        holdout_report = summarize_predictions(holdout_predictions, args.max_threshold_pct)
        fit["holdout"] = holdout_report
        write_rows(out_dir / "holdout_predictions.csv", holdout_predictions, PREDICTION_FIELDS)

    write_json(out_dir / "fit.json", fit)
    print(f"wrote fit: {out_dir / 'fit.json'}")
    print(f"wrote calibration predictions: {out_dir / 'calibration_predictions.csv'}")
    print(
        "calibration: "
        f"samples={calibration_report.get('samples')} "
        f"median_abs_pct_error={calibration_report.get('median_abs_pct_error')} "
        f"max_abs_pct_error={calibration_report.get('max_abs_pct_error')}"
    )
    if "holdout" in fit:
        holdout = fit["holdout"]
        print(f"wrote holdout predictions: {out_dir / 'holdout_predictions.csv'}")
        print(
            "holdout: "
            f"samples={holdout.get('samples')} "
            f"median_abs_pct_error={holdout.get('median_abs_pct_error')} "
            f"max_abs_pct_error={holdout.get('max_abs_pct_error')} "
            f"within_10={holdout.get('within_10_pct')}/{holdout.get('samples')} "
            f"within_20={holdout.get('within_20_pct')}/{holdout.get('samples')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
