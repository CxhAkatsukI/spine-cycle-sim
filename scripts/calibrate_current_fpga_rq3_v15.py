#!/usr/bin/env python3
"""Project current-plugin RQ3 ledgers through frozen Spine v15 envelopes."""

from __future__ import annotations

import argparse
import csv
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.freeze_current_fpga_spine_component_features_v14 import (  # noqa: E402
    component_active_cycles,
    component_request_count,
)
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    SpineMechanismComponentModel,
)
from spine_cycle_sim.calibration.rq3 import (  # noqa: E402
    ITERATIVE_STAGE_KEYS,
    MAINTENANCE_STAGE_KEYS,
    project_rq3_stage_ledger,
)


DEFAULT_PACKAGE = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v15_rq3_20260812/package"
)
DEFAULT_FROZEN = (
    ROOT
    / "docs/evaluation_refresh_20260810/calibration_v15_frozen"
    / "frozen_spine_mechanism_component_models.json"
)
DEFAULT_HOLDOUT = (
    ROOT
    / "docs/evaluation_refresh_20260810/calibration_v15_holdout"
    / "analysis_manifest.json"
)
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/fig10_current_v15"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(
            sink, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def model_from_payload(payload: Mapping[str, Any]) -> SpineMechanismComponentModel:
    names = {field.name for field in fields(SpineMechanismComponentModel)}
    return SpineMechanismComponentModel(
        **{name: payload[name] for name in names}
    )


def iterative_model_supported(model: SpineMechanismComponentModel) -> bool:
    return any(
        value != 0.0
        for value in (
            model.reader_round_cycles,
            model.reader_vertex_cycles,
            model.reader_memory_request_cycles,
            model.compute_fixed_cycles,
            model.compute_round_cycles,
            model.compute_memory_request_cycles,
            model.compute_simulator_cycle_scale,
            model.span_residual_cycles_per_round,
        )
    )


