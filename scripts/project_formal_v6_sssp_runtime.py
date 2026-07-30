#!/usr/bin/env python3
"""Project infeasible full-graph K4 SSSP runs from completed formal evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
from typing import Any, Mapping, Sequence


DEFAULT_ROOT = Path("/data/tmp/chuxiao/large_graph_campaign_v1")
COMPLETED = (
    ("sx_askubuntu", "7d85c85226dfafcf6942"),
    ("sx_superuser", "a4c67b976434b6a2ec1b"),
    ("wiki_talk_temporal", "db5d657374e1d0bac2c2"),
)
TARGETS = (
    (
        "sx_stackoverflow",
        13,
        "formal_v6_sssp_exact",
        "run.sx_stackoverflow.weighted_sssp.insert.u8.grasu_regraph_k4_shared.69248cd5746efe44a840",
    ),
    (
        "soc_pokec",
        19,
        "formal_v6_pokec_sssp_k4_sidecar",
        "run.soc_pokec.weighted_sssp.insert.u8.grasu_regraph_k4_shared.bb8611a68e5fdcd8b898",
    ),
)


def cycles_per_edge_round(rows: Sequence[Mapping[str, float]]) -> float:
    coefficients = []
    for row in rows:
        edges = int(row["directed_records"])
        supersteps = int(row["supersteps"])
        cycles = int(row["cycles"])
        if edges <= 0 or supersteps <= 0 or cycles <= 0:
            raise ValueError("calibration rows require positive work and cycles")
        coefficients.append(cycles / (edges * supersteps))
    if not coefficients:
        raise ValueError("at least one calibration row is required")
    return statistics.median(coefficients)


def project_target(
    *,
    directed_records: int,
    supersteps: int,
    current_cycles: int,
    elapsed_seconds: float,
    coefficient: float,
    wall_budget_hours: float,
) -> dict[str, Any]:
    if min(directed_records, supersteps, current_cycles) <= 0:
        raise ValueError("target work and current cycles must be positive")
    if elapsed_seconds <= 0.0 or coefficient <= 0.0 or wall_budget_hours <= 0.0:
        raise ValueError("elapsed time, coefficient, and budget must be positive")
    projected_cycles = coefficient * directed_records * supersteps
    observed_rate = current_cycles / elapsed_seconds
    remaining_cycles = max(0.0, projected_cycles - current_cycles)
    projected_hours = projected_cycles / observed_rate / 3600.0
    remaining_hours = remaining_cycles / observed_rate / 3600.0
    optimistic_total_cycles = projected_cycles / 10.0
    optimistic_remaining_cycles = max(0.0, optimistic_total_cycles - current_cycles)
    optimistic_remaining_hours = (
        optimistic_remaining_cycles / (observed_rate * 2.0) / 3600.0
    )
    return {
        "directed_records": directed_records,
        "oracle_minimum_supersteps": supersteps,
        "current_cycles": current_cycles,
        "elapsed_seconds": elapsed_seconds,
        "observed_cycles_per_second": observed_rate,
        "projected_cycles": round(projected_cycles),
        "projected_progress_fraction": current_cycles / projected_cycles,
        "projected_total_hours_at_observed_rate": projected_hours,
        "projected_remaining_hours_at_observed_rate": remaining_hours,
        "optimistic_remaining_hours_10x_less_work_2x_rate": optimistic_remaining_hours,
        "wall_budget_hours": wall_budget_hours,
        "wall_budget_feasible": optimistic_remaining_hours <= wall_budget_hours,
        "recommended_action": (
            "continue"
            if optimistic_remaining_hours <= wall_budget_hours
            else "soft_stop_and_classify_wall_time_infeasible"
        ),
    }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _records(root: Path, dataset_id: str) -> int:
    manifest = _load_json(
        root / "workloads" / dataset_id / "materialization_manifest.json"
    )
    return int(manifest["graphs"]["directed"]["records"])


def build_projection(root: Path, wall_budget_hours: float) -> dict[str, Any]:
    calibration_rows = []
    for dataset_id, execution_id in COMPLETED:
        result_path = (
            root
            / "formal_v6_sssp_exact"
            / "runs"
            / "runs"
            / execution_id
            / "case_result.json"
        )
        result = _load_json(result_path)
        admission = result.get("admission", {})
        if (
            result.get("status") != "pass"
            or int(admission.get("architecture_correctness_mismatches", -1)) != 0
            or int(admission.get("mathematical_correctness_mismatches", -1)) != 0
        ):
            raise ValueError(f"calibration result is not correctness-admitted: {result_path}")
        row = {
            "dataset_id": dataset_id,
            "execution_id": execution_id,
            "directed_records": _records(root, dataset_id),
            "supersteps": int(result["scalar_metrics"]["supersteps"]),
            "cycles": int(result["row"]["cycles"]),
        }
        row["cycles_per_edge_round"] = (
            row["cycles"] / (row["directed_records"] * row["supersteps"])
        )
        calibration_rows.append(row)
    coefficient = cycles_per_edge_round(calibration_rows)

    targets = []
    for dataset_id, supersteps, campaign, job_id in TARGETS:
        run_dir = root / campaign / "run"
        state = _load_json(run_dir / "campaign_state.json")
        job = next(row for row in state["jobs"] if row["job_id"] == job_id)
        progress = _load_json(run_dir / "jobs" / job_id / "progress.json")
        projection = project_target(
            directed_records=_records(root, dataset_id),
            supersteps=supersteps,
            current_cycles=int(progress["simulated_cycles"]),
            elapsed_seconds=float(job["elapsed_seconds"]),
            coefficient=coefficient,
            wall_budget_hours=wall_budget_hours,
        )
        projection.update(
            {
                "dataset_id": dataset_id,
                "job_id": job_id,
                "campaign": campaign,
                "progress_host_epoch_seconds": progress["host_epoch_seconds"],
                "backend_requests": int(progress["backend_requests"]),
                "superstep_source": "GRASU_SST_NATIVE_SUPERSTEPS in frozen running SST environment",
            }
        )
        targets.append(projection)

    return {
        "schema_version": 1,
        "evidence_id": "formal_v6_large_sssp_runtime_projection_20260730",
        "model": "median admitted cycles / (directed records * oracle-minimum supersteps)",
        "cycles_per_edge_round": coefficient,
        "calibration_rows": calibration_rows,
        "targets": targets,
        "all_targets_wall_time_infeasible": all(
            not row["wall_budget_feasible"] for row in targets
        ),
        "claim_boundary": (
            "This is a host-runtime feasibility decision, not an accelerator-cycle result. "
            "Stopped rows do not enter architecture performance aggregates."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--wall-budget-hours", type=float, default=3.0)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    payload = build_projection(args.campaign_root.resolve(), args.wall_budget_hours)
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="ascii")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
