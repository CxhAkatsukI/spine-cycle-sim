#!/usr/bin/env python3
"""Compose the E2E component timing model from existing calibrated sub-models.

This analysis layer reuses:
  * the Phase 4C B-stage / maintenance component model (B -> median_maint_ms),
  * the D-stage tile component model (D_span -> median_conv_span_ms),
  * a reader sub-model fit here (R -> median_reader_ms), and
  * a residual overhead term,
and assembles a serial ledger for kernel end-to-end time:

    serial_pred = B_pred + D_span_pred + overhead_model

validated primarily against the real exact Amazon slices' median_kernel_e2e_ms.
It does not modify the HLS kernel, rebuild the xclbin, or change
``SpineV0Simulator.run()``.

Usage:
    python3 scripts/analyze_e2e_component_model.py --out-dir <DIR>
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_dstage_component_model import (  # noqa: E402
    CORRECTION_FIELDS,
    DEFAULT_BASE_MODEL_FIT,
    DEFAULT_CALIBRATION_DIRS,
    DEFAULT_EVAL_GROUPS,
    DEFAULT_EXACT_CALIBRATION_CASES,
    DatasetSpec,
    base_whatif_full_sweep_half,
    base_whatif_replay_to_clipped,
    correction_cycles,
    enrich_rows_with_tile_entries,
    fit_nonnegative_residual_model,
    load_labeled_dataset,
    predict_with_corrections,
    read_json,
)
from scripts.analyze_hw_dstage_tile_timing import load_dataset, numeric  # noqa: E402
from scripts.analyze_reader_component_model import (  # noqa: E402
    DEFAULT_CALIBRATION_DIRS as READER_V2_CALIBRATION_DIRS,
)
from spine_cycle_sim.calibration import (  # noqa: E402
    E2E_GROUP_SUMMARY_FIELD_ORDER,
    E2EInputs,
    READER_COMPONENT_ORDER,
    READER_WHATIF_ORDER,
    build_e2e_prediction,
    component_summary_row,
    compute_overhead_model,
    e2e_group_summary,
    e2e_prediction_field_order,
    fit_component_model,
    fit_reader_component_model,
    fit_reader_model,
    load_default_evidence,
    load_reader_rows,
    reader_component_model_to_dict,
    reader_model_to_dict,
    write_json,
    write_rows_csv,
)
from spine_cycle_sim.calibration.maintenance import DEFAULT_FREQ_MHZ  # noqa: E402

DEFAULT_EXACT_DIR = ROOT / "results/phase4a_amazon_exact_slices_hw_20260719_224034"
DEFAULT_REALLIKE_DIR = ROOT / "results/phase3d_amazon_slices_hw_20260719_220659"
DEFAULT_OVERHEAD_DIRS = [
    ROOT / "results/phase3c_full_partition_calibration_hw_20260719_175201",
    ROOT / "results/dstage_phase3a4_replay_calibration_hw_20260719_155924",
    ROOT / "results/phase3b_bottleneck_synthetic_hw_20260719_172739",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, default=ROOT)
    parser.add_argument("--exact-dir", type=Path, default=DEFAULT_EXACT_DIR)
    parser.add_argument("--reallike-dir", type=Path, default=DEFAULT_REALLIKE_DIR)
    parser.add_argument("--base-model-fit", type=Path, default=DEFAULT_BASE_MODEL_FIT)
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_FREQ_MHZ)
    parser.add_argument("--trusted-threshold-pct", type=float, default=15.0)
    parser.add_argument(
        "--reader-model",
        choices=["v2", "v1"],
        default="v2",
        help=(
            "Reader sub-model for R_pred and the downstream report. v2 is the "
            "Phase 5A structured non-negative component model; v1 is the E2E free-OLS "
            "reader model. R is diagnostic and never enters the serial total either way."
        ),
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# D-span predictor (reuse the D-stage component model)
# ---------------------------------------------------------------------------


def build_dspan_predictor(base_model_fit: Path, freq_mhz: float):
    base = read_json(base_model_fit)
    base_model = base.get("model", base)
    calibration = enrich_rows_with_tile_entries(
        [
            row
            for path in DEFAULT_CALIBRATION_DIRS
            for row in load_labeled_dataset(DatasetSpec("synthetic_calibration", "calibration", path))
        ]
    )
    exact_rows = load_labeled_dataset(DatasetSpec("phase4a", "holdout", DEFAULT_EXACT_DIR))
    exact_cal = [
        dict(row, role="calibration")
        for row in exact_rows
        if str(row["case"]) in DEFAULT_EXACT_CALIBRATION_CASES
    ]
    coefficients = fit_nonnegative_residual_model(
        enrich_rows_with_tile_entries([*calibration, *exact_cal]),
        base_model,
        freq_mhz,
        "sqrt_relative",
        5000,
    )

    def predict(row: dict[str, Any]) -> dict[str, float]:
        predicted, base_cycles, corrections = predict_with_corrections(
            row, base_model, coefficients
        )
        predicted = max(1.0, predicted)
        replay_corrections = dict(corrections)
        replay_corrections["fallback_clipped_stream_correction"] = 0.0
        replay = base_whatif_replay_to_clipped(row, base_model) + sum(replay_corrections.values())
        sweep = base_whatif_full_sweep_half(row, base_model) + sum(corrections.values())
        return {
            "d_span": predicted,
            "replay_to_clipped": min(predicted, max(1.0, replay)),
            "full_sweep_half": min(predicted, max(1.0, sweep)),
        }

    return predict, coefficients, str(base_model.get("backend", ""))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    freq = args.freq_mhz

    # --- B-stage model (Phase 4C) --------------------------------------------
    b_records = load_default_evidence(root=args.evidence_root, freq_mhz=freq)
    b_model = fit_component_model(b_records, freq_mhz=freq)
    b_by_case: dict[str, dict[str, Any]] = {}
    for record in b_records:
        prediction = b_model.predict(record)
        b_by_case[record.case] = {
            "pred": prediction["predicted_cycles"],
            "edges": record.batch_edges,
            "jitter": record.jitter_pct,
            "whatifs": {
                name: entry["speedup"] for name, entry in prediction["whatifs"].items()
            },
        }

    # --- D-span model (reuse D-stage component model) ------------------------
    dspan_predict, d_coefficients, d_backend = build_dspan_predictor(
        args.base_model_fit, freq
    )

    # --- Reader (R) model ----------------------------------------------------
    exact_rows = load_dataset(args.exact_dir)
    reallike_rows = load_dataset(args.reallike_dir)
    reader_v1_calibration = reallike_rows + [
        row for row in exact_rows if str(row["case"]) in DEFAULT_EXACT_CALIBRATION_CASES
    ]
    reader_v2_model = None
    reader_v2_calibration: list[dict[str, Any]] = []
    if args.reader_model == "v2":
        for raw in READER_V2_CALIBRATION_DIRS:
            path = Path(raw)
            if not path.is_absolute():
                path = args.evidence_root / path
            reader_v2_calibration.extend(load_reader_rows(path))
        reader_v2_model = fit_reader_component_model(reader_v2_calibration, freq_mhz=freq)
        reader_predict = reader_v2_model.predicted_cycles
        reader_meta = reader_component_model_to_dict(reader_v2_model)
        reader_calibration = reader_v2_calibration
    else:
        reader_v1_model = fit_reader_model(reader_v1_calibration, freq_mhz=freq)
        reader_predict = reader_v1_model.predict
        reader_meta = reader_model_to_dict(reader_v1_model)
        reader_calibration = reader_v1_calibration

    # --- Overhead model ------------------------------------------------------
    overhead_rows = [
        row
        for path in DEFAULT_OVERHEAD_DIRS
        for row in load_labeled_dataset(DatasetSpec("overhead_cal", "calibration", path))
    ]
    overhead_model = compute_overhead_model(overhead_rows, freq_mhz=freq)

    # --- Assemble E2E ledger for the real exact slices -----------------------
    exact_enriched = enrich_rows_with_tile_entries(exact_rows)
    predictions: list[dict[str, Any]] = []
    for row in exact_enriched:
        case = str(row["case"])
        b_info = b_by_case.get(case)
        if b_info is None:
            continue  # B out of the calibrated (one-partition L0) domain
        role = (
            "calibration"
            if case in DEFAULT_EXACT_CALIBRATION_CASES
            else "holdout"
        )
        d_pred = dspan_predict(row)
        inp = E2EInputs(
            group="phase4a_amazon_real",
            role=role,
            case=case,
            sweep=str(row.get("sweep", "real_slice_exact")),
            batch_edges=float(b_info["edges"]),
            jitter_pct=float(b_info["jitter"]),
            B_actual=_ms(row, "median_maint_ms", freq),
            R_actual=_ms(row, "median_reader_ms", freq),
            D_span_actual=_ms(row, "median_conv_span_ms", freq),
            kernel_e2e_actual=_ms(row, "median_kernel_e2e_ms", freq),
            B_pred=float(b_info["pred"]),
            R_pred=reader_predict(row),
            D_span_pred=d_pred["d_span"],
            overhead_model=overhead_model,
            b_whatif_speedups=b_info["whatifs"],
            d_whatif_cycles={
                "full_sweep_half": d_pred["full_sweep_half"],
                "replay_to_clipped": d_pred["replay_to_clipped"],
            },
        )
        predictions.append(build_e2e_prediction(inp))

    predictions.sort(key=lambda p: (p["role"], p["kernel_e2e_actual_cycles"]))

    # --- Component validation rows -------------------------------------------
    component_rows = _component_validation_rows(
        b_records, b_model, dspan_predict, reader_predict, reader_calibration, freq
    )
    summaries = e2e_group_summary(predictions, extra_component_rows=component_rows)

    # --- Reader downstream report (v2 structured breakdown per E2E case) ------
    reader_downstream = _reader_downstream_report(reader_v2_model, exact_enriched, b_by_case)

    # --- Write ---------------------------------------------------------------
    model_json = {
        "freq_mhz": freq,
        "execution_model": "serial",
        "execution_note": (
            "current measured execution is modeled as serial (B then D span); "
            "kernel_e2e ~= maint + conv_span with ~0 residual across evidence"
        ),
        "ledger": "serial_pred = B_pred + D_span_pred + overhead_model",
        "reader_in_serial_total": False,
        "overhead_model_cycles": overhead_model,
        "reader_model_version": args.reader_model,
        "reader_model": reader_meta,
        "dspan_model": {
            "backend": d_backend,
            "base_model_fit": str(args.base_model_fit),
            "correction_components": d_coefficients,
            "correction_fields": CORRECTION_FIELDS,
        },
        "b_model": {
            "form": "cycles = fixed + active_parts*c_part + edges*c_edge + edges*active_parts*c_edge_part",
            "fixed": b_model.l0.fixed,
            "c_part": b_model.l0.c_part,
            "c_edge": b_model.l0.c_edge,
            "c_edge_part": b_model.l0.c_edge_part,
            "carry_fixed_residual": b_model.carry.fixed_residual,
        },
        "bottleneck_rules": {
            "maintenance_dominant": "B >= 1.25 * D_span",
            "reader_dominant": "R >= 0.85 * D_span",
            "compute_tail_dominant": "D_tail >= 0.40 * D_span",
            "else": "balanced",
        },
        "evidence": {
            "exact_dir": str(args.exact_dir),
            "reallike_dir": str(args.reallike_dir),
            "overhead_dirs": [str(p) for p in DEFAULT_OVERHEAD_DIRS],
            "exact_calibration_cases": sorted(DEFAULT_EXACT_CALIBRATION_CASES),
        },
        "e2e_cases": len(predictions),
    }
    write_json(args.out_dir / "e2e_model.json", model_json)
    write_rows_csv(
        args.out_dir / "e2e_predictions.csv", predictions, e2e_prediction_field_order()
    )
    write_rows_csv(
        args.out_dir / "e2e_group_summary.csv", summaries, E2E_GROUP_SUMMARY_FIELD_ORDER
    )
    if reader_downstream:
        write_rows_csv(
            args.out_dir / "e2e_reader_downstream.csv",
            reader_downstream,
            ["case", "reader_pred_cycles", "top_component", "top_component_share"],
        )

    print(
        f"e2e_cases={len(predictions)} overhead_model_cycles={overhead_model:.1f} "
        f"reader_model={args.reader_model}"
    )
    print(f"wrote {args.out_dir / 'e2e_model.json'}")
    print(f"wrote {args.out_dir / 'e2e_predictions.csv'}")
    print(f"wrote {args.out_dir / 'e2e_group_summary.csv'}")
    if reader_downstream:
        print(f"wrote {args.out_dir / 'e2e_reader_downstream.csv'}")
    print()
    print("group_summary:")
    header = E2E_GROUP_SUMMARY_FIELD_ORDER
    print("  " + "  ".join(header))
    for summary in summaries:
        print("  " + "  ".join(_fmt(summary.get(key, "")) for key in header))
    return 0


def _component_validation_rows(
    b_records,
    b_model,
    dspan_predict,
    reader_predict,
    reader_calibration,
    freq: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # B component validation, grouped by B evidence group.
    b_groups: dict[tuple[str, str], list[float]] = {}
    for record in b_records:
        prediction = b_model.predict(record)
        b_groups.setdefault((record.group, record.role), []).append(
            prediction["abs_error_pct"]
        )
    for (group, role), errors in sorted(b_groups.items()):
        rows.append(component_summary_row("B", group, role, errors))

    # D-span component validation, over the standard D eval groups.
    for group, path in sorted(DEFAULT_EVAL_GROUPS.items()):
        errors: list[float] = []
        for row in load_dataset(path):
            actual = numeric(row, "median_conv_span_ms")
            if actual is None or actual <= 0.0:
                continue
            actual_cycles = actual * freq * 1000.0
            pred = dspan_predict(row)["d_span"]
            errors.append(abs(pred - actual_cycles) / actual_cycles * 100.0)
        if errors:
            rows.append(component_summary_row("D_span", group, "holdout", errors))

    # R component validation on the reader calibration set.
    r_errors: list[float] = []
    for row in reader_calibration:
        actual = numeric(row, "median_reader_ms")
        if actual is None or actual <= 0.0:
            continue
        actual_cycles = actual * freq * 1000.0
        pred = reader_predict(row)
        r_errors.append(abs(pred - actual_cycles) / actual_cycles * 100.0)
    if r_errors:
        rows.append(component_summary_row("R", "reader_calibration", "calibration", r_errors))
    return rows


def _reader_downstream_report(reader_v2_model, exact_enriched, b_by_case):
    """Per-E2E-case reader component breakdown + reader what-ifs (v2 only).

    R is diagnostic, so this report explains the reader bottleneck inside the D
    span; it does not feed the serial total.
    """

    if reader_v2_model is None:
        return []
    report: list[dict[str, Any]] = []
    for row in exact_enriched:
        case = str(row["case"])
        if case not in b_by_case:
            continue
        components = reader_v2_model.components(row)
        total = sum(components.values()) or 1.0
        top = max(components, key=lambda name: components[name])
        whatifs = reader_v2_model.whatifs(row)
        entry: dict[str, Any] = {
            "case": case,
            "reader_pred_cycles": total,
            "top_component": top,
            "top_component_share": components[top] / total,
        }
        for name in READER_COMPONENT_ORDER:
            entry[f"comp_{name}_cycles"] = components[name]
            entry[f"comp_{name}_share"] = components[name] / total
        for name in READER_WHATIF_ORDER:
            entry[f"whatif_{name}_speedup"] = whatifs[name]["speedup"]
        report.append(entry)
    report.sort(key=lambda entry: entry["reader_pred_cycles"])
    return report


def _ms(row: dict[str, Any], key: str, freq: float) -> float:
    value = numeric(row, key)
    return 0.0 if value is None else value * freq * 1000.0


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