def calibrate_row(
    row: Mapping[str, object],
    raw: Mapping[str, Any],
    model: SpineMechanismComponentModel,
) -> dict[str, object]:
    rounds = int(raw.get("rounds", raw.get("iterations", 0)))
    common: dict[str, object] = {
        **row,
        "rounds": rounds,
        "timing_admission": "STRUCTURE_ONLY",
        "timing_admission_reason": "",
        "fpga_component_envelope_calibrated": False,
    }
    for key in (*MAINTENANCE_STAGE_KEYS, *ITERATIVE_STAGE_KEYS):
        common[f"raw_{key}"] = float(row.get(key, 0))
        common[f"calibrated_{key}"] = ""
    common.update(
        {
            "raw_total_cycles": float(row["total_cycles"]),
            "predicted_maintenance_cycles": "",
            "predicted_iterative_span_cycles": "",
            "calibrated_total_cycles": "",
            "calibrated_ledger_closed": "",
            "calibration_projection": "",
            "fpga_per_stage_counters_available": False,
        }
    )
    truthy = {True, "True", "true", 1, "1"}
    if row.get("ten_stage_supported") not in truthy:
        common["timing_admission_reason"] = (
            "execution result lacks the direct timestamps required for a "
            "supported ten-stage attribution"
        )
        return common
    if row.get("ten_stage_ledger_closed") not in truthy:
        common["timing_admission_reason"] = (
            "execution result has a ten-stage attribution whose ledger does "
            "not close to the reported total"
        )
        return common
    if rounds > 0 and not iterative_model_supported(model):
        common["timing_admission_reason"] = (
            "frozen routed FPGA samples contain no nonzero iterative rounds "
            "for this algorithm"
        )
        return common
    if "vertices" not in raw:
        common["timing_admission_reason"] = (
            "the frozen FPGA component model requires graph vertices, but "
            "the integrity-checked execution evidence does not provide them"
        )
        return common

    reader_cycles = component_active_cycles(dict(raw), "reader") if rounds else 0.0
    compute_cycles = component_active_cycles(dict(raw), "compute") if rounds else 0.0
    reader_requests = component_request_count(dict(raw), "reader") if rounds else 0.0
    compute_requests = component_request_count(dict(raw), "compute") if rounds else 0.0
    prediction = model.predict_components(
        rounds=rounds,
        vertices=float(raw["vertices"]),
        simulator_maintenance_cycles=float(raw["maintenance_cycles"]),
        simulator_reader_cycles=reader_cycles,
        simulator_compute_cycles=compute_cycles,
        simulator_reader_memory_requests=reader_requests,
        simulator_compute_memory_requests=compute_requests,
    )
    projected = project_rq3_stage_ledger(
        row,
        predicted_maintenance_cycles=prediction["maintenance_cycles"],
        predicted_iterative_span_cycles=prediction["iterative_span_cycles"],
    )
    common.update(projected)
    common["timing_admission"] = "CALIBRATED_COMPONENT_ENVELOPE"
    common["timing_admission_reason"] = (
        "total component envelopes use frozen v15; within-envelope stage "
        "fractions remain simulator attribution"
    )
    common["fpga_component_envelope_calibrated"] = True
    return common


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rq3-package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--frozen-model", type=Path, default=DEFAULT_FROZEN)
    parser.add_argument("--holdout-analysis", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-partial-holdout", action="store_true")
    parser.add_argument("--require-all-calibrated", action="store_true")
    args = parser.parse_args()

    package = args.rq3_package.resolve()
    package_manifest_path = package / "manifest.json"
    package_manifest = read_json(package_manifest_path)
    if package_manifest.get("status") != "PASS":
        raise ValueError("RQ3 source package is not complete")
    frozen_path = args.frozen_model.resolve()
    frozen = read_json(frozen_path)
    if (
        frozen.get("status") != "FROZEN_BEFORE_HOLDOUT"
        or frozen.get("holdout_used_for_fit") is not False
    ):
        raise ValueError("Spine v15 model is not a pre-holdout freeze")
    holdout_path = args.holdout_analysis.resolve()
    holdout = read_json(holdout_path)
    accepted_holdout = holdout.get("status") == "PASS"
    if not accepted_holdout and not args.allow_partial_holdout:
        raise ValueError("Spine v15 transfer validation has not passed")

    models = {
        algorithm: model_from_payload(payload)
        for algorithm, payload in frozen["models"].items()
    }
    latency_path = package / "analysis" / "rq3_latency_rows.csv"
    rows = read_csv(latency_path)
    calibrated: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    for row in rows:
        execution_id = row["execution_id"]
        wrapper_path = package / "runs" / execution_id / "case_result.json"
        wrapper = read_json(wrapper_path)
        if wrapper.get("plugin_sha256") != package_manifest.get("plugin_sha256"):
            raise ValueError(f"RQ3 wrapper plugin mismatch: {execution_id}")
        raw_path = Path(wrapper["raw_result_path"])
        if sha256_file(raw_path) != wrapper["raw_result_sha256"]:
            raise ValueError(f"RQ3 raw result changed: {execution_id}")
        raw = read_json(raw_path)
        if "vertices" not in raw:
            vertices = wrapper.get("scalar_metrics", {}).get("vertices")
            if vertices is not None:
                raw["vertices"] = int(vertices)
        algorithm = row["algorithm"]
        if algorithm not in models:
            raise ValueError(f"no frozen v15 model for {algorithm}")
        calibrated.append(calibrate_row(row, raw, models[algorithm]))
        evidence.append(
            {
                "execution_id": execution_id,
                "wrapper": str(wrapper_path),
                "wrapper_sha256": sha256_file(wrapper_path),
                "raw_result": str(raw_path),
                "raw_result_sha256": sha256_file(raw_path),
            }
        )

    unsupported = [
        row for row in calibrated if not row["fpga_component_envelope_calibrated"]
    ]
    status = (
        "PASS"
        if accepted_holdout and not unsupported
        else "PARTIAL_COMPONENT_CALIBRATION"
    )
    if args.require_all_calibrated and status != "PASS":
        raise ValueError(
            f"RQ3 calibration is incomplete: holdout={holdout.get('status')} "
            f"unsupported={len(unsupported)}"
        )
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "calibrated_breakdown_rows.csv", calibrated)
    write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "status": status,
            "source_package": str(package),
            "source_package_manifest_sha256": sha256_file(package_manifest_path),
            "source_latency_rows": str(latency_path),
            "source_latency_rows_sha256": sha256_file(latency_path),
            "plugin_sha256": package_manifest.get("plugin_sha256"),
            "frozen_model": str(frozen_path),
            "frozen_model_sha256": sha256_file(frozen_path),
            "holdout_analysis": str(holdout_path),
            "holdout_analysis_sha256": sha256_file(holdout_path),
            "holdout_status": holdout.get("status"),
            "rows": len(calibrated),
            "calibrated_rows": len(calibrated) - len(unsupported),
            "structure_only_rows": len(unsupported),
            "structure_only_execution_ids": [
                row["execution_id"] for row in unsupported
            ],
            "evidence_boundary": (
                "FPGA calibration covers aggregate maintenance and iterative "
                "component envelopes only; ten-stage fractions are direct "
                "execution-model timestamp attribution, not FPGA per-stage counters"
            ),
            "evidence": evidence,
        },
    )
    print(
        f"CURRENT_FPGA_RQ3_V15_{status} rows={len(calibrated)} "
        f"structure_only={len(unsupported)} out={output}",
        flush=True,
    )
    return 0 if status == "PASS" or not args.require_all_calibrated else 1


if __name__ == "__main__":
    raise SystemExit(main())
