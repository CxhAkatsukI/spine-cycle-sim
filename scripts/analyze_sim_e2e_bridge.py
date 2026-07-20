#!/usr/bin/env python3
"""Sim-vs-HW end-to-end bridge validation.

Runs `SpineV0Simulator` on synthetic workloads that have measured hardware
evidence, feeds the sim's structural features through the calibrated component
models (via `spine_cycle_sim.calibration.bridge`), and compares the sim-driven
E2E prediction against the measured HW `median_kernel_e2e_ms` per stage.

Because the simulator's tile schedule is produced by the same tiling algorithm
as the hardware host, its structural features match the HW rows (verified in the
Phase 5A feasibility check), so the sim-vs-HW error is the component-model error.
The simulator only runs synthetic workloads; real Amazon slices are validated
via the same shared models (~12% serial) in `analyze_e2e_component_model.py`.

Usage:
    python3 scripts/analyze_sim_e2e_bridge.py --out-dir <DIR>
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_hw_dstage_readiness import (  # noqa: E402
    phase3c_full_partition_holdout_matrix,
    phase5a_reader_calibration_matrix,
    phase5a_reader_holdout_matrix,
)
from spine_cycle_sim.calibration.bridge import BridgeModels, predict_e2e_from_results  # noqa: E402
from spine_cycle_sim.calibration.maintenance import DEFAULT_FREQ_MHZ  # noqa: E402
from spine_cycle_sim.calibration.reader import path_class  # noqa: E402
from spine_cycle_sim.models.spine import SpineV0Simulator, load_config  # noqa: E402
from spine_cycle_sim.workloads.generators import (  # noqa: E402
    generate_multi_source_tile_workload,
    generate_partition_tile_workload,
    generate_striped_source_tile_workload,
)

# (matrix function, HW evidence dir, group label, role) — pre-declared.
VALIDATION_GROUPS = [
    (phase5a_reader_calibration_matrix, "results/phase5a_reader_calibration_hw_20260720_210049",
     "phase5a_reader_cal", "reader_calibration"),
    (phase5a_reader_holdout_matrix, "results/phase5a_reader_holdout_hw_20260720_210049",
     "phase5a_reader_holdout", "reader_holdout"),
    (phase3c_full_partition_holdout_matrix, "results/phase3c_full_partition_holdout_hw_20260719_175623",
     "phase3c_full_holdout", "dspan_holdout"),
]

PREDICTION_FIELDS = [
    "group", "role", "case", "sweep", "path_class",
    "sim_traversed_edges", "hw_traversed_edges", "structural_match",
    "B_actual_cycles", "B_pred_cycles", "B_error_pct",
    "R_actual_cycles", "R_pred_cycles", "R_error_pct",
    "D_span_actual_cycles", "D_span_pred_cycles", "D_span_error_pct",
    "kernel_e2e_actual_cycles", "serial_pred_cycles", "serial_error_pct",
    "overhead_actual_cycles", "overhead_model_cycles", "overhead_note",
    "bottleneck_actual", "bottleneck_pred", "trusted_status",
    "whatif_halve_b_repeated_scans_speedup", "whatif_halve_b_level_write_path_speedup",
    "whatif_halve_reader_time_speedup", "whatif_ideal_bd_overlap_speedup",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/spine_current.yaml")
    parser.add_argument("--evidence-root", type=Path, default=ROOT)
    parser.add_argument("--freq-mhz", type=float, default=DEFAULT_FREQ_MHZ)
    return parser.parse_args()


def _parse_partition_spec(tokens: list[str]) -> dict[int, list[int]]:
    spec: dict[int, list[int]] = {}
    for token in tokens:
        if token.startswith("--") or ":" not in token:
            continue
        part, counts = token.split(":", 1)
        spec[int(part)] = [int(c) for c in counts.split(",") if c != ""]
    return spec


def spec_to_workload(args: tuple[str, ...], vs_partition_size: int):
    """Translate a DStageCase's host args into a simulator Workload (or None)."""
    a = list(args)
    if not a:
        return None
    if a[0] == "--multi-source-tile-work":
        return generate_multi_source_tile_workload(
            int(a[1]), _parse_partition_spec(a[2:]), vs_partition_size=vs_partition_size
        )
    if a[0] == "--partition-tile-work":
        return generate_partition_tile_workload(
            _parse_partition_spec(a[1:]), vs_partition_size=vs_partition_size
        )
    if a[0] == "--striped-source-tile-work":
        return generate_striped_source_tile_workload(
            int(a[1]), int(a[2]), int(a[3]), int(a[4]), vs_partition_size=vs_partition_size
        )
    # --star-onepart (edge_stream axis) has no simulator generator -> skip.
    return None


