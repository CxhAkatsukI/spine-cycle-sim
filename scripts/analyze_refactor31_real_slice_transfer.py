#!/usr/bin/env python3
"""Fit and validate the refactor31 real-slice simulator transfer model."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration.refactor31 import (  # noqa: E402
    fit_refactor31_residual_model,
    load_refactor31_real_slice_fpga_logs,
    load_refactor31_resident_sim_summary,
    refactor31_absolute_error_percent,
    refactor31_spearman,
    summarize_refactor31_real_slice_fpga_runs,
)


DEFAULT_MATRIX = (
    ROOT / "configs/experiments/spine_refactor31_fpga_calibration_matrix_v2.json"
)
DEFAULT_SLICES = Path(
    "/data/feiyang/codex_builds/spine_paper_alignment/"
    "refactor31_real_slices_v2/manifest.json"
)
DEFAULT_MODEL_PROTOCOL = (
    ROOT / "configs/experiments/spine_refactor31_transfer_residual_model_v2.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty CSV {path}")
    fields: list[str] = []
    for row in rows:
        fields.extend(field for field in row if field not in fields)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def case_id(row: dict[str, Any]) -> str:
    return f"{row['dataset']}_e{row['target_edges']}"


def summarize_group(rows: list[dict[str, Any]], role: str) -> dict[str, Any]:
    selected = [row for row in rows if row["role"] == role]
    if not selected:
        raise ValueError(f"no rows for role {role}")
    output: dict[str, Any] = {"role": role, "cases": len(selected)}
    for target in ("paired", "reader", "compute"):
        errors = [float(row[f"calibrated_{target}_error_pct"]) for row in selected]
        actual = [float(row[f"actual_{target}_cycles"]) for row in selected]
        predicted = [float(row[f"calibrated_{target}_cycles"]) for row in selected]
        output[f"{target}_median_abs_error_pct"] = statistics.median(errors)
        output[f"{target}_max_abs_error_pct"] = max(errors)
        output[f"{target}_spearman"] = (
            refactor31_spearman(actual, predicted) if len(selected) >= 2 else math.nan
        )
    return output


def evaluate_holdout_admission(
    holdout_summary: dict[str, Any], admission_cfg: dict[str, Any]
) -> dict[str, Any]:
    """Apply the frozen transfer thresholds only to unseen holdout cases."""
    admission = {
        "scope": "frozen_holdout",
        "correctness_and_ledger": True,
        "paired_median_error": (
            holdout_summary["paired_median_abs_error_pct"]
            <= float(admission_cfg["median_total_cycle_error_percent_max"])
        ),
        "paired_max_error": (
            holdout_summary["paired_max_abs_error_pct"]
            <= float(admission_cfg["max_total_cycle_error_percent_max"])
        ),
        "component_median_error": max(
            holdout_summary["reader_median_abs_error_pct"],
            holdout_summary["compute_median_abs_error_pct"],
        )
        <= float(admission_cfg["component_median_cycle_error_percent_max"]),
        "workload_rank": (
            holdout_summary["paired_spearman"]
            >= float(admission_cfg["workload_rank_spearman_min"])
        ),
    }
    admission["all"] = all(
        value for key, value in admission.items() if key != "scope"
    )
    return admission


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--slice-manifest", type=Path, default=DEFAULT_SLICES)
    parser.add_argument(
        "--model-protocol", type=Path, default=DEFAULT_MODEL_PROTOCOL
    )
    parser.add_argument("--fpga-root", type=Path, required=True)
    parser.add_argument("--sim-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    matrix_path = args.matrix.resolve()
    slice_manifest_path = args.slice_manifest.resolve()
    model_protocol_path = args.model_protocol.resolve()
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    model_protocol = json.loads(model_protocol_path.read_text(encoding="utf-8"))
    slices = json.loads(slice_manifest_path.read_text(encoding="utf-8"))
    if model_protocol["parent_matrix_sha256"] != sha256(matrix_path):
        raise ValueError("residual-model protocol parent matrix hash mismatch")
    calibration_ids = {
        dataset["id"] for dataset in matrix["calibration"]["datasets"]
    }
    generated = [row for row in slices["rows"] if row["status"] == "generated"]
    expected_cases = {case_id(row) for row in generated}
    rows: list[dict[str, Any]] = []
    profile_path = (ROOT / matrix["architecture_profile"]).resolve()
    plugin_path = (ROOT / matrix["simulator_plugin"]["path"]).resolve()
    fpga_binding = matrix["native_fpga_artifact"]
    host_path = Path(fpga_binding["host_path"]).resolve()
    xclbin_path = Path(fpga_binding["xclbin_path"]).resolve()
    bound_paths = (
        (profile_path, matrix["architecture_profile_sha256"]),
        (plugin_path, matrix["simulator_plugin"]["sha256"]),
        (host_path, fpga_binding["host_sha256"]),
        (xclbin_path, fpga_binding["xclbin_sha256"]),
    )
    for path, expected_sha256 in bound_paths:
        if not path.is_file() or sha256(path) != expected_sha256:
            raise ValueError(f"frozen artifact hash mismatch: {path}")
    input_paths = [
        matrix_path,
        model_protocol_path,
        slice_manifest_path,
        profile_path,
        plugin_path,
        host_path,
        xclbin_path,
    ]

    ordered_slices = sorted(
        generated, key=lambda row: (row["dataset"], row["target_edges"])
    )
    for slice_row in ordered_slices:
        name = case_id(slice_row)
        fpga_logs = sorted((args.fpga_root / "fpga" / name).glob("repeat_*.log"))
        sim_summary_path = args.sim_root / "sim" / name / "summary.json"
        if not fpga_logs or not sim_summary_path.is_file():
            raise ValueError(f"incomplete transfer evidence for {name}")
        slice_path = Path(slice_row["path"]).resolve()
        if not slice_path.is_file() or sha256(slice_path) != slice_row["sha256"]:
            raise ValueError(f"slice hash mismatch for {name}")
        input_paths.append(slice_path)
        input_paths.extend(fpga_logs)
        input_paths.append(sim_summary_path)
        fpga = summarize_refactor31_real_slice_fpga_runs(
            load_refactor31_real_slice_fpga_logs(fpga_logs),
            required_repeats=int(matrix["required_repeats"]),
        )
        sim = load_refactor31_resident_sim_summary(sim_summary_path)
        if fpga["case"] != Path(slice_row["path"]).stem:
            raise ValueError(f"slice identity mismatch for {name}")
        for field in ("rounds", "resident_level", "processed_edges"):
            if int(fpga[field]) != int(sim[field]):
                raise ValueError(f"FPGA/simulator {field} mismatch for {name}")
        if not fpga["calibration_admitted"]:
            raise ValueError(f"FPGA repeat/correctness gate failed for {name}")
        if not sim["correctness_admitted"] or not sim["ledger_admitted"]:
            raise ValueError(f"simulator correctness/ledger gate failed for {name}")
        if sim["architecture_profile_sha256"] != matrix["architecture_profile_sha256"]:
            raise ValueError(f"simulator profile hash mismatch for {name}")
        if sim["sst_plugin_sha256"] != matrix["simulator_plugin"]["sha256"]:
            raise ValueError(f"simulator plugin hash mismatch for {name}")
        rows.append(
            {
                "case": name,
                "dataset": slice_row["dataset"],
                "role": (
                    "calibration"
                    if slice_row["dataset"] in calibration_ids
                    else "holdout"
                ),
                "target_edges": int(slice_row["target_edges"]),
                "vertices": int(fpga["vertices"]),
                "source": int(fpga["source"]),
                "resident_level": int(fpga["resident_level"]),
                "rounds": int(fpga["rounds"]),
                "processed_edges": int(fpga["processed_edges"]),
                "fpga_samples": int(fpga["samples"]),
                "fpga_reader_cv_pct": float(fpga["reader_cv_pct"]),
                "fpga_compute_cv_pct": float(fpga["compute_cv_pct"]),
                "fpga_paired_cv_pct": float(fpga["paired_cv_pct"]),
                "actual_reader_cycles": int(fpga["median_reader_cycles"]),
                "actual_compute_cycles": int(fpga["median_compute_cycles"]),
                "actual_paired_cycles": int(fpga["median_paired_cycles"]),
                "raw_reader_cycles": int(sim["raw_reader_cycles"]),
                "raw_compute_cycles": int(sim["raw_compute_cycles"]),
                "raw_paired_cycles": int(sim["raw_paired_cycles"]),
            }
        )

    if {row["case"] for row in rows} != expected_cases:
        raise ValueError("analyzed case set does not match the frozen generated matrix")
    calibration = [row for row in rows if row["role"] == "calibration"]
    models = {
        target: fit_refactor31_residual_model(
            calibration,
            actual_field=f"actual_{target}_cycles",
            raw_field=f"raw_{target}_cycles",
            include_processed_edges=True,
            relative_error_weighted=True,
        )
        for target in ("paired", "reader", "compute")
    }
    for row in rows:
        for target, model in models.items():
            actual = float(row[f"actual_{target}_cycles"])
            raw = float(row[f"raw_{target}_cycles"])
            calibrated = model.predict(
                raw, int(row["rounds"]), int(row["processed_edges"])
            )
            row[f"raw_{target}_error_pct"] = refactor31_absolute_error_percent(
                actual, raw
            )
            row[f"calibrated_{target}_cycles"] = round(calibrated)
            row[f"calibrated_{target}_error_pct"] = (
                refactor31_absolute_error_percent(actual, calibrated)
            )

    group_summary = [
        summarize_group(rows, role) for role in ("calibration", "holdout")
    ]
    holdout_summary = next(
        summary for summary in group_summary if summary["role"] == "holdout"
    )
    all_summary = summarize_group(
        [dict(row, role="all") for row in rows], "all"
    )
    admission_cfg = matrix["admission"]
    admission = evaluate_holdout_admission(holdout_summary, admission_cfg)

    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "refactor31_real_slice_predictions.csv", rows)
    write_csv(output / "refactor31_real_slice_group_summary.csv", group_summary)
    input_hashes = [
        {"path": str(path.resolve()), "sha256": sha256(path.resolve())}
        for path in sorted(set(input_paths))
    ]
    (output / "refactor31_real_slice_input_hashes.json").write_text(
        json.dumps(input_hashes, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = {
        "schema_version": 2,
        "evidence_id": "spine_refactor31_real_slice_transfer_v3",
        "matrix_id": matrix["matrix_id"],
        "matrix_sha256": sha256(matrix_path),
        "slice_manifest_sha256": sha256(slice_manifest_path),
        "artifact_binding": {
            "architecture_profile_sha256": matrix["architecture_profile_sha256"],
            "simulator_plugin_sha256": matrix["simulator_plugin"]["sha256"],
            "fpga_host_sha256": fpga_binding["host_sha256"],
            "fpga_xclbin_sha256": fpga_binding["xclbin_sha256"],
        },
        "execution_boundary": matrix["execution_boundary"],
        "residual_model_protocol": {
            "id": model_protocol["model_id"],
            "sha256": sha256(model_protocol_path),
            "features": model_protocol["features"],
            "constraint": model_protocol["constraint"],
        },
        "calibration_case_count": len(calibration),
        "holdout_case_count": len(rows) - len(calibration),
        "models": {target: model.to_dict() for target, model in models.items()},
        "all_case_summary": all_summary,
        "group_summary": group_summary,
        "admission_summary": holdout_summary,
        "admission_thresholds": admission_cfg,
        "admission": admission,
        "claim_boundary": {
            "supported": [
                "correctness_gated_refactor31_real_slice_timing",
                "resident_reader_compute_event_window_transfer",
                "calibration_holdout_separation",
            ],
            "not_supported": [
                "paper_owner_fifo_cycle_calibration",
                "maintenance_or_graph_load_timing",
                "graphs_exceeding_the_refactor31_vertex_domain",
            ],
        },
    }
    (output / "refactor31_real_slice_transfer_evidence.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"cases={len(rows)} calibration={len(calibration)} "
        f"holdout={len(rows) - len(calibration)} admitted={int(admission['all'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
