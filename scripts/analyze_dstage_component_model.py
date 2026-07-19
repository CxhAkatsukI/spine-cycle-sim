#!/usr/bin/env python3
"""Analyze D-stage timing with hardware-action component corrections and what-ifs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_hw_dstage_tile_timing import (  # noqa: E402
    load_dataset,
    numeric,
    predict as base_predict,
    read_rows,
    target_cycles,
)
from spine_cycle_sim.calibration.maintenance import DEFAULT_FREQ_MHZ  # noqa: E402

DEFAULT_BASE_MODEL_FIT = (
    ROOT / "results/phase3c_full_partition_analysis_20260719_175848/fit.json"
)
DEFAULT_CALIBRATION_DIRS = [
    ROOT / "results/dstage_phase3a4_replay_calibration_hw_20260719_155924",
    ROOT / "results/phase3c_full_partition_calibration_hw_20260719_175201",
]
DEFAULT_EXACT_DIR = ROOT / "results/phase4a_amazon_exact_slices_hw_20260719_224034"
DEFAULT_EVAL_GROUPS = {
    "phase3c_holdout": ROOT / "results/phase3c_full_partition_holdout_hw_20260719_175623",
    "phase3c_final": ROOT / "results/phase3c_final_validation_hw_20260719_175901",
    "phase3b_broad": ROOT / "results/phase3b_bottleneck_synthetic_hw_20260719_172739",
}
DEFAULT_EXACT_CALIBRATION_CASES = {
    "amazon_top512_exact",
    "amazon_top8192_exact",
    "amazon_densewin4096_active3933_exact",
    "amazon_stride512_exact",
}

CORRECTION_FIELDS = [
    "clipped_range_stream_correction",
    "mixed_full_peak_range_correction",
    "fallback_clipped_stream_correction",
]

COMPONENT_FIELDS = [
    "phase3c_base_current_hw",
    *CORRECTION_FIELDS,
]

PREDICTION_FIELDS = [
    "group",
    "role",
    "case",
    "sweep",
    "actual_cycles",
    "predicted_cycles",
    "base_cycles",
    "correction_cycles",
    "error_pct",
    "abs_error_pct",
    "trusted_status",
    "top_component",
    "top_component_cycles",
    "base_share_pct",
    "correction_share_pct",
    "whatif_replay_to_clipped_cycles",
    "whatif_replay_to_clipped_speedup",
    "whatif_full_sweep_half_cycles",
    "whatif_full_sweep_half_speedup",
    "median_active_records",
    "median_touched_tiles",
    "tile_clipped_ranges",
    "tile_max_clipped_ranges",
    "tile_fast_count",
    "tile_full_count",
    "tile_fallback_count",
    "tile_max_work",
    *[f"{name}_value" for name in COMPONENT_FIELDS],
    *[f"{name}_cycles" for name in COMPONENT_FIELDS],
]


@dataclass(frozen=True)
class DatasetSpec:
    group: str
    role: str
    path: Path


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


def load_labeled_dataset(spec: DatasetSpec) -> list[dict[str, Any]]:
    rows = load_dataset(spec.path)
    for row in rows:
        row["group"] = spec.group
        row["role"] = spec.role
        row["source_dir"] = str(spec.path)
    return rows


def load_labeled_datasets(specs: list[DatasetSpec]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        rows.extend(load_labeled_dataset(spec))
    return rows


def median_tile_entries(tile_rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in tile_rows:
        grouped.setdefault(str(row["case"]), []).append(row)

    out: dict[str, dict[str, float]] = {}
    for case, rows in grouped.items():
        by_repeat: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            by_repeat.setdefault(int(float(row.get("repeat", 0) or 0)), []).append(row)
        repeat_features: list[dict[str, float]] = []
        for repeat_rows in by_repeat.values():
            full_work = [
                numeric(row, "tile_work") or 0.0
                for row in repeat_rows
                if str(row.get("path", "")) == "full"
            ]
            fast_work = [
                numeric(row, "tile_work") or 0.0
                for row in repeat_rows
                if str(row.get("path", "")) == "fast"
            ]
            repeat_features.append(
                {
                    "full_tile_max_work": max(full_work, default=0.0),
                    "fast_tile_max_work": max(fast_work, default=0.0),
                }
            )
        if repeat_features:
            out[case] = {
                key: statistics.median(item[key] for item in repeat_features)
                for key in repeat_features[0]
            }
    return out


def load_tile_entry_features(directory: Path) -> dict[str, dict[str, float]]:
    tile_schedule = directory / "tile_schedule.csv"
    if not tile_schedule.exists():
        return {}
    return median_tile_entries(read_rows(tile_schedule))


def enrich_rows_with_tile_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_dir: dict[str, dict[str, dict[str, float]]] = {}
    for row in rows:
        source = str(row.get("source_dir", ""))
        if source and source not in by_dir:
            by_dir[source] = load_tile_entry_features(Path(source))
    out: list[dict[str, Any]] = []
    for row in rows:
        updated = dict(row)
        updated.update(by_dir.get(str(row.get("source_dir", "")), {}).get(str(row["case"]), {}))
        out.append(updated)
    return out


def correction_feature_values(row: dict[str, Any]) -> dict[str, float]:
    fallback_tiles = numeric(row, "tile_fallback_count") or 0.0
    clipped_ranges = numeric(row, "tile_clipped_ranges") or 0.0
    mixed_path = numeric(row, "tile_mixed_path") or 0.0
    peak_ranges = numeric(row, "tile_max_clipped_ranges") or 0.0
    return {
        "clipped_range_stream_correction": clipped_ranges,
        "mixed_full_peak_range_correction": mixed_path * peak_ranges,
        "fallback_clipped_stream_correction": fallback_tiles * clipped_ranges,
    }


def row_weight(target: float, mode: str) -> float:
    if target <= 0.0:
        return 1.0
    if mode == "none":
        return 1.0
    if mode == "sqrt_relative":
        return 1.0 / max(1.0, target)
    if mode == "relative":
        return 1.0 / max(1.0, target * target)
    raise ValueError(f"unknown weight mode: {mode}")


def fit_nonnegative_residual_model(
    rows: list[dict[str, Any]],
    base_model: dict[str, Any],
    freq_mhz: float,
    weight_mode: str,
    iterations: int,
) -> dict[str, float]:
    records: list[tuple[list[float], float]] = []
    for row in rows:
        actual = target_cycles(row, freq_mhz)
        if actual is None:
            continue
        base = base_predict(base_model, row)
        features = correction_feature_values(row)
        weight = math.sqrt(row_weight(actual, weight_mode))
        records.append(
            (
                [features[name] * weight for name in CORRECTION_FIELDS],
                (actual - base) * weight,
            )
        )
    if len(records) < 2:
        raise SystemExit("not enough calibration rows for component correction model")

    coefficients = [0.0 for _ in CORRECTION_FIELDS]
    predictions = [0.0 for _ in records]
    columns = [[record[0][index] for record in records] for index in range(len(CORRECTION_FIELDS))]
    column_norms = [sum(value * value for value in column) for column in columns]

    for _ in range(iterations):
        for index, column in enumerate(columns):
            denom = column_norms[index]
            if denom <= 0.0:
                continue
            old = coefficients[index]
            numerator = 0.0
            for row_index, value in enumerate(column):
                residual_without = records[row_index][1] - predictions[row_index] + old * value
                numerator += value * residual_without
            new = max(0.0, numerator / denom)
            if new == old:
                continue
            delta = new - old
            coefficients[index] = new
            for row_index, value in enumerate(column):
                predictions[row_index] += delta * value
    return dict(zip(CORRECTION_FIELDS, coefficients))


def correction_cycles(coefficients: dict[str, float], row: dict[str, Any]) -> dict[str, float]:
    values = correction_feature_values(row)
    return {name: coefficients[name] * values[name] for name in CORRECTION_FIELDS}


def predict_with_corrections(
    row: dict[str, Any],
    base_model: dict[str, Any],
    coefficients: dict[str, float],
) -> tuple[float, float, dict[str, float]]:
    base = base_predict(base_model, row)
    corrections = correction_cycles(coefficients, row)
    predicted = base + sum(corrections.values())
    return predicted, base, corrections


def base_whatif_replay_to_clipped(row: dict[str, Any], base_model: dict[str, Any]) -> float:
    source_tile_visits = numeric(row, "active_records_x_touched_tiles") or 0.0
    clipped_ranges = numeric(row, "tile_clipped_ranges") or 0.0
    if source_tile_visits <= 0.0:
        return base_predict(base_model, row)
    ratio = min(1.0, clipped_ranges / source_tile_visits)
    updated = dict(row)
    for feature in (
        "active_records_x_touched_tiles",
        "fast_records_x_tiles",
        "full_records_x_tiles",
        "partition_count_x_active_records",
    ):
        value = numeric(updated, feature)
        if value is not None:
            updated[feature] = value * ratio
    return base_predict(base_model, updated)


def base_whatif_full_sweep_half(row: dict[str, Any], base_model: dict[str, Any]) -> float:
    updated = dict(row)
    for feature in (
        "tile_full_swept_words",
        "tile_max_partition_swept_words",
    ):
        value = numeric(updated, feature)
        if value is not None:
            updated[feature] = value * 0.5
    return base_predict(base_model, updated)


def classify_status(abs_error: float, trusted_threshold_pct: float, max_threshold_pct: float) -> str:
    if abs_error <= trusted_threshold_pct:
        return "trusted"
    if abs_error <= max_threshold_pct:
        return "borderline"
    return "untrusted"


def prediction_row(
    row: dict[str, Any],
    base_model: dict[str, Any],
    coefficients: dict[str, float],
    freq_mhz: float,
    trusted_threshold_pct: float,
    max_threshold_pct: float,
) -> dict[str, Any] | None:
    actual = target_cycles(row, freq_mhz)
    if actual is None or actual <= 0.0:
        return None
    predicted, base, corrections = predict_with_corrections(row, base_model, coefficients)
    predicted = max(1.0, predicted)
    error_pct = (predicted - actual) / actual * 100.0
    abs_error = abs(error_pct)
    components = {
        "phase3c_base_current_hw": base,
        **corrections,
    }
    correction_total = sum(corrections.values())
    if correction_total > 0.0:
        top_component, top_cycles = max(corrections.items(), key=lambda item: item[1])
    else:
        top_component, top_cycles = "phase3c_base_current_hw", base

    replay_corrections = dict(corrections)
    replay_corrections["fallback_clipped_stream_correction"] = 0.0
    replay_whatif = base_whatif_replay_to_clipped(row, base_model) + sum(
        replay_corrections.values()
    )
    sweep_whatif = base_whatif_full_sweep_half(row, base_model) + sum(corrections.values())
    replay_whatif = min(predicted, max(1.0, replay_whatif))
    sweep_whatif = min(predicted, max(1.0, sweep_whatif))

    out = dict(row)
    out.update(
        {
            "actual_cycles": actual,
            "predicted_cycles": predicted,
            "base_cycles": base,
            "correction_cycles": correction_total,
            "error_pct": error_pct,
            "abs_error_pct": abs_error,
            "trusted_status": classify_status(
                abs_error,
                trusted_threshold_pct,
                max_threshold_pct,
            ),
            "top_component": top_component,
            "top_component_cycles": top_cycles,
            "base_share_pct": base / predicted * 100.0 if predicted > 0.0 else "",
            "correction_share_pct": correction_total / predicted * 100.0
            if predicted > 0.0
            else "",
            "whatif_replay_to_clipped_cycles": replay_whatif,
            "whatif_replay_to_clipped_speedup": predicted / replay_whatif,
            "whatif_full_sweep_half_cycles": sweep_whatif,
            "whatif_full_sweep_half_speedup": predicted / sweep_whatif,
        }
    )
    values = {
        "phase3c_base_current_hw": 1.0,
        **correction_feature_values(row),
    }
    for name in COMPONENT_FIELDS:
        out[f"{name}_value"] = values[name]
        out[f"{name}_cycles"] = components[name]
    return out


def prediction_rows(
    rows: list[dict[str, Any]],
    base_model: dict[str, Any],
    coefficients: dict[str, float],
    freq_mhz: float,
    trusted_threshold_pct: float,
    max_threshold_pct: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        prediction = prediction_row(
            row,
            base_model,
            coefficients,
            freq_mhz,
            trusted_threshold_pct,
            max_threshold_pct,
        )
        if prediction is not None:
            out.append(prediction)
    return out


def summarize_group(rows: list[dict[str, Any]], group: str) -> dict[str, Any]:
    errors = [numeric(row, "abs_error_pct") for row in rows]
    clean = [float(value) for value in errors if value is not None]
    if not clean:
        return {"group": group, "samples": 0}
    return {
        "group": group,
        "samples": len(clean),
        "median_abs_error_pct": statistics.median(clean),
        "max_abs_error_pct": max(clean),
        "within_10_pct": sum(value <= 10.0 for value in clean),
        "within_15_pct": sum(value <= 15.0 for value in clean),
        "within_20_pct": sum(value <= 20.0 for value in clean),
        "trusted": sum(row.get("trusted_status") == "trusted" for row in rows),
        "borderline": sum(row.get("trusted_status") == "borderline" for row in rows),
        "untrusted": sum(row.get("trusted_status") == "untrusted" for row in rows),
    }


def summarize_predictions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = sorted({str(row.get("group", "")) for row in rows})
    return [
        summarize_group([row for row in rows if row.get("group") == group], group)
        for group in groups
    ]


def count_by(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get(field, ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def parse_eval_group(value: str) -> DatasetSpec:
    name, separator, path = value.partition("=")
    if not separator or not name or not path:
        raise argparse.ArgumentTypeError("eval groups must be NAME=PATH")
    return DatasetSpec(name, "holdout", Path(path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-model-fit", type=Path, default=DEFAULT_BASE_MODEL_FIT)
    parser.add_argument("--calibration-dir", type=Path, action="append")
    parser.add_argument("--exact-dir", type=Path, default=DEFAULT_EXACT_DIR)
    parser.add_argument("--exact-calibration-case", action="append")
    parser.add_argument("--eval-group", type=parse_eval_group, action="append")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_FREQ_MHZ)
    parser.add_argument(
        "--weight-mode",
        choices=["none", "sqrt_relative", "relative"],
        default="sqrt_relative",
    )
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--trusted-threshold-pct", type=float, default=15.0)
    parser.add_argument("--max-threshold-pct", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    base_fit = read_json(args.base_model_fit)
    base_model = base_fit.get("model", base_fit)
    calibration_dirs = args.calibration_dir or DEFAULT_CALIBRATION_DIRS
    exact_calibration_cases = set(
        args.exact_calibration_case or DEFAULT_EXACT_CALIBRATION_CASES
    )

    calibration_rows = load_labeled_datasets(
        [
            DatasetSpec("synthetic_calibration", "calibration", path)
            for path in calibration_dirs
        ]
    )
    exact_rows = load_labeled_dataset(
        DatasetSpec("phase4a_exact", "holdout", args.exact_dir)
    )
    exact_calibration_rows: list[dict[str, Any]] = []
    exact_holdout_rows: list[dict[str, Any]] = []
    for row in exact_rows:
        updated = dict(row)
        if str(row["case"]) in exact_calibration_cases:
            updated["role"] = "calibration"
            updated["group"] = "phase4a_exact_calibration"
            exact_calibration_rows.append(updated)
        else:
            updated["role"] = "holdout"
            updated["group"] = "phase4a_exact_holdout"
            exact_holdout_rows.append(updated)

    fit_rows = enrich_rows_with_tile_entries(
        [*calibration_rows, *exact_calibration_rows]
    )
    coefficients = fit_nonnegative_residual_model(
        fit_rows,
        base_model,
        args.freq_mhz,
        args.weight_mode,
        args.iterations,
    )

    eval_specs = args.eval_group or [
        DatasetSpec(name, "holdout", path)
        for name, path in DEFAULT_EVAL_GROUPS.items()
    ]
    eval_rows = load_labeled_datasets(eval_specs)
    eval_rows = [
        row
        for row in eval_rows
        if not (
            row.get("group") == "phase4a_exact"
            and str(row["case"]) in exact_calibration_cases
        )
    ]
    all_prediction_input = enrich_rows_with_tile_entries(
        [*fit_rows, *exact_holdout_rows, *eval_rows]
    )
    baseline_predictions = prediction_rows(
        all_prediction_input,
        base_model,
        {name: 0.0 for name in CORRECTION_FIELDS},
        args.freq_mhz,
        args.trusted_threshold_pct,
        args.max_threshold_pct,
    )
    predictions = prediction_rows(
        all_prediction_input,
        base_model,
        coefficients,
        args.freq_mhz,
        args.trusted_threshold_pct,
        args.max_threshold_pct,
    )
    summaries = summarize_predictions(predictions)
    baseline_summaries = summarize_predictions(baseline_predictions)

    write_rows(args.out_dir / "baseline_predictions.csv", baseline_predictions, PREDICTION_FIELDS)
    write_rows(
        args.out_dir / "baseline_group_summary.csv",
        baseline_summaries,
        [
            "group",
            "samples",
            "median_abs_error_pct",
            "max_abs_error_pct",
            "within_10_pct",
            "within_15_pct",
            "within_20_pct",
            "trusted",
            "borderline",
            "untrusted",
        ],
    )
    write_rows(args.out_dir / "component_predictions.csv", predictions, PREDICTION_FIELDS)
    write_rows(
        args.out_dir / "group_summary.csv",
        summaries,
        [
            "group",
            "samples",
            "median_abs_error_pct",
            "max_abs_error_pct",
            "within_10_pct",
            "within_15_pct",
            "within_20_pct",
            "trusted",
            "borderline",
            "untrusted",
        ],
    )
    write_json(
        args.out_dir / "component_model.json",
        {
            "target": "median_conv_span_ms",
            "target_units": "cycles",
            "freq_mhz": args.freq_mhz,
            "base_model_fit": str(args.base_model_fit),
            "base_model_backend": base_model.get("backend", ""),
            "component_correction_backend": "nonnegative_residual_components_v1",
            "weight_mode": args.weight_mode,
            "iterations": args.iterations,
            "correction_components": coefficients,
            "component_fields": COMPONENT_FIELDS,
            "calibration_dirs": [str(path) for path in calibration_dirs],
            "exact_dir": str(args.exact_dir),
            "exact_calibration_cases": sorted(exact_calibration_cases),
            "baseline_summaries": baseline_summaries,
            "summaries": summaries,
            "top_component_counts": count_by(predictions, "top_component"),
            "trusted_status_counts": count_by(predictions, "trusted_status"),
        },
    )
    print(
        "component_model: "
        f"rows={len(predictions)} "
        f"groups={len(summaries)} "
        f"wrote={args.out_dir}"
    )
    for summary in summaries:
        print(
            f"{summary['group']}: samples={summary.get('samples')} "
            f"median={summary.get('median_abs_error_pct')} "
            f"max={summary.get('max_abs_error_pct')} "
            f"trusted={summary.get('trusted')} "
            f"borderline={summary.get('borderline')} "
            f"untrusted={summary.get('untrusted')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