def _hw_actuals(hw_dir: Path, freq: float) -> dict[str, dict]:
    summary = hw_dir / "summary.csv"
    if not summary.exists():
        return {}
    out: dict[str, dict] = {}
    with summary.open(newline="") as handle:
        for row in csv.DictReader(handle):
            def cyc(key: str):
                value = row.get(key, "")
                try:
                    return float(value) * freq * 1000.0
                except (TypeError, ValueError):
                    return None
            ms = {k: cyc(k) for k in (
                "median_maint_ms", "median_reader_ms", "median_conv_span_ms", "median_kernel_e2e_ms")}
            if any(v is None for v in ms.values()):
                continue
            out[str(row["case"])] = {
                "B_actual": ms["median_maint_ms"],
                "R_actual": ms["median_reader_ms"],
                "D_span_actual": ms["median_conv_span_ms"],
                "kernel_e2e_actual": ms["median_kernel_e2e_ms"],
                "hw_traversed_edges": float(row.get("median_traversed_edges") or 0.0),
            }
    return out


def main() -> int:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    freq = args.freq_mhz
    config = load_config(args.config)

    print("loading bridge models (B / D_span / reader / overhead)...", flush=True)
    models = BridgeModels.load(root=args.evidence_root, freq_mhz=freq)

    rows: list[dict] = []
    for matrix_fn, hw_rel, group, role in VALIDATION_GROUPS:
        hw_dir = args.evidence_root / hw_rel
        actuals = _hw_actuals(hw_dir, freq)
        if not actuals:
            print(f"  [skip] no HW evidence for {group} ({hw_dir})", flush=True)
            continue
        cases = []
        meta: dict[str, dict] = {}
        for spec in matrix_fn():
            if spec.case not in actuals:
                continue
            workload = spec_to_workload(spec.args, config.vs_partition_size)
            if workload is None:
                continue
            result = SpineV0Simulator(workload, config).run()
            cases.append((spec.case, spec.sweep, result))
            meta[spec.case] = {
                "sim_traversed_edges": float(result.get("dstage_tile_traversed_edges") or 0.0),
                "path_class": path_class({
                    "tile_fast_count": result.get("dstage_tile_fast_path_tiles"),
                    "tile_full_count": result.get("dstage_tile_full_path_tiles"),
                    "tile_fallback_count": result.get("dstage_tile_fallback_used"),
                }),
            }
        preds = predict_e2e_from_results(models, cases, actuals)
        for p in preds:
            case = p["case"]
            hw_edges = actuals[case]["hw_traversed_edges"]
            sim_edges = meta[case]["sim_traversed_edges"]
            rows.append({
                "group": group, "role": role, "case": case, "sweep": p["sweep"],
                "path_class": meta[case]["path_class"],
                "sim_traversed_edges": sim_edges, "hw_traversed_edges": hw_edges,
                "structural_match": "yes" if abs(sim_edges - hw_edges) < 1e-6 else "no",
                "B_actual_cycles": p["B_actual_cycles"], "B_pred_cycles": p["B_pred_cycles"],
                "B_error_pct": p["B_error_pct"],
                "R_actual_cycles": p["R_actual_cycles"], "R_pred_cycles": p["R_pred_cycles"],
                "R_error_pct": p["R_error_pct"],
                "D_span_actual_cycles": p["D_span_actual_cycles"],
                "D_span_pred_cycles": p["D_span_pred_cycles"], "D_span_error_pct": p["D_span_error_pct"],
                "kernel_e2e_actual_cycles": p["kernel_e2e_actual_cycles"],
                "serial_pred_cycles": p["serial_pred_cycles"], "serial_error_pct": p["serial_error_pct"],
                "overhead_actual_cycles": p["overhead_actual_cycles"],
                "overhead_model_cycles": p["overhead_model_cycles"], "overhead_note": p["overhead_note"],
                "bottleneck_actual": p["bottleneck_actual"], "bottleneck_pred": p["bottleneck_pred"],
                "trusted_status": p["trusted_status"],
                "whatif_halve_b_repeated_scans_speedup": p["whatif_halve_b_repeated_scans_speedup"],
                "whatif_halve_b_level_write_path_speedup": p["whatif_halve_b_level_write_path_speedup"],
                "whatif_halve_reader_time_speedup": p["whatif_halve_reader_time_speedup"],
                "whatif_ideal_bd_overlap_speedup": p["whatif_ideal_bd_overlap_speedup"],
            })

    _write_csv(args.out_dir / "sim_e2e_predictions.csv", rows, PREDICTION_FIELDS)
    summaries = _group_summary(rows)
    _write_csv(args.out_dir / "sim_e2e_group_summary.csv", summaries, list(summaries[0]) if summaries else [])
    _write_json(args.out_dir / "sim_e2e_model.json", {
        "freq_mhz": freq,
        "backend": "component_model_bridge_v1",
        "serial_ledger": "serial_pred = B_pred + D_span_pred + overhead_model (R diagnostic, not in serial)",
        "overhead_model_cycles": models.overhead_cycles,
        "b_model": {"fixed": models.b_model.l0.fixed, "c_part": models.b_model.l0.c_part,
                    "c_edge": models.b_model.l0.c_edge, "c_edge_part": models.b_model.l0.c_edge_part},
        "reader_coefficients": models.reader_model.coefficients,
        "validation_groups": [g for _, _, g, _ in VALIDATION_GROUPS],
        "cases": len(rows),
        "note": "simulator runs synthetic only; real Amazon slices validated via the same models elsewhere",
    })

    print(f"\ncases={len(rows)}  overhead_model_cycles={models.overhead_cycles:.1f}")
    print(f"wrote {args.out_dir / 'sim_e2e_predictions.csv'}")
    print(f"wrote {args.out_dir / 'sim_e2e_group_summary.csv'}")
    print()
    _print_summary(summaries)
    return 0


def _group_summary(rows: list[dict]) -> list[dict]:
    import statistics
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["role"], row["group"]), []).append(row)
    out: list[dict] = []
    for (role, group), preds in sorted(groups.items()):
        serial = [abs(float(p["serial_error_pct"])) for p in preds]
        out.append({
            "role": role, "group": group, "cases": len(preds),
            "structural_matches": sum(1 for p in preds if p["structural_match"] == "yes"),
            "median_serial_abs_error_pct": statistics.median(serial),
            "max_serial_abs_error_pct": max(serial),
            "median_B_abs_error_pct": statistics.median(abs(float(p["B_error_pct"])) for p in preds),
            "median_D_span_abs_error_pct": statistics.median(abs(float(p["D_span_error_pct"])) for p in preds),
        })
    return out


def _print_summary(summaries: list[dict]) -> None:
    if not summaries:
        print("(no cases)")
        return
    header = list(summaries[0])
    print("  " + "  ".join(header))
    for s in summaries:
        print("  " + "  ".join(f"{v:.3f}" if isinstance(v, float) else str(v) for v in s.values()))


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    keys = list(fieldnames)
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_json(path: Path, data) -> None:
    import json
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
