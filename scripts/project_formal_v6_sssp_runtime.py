#!/usr/bin/env python3
"""Project infeasible full-graph K4 SSSP runs from completed formal evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any, Mapping, Sequence


DEFAULT_ROOT = Path("/data/tmp/chuxiao/large_graph_campaign_v1")
DEFAULT_R19_PREFLIGHT = (
    DEFAULT_ROOT / "formal_v6_r19_k4_preflight_20260730" / "preflight.json"
)
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


def project_preflight_target(
    *,
    directed_records: int,
    supersteps: int,
    coefficient: float,
    cycles_per_second: float,
    wall_budget_hours: float,
) -> dict[str, Any]:
    if directed_records <= 0 or supersteps <= 0:
        raise ValueError("preflight target requires positive work")
    if coefficient <= 0.0 or cycles_per_second <= 0.0 or wall_budget_hours <= 0.0:
        raise ValueError("preflight projection rates and budget must be positive")
    projected_cycles = coefficient * directed_records * supersteps
    projected_hours = projected_cycles / cycles_per_second / 3600.0
    optimistic_hours = projected_hours / 20.0
    feasible = projected_hours <= wall_budget_hours
    return {
        "directed_records": directed_records,
        "oracle_minimum_supersteps": supersteps,
        "projected_cycles": round(projected_cycles),
        "calibration_cycles_per_second": cycles_per_second,
        "projected_total_hours_at_calibration_rate": projected_hours,
        "optimistic_total_hours_10x_less_work_2x_rate": optimistic_hours,
        "wall_budget_hours": wall_budget_hours,
        "wall_budget_feasible": feasible,
        "recommended_action": (
            "launch_cycle_simulation" if feasible else "do_not_launch_wall_time_infeasible"
        ),
    }


def project_one_round_target(
    *,
    directed_records: int,
    coefficient: float,
    cycles_per_second: float,
    wall_budget_hours: float,
) -> dict[str, Any]:
    """Screen an unlaunched graph using the cheapest possible full-graph round."""

    projection = project_preflight_target(
        directed_records=directed_records,
        supersteps=1,
        coefficient=coefficient,
        cycles_per_second=cycles_per_second,
        wall_budget_hours=wall_budget_hours,
    )
    projection.update(
        {
            "minimum_supersteps_used": 1,
            "superstep_basis": "weighted_sssp_requires_at_least_one_full_graph_round",
            "claim_class": (
                "authenticated_materialization_one_round_host_time_projection_"
                "not_simulated_performance"
            ),
        }
    )
    return projection


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def historical_job_observation(
    run_dir: Path, job: Mapping[str, Any]
) -> tuple[float, int]:
    elapsed = float(job.get("elapsed_seconds", 0.0))
    peak_rss = int(job.get("peak_rss_bytes", 0))
    if elapsed > 0.0:
        return elapsed, peak_rss
    events_path = run_dir / "events.jsonl"
    candidates = []
    if events_path.is_file():
        for line in events_path.read_text(encoding="ascii").splitlines():
            event = json.loads(line)
            if (
                event.get("event") == "job_finished"
                and event.get("job_id") == job.get("job_id")
                and float(event.get("elapsed_seconds", 0.0)) > 0.0
            ):
                candidates.append(event)
    if not candidates:
        raise ValueError(
            f"no positive runtime observation for {job.get('job_id', '<unknown>')}"
        )
    recovered = max(candidates, key=lambda event: float(event["elapsed_seconds"]))
    return (
        float(recovered["elapsed_seconds"]),
        int(recovered.get("peak_rss_bytes", 0)),
    )


def _records(root: Path, dataset_id: str) -> int:
    manifest = _load_json(
        root / "workloads" / dataset_id / "materialization_manifest.json"
    )
    return int(manifest["graphs"]["directed"]["records"])


def _directed_graph_identity(root: Path, dataset_id: str) -> dict[str, Any]:
    manifest_path = (
        root / "workloads" / dataset_id / "materialization_manifest.json"
    ).resolve()
    manifest = _load_json(manifest_path)
    graph = manifest["graphs"]["directed"]
    return {
        "materialization_manifest_path": str(manifest_path),
        "materialization_manifest_sha256": _sha256(manifest_path),
        "directed_graph_path": str(Path(graph["path"]).resolve()),
        "directed_graph_sha256": str(graph["sha256"]),
        "directed_records": int(graph["records"]),
        "vertices": int(graph["vertices"]),
    }


def build_projection(
    root: Path,
    wall_budget_hours: float,
    *,
    r19_preflight_path: Path = DEFAULT_R19_PREFLIGHT,
) -> dict[str, Any]:
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
            "host_wall_seconds": float(result["host_wall_seconds"]),
        }
        row["cycles_per_edge_round"] = (
            row["cycles"] / (row["directed_records"] * row["supersteps"])
        )
        row["cycles_per_second"] = row["cycles"] / row["host_wall_seconds"]
        calibration_rows.append(row)
    coefficient = cycles_per_edge_round(calibration_rows)
    calibration_rate = statistics.median(
        float(row["cycles_per_second"]) for row in calibration_rows
    )
    conservative_coefficient = min(
        float(row["cycles_per_edge_round"]) for row in calibration_rows
    )
    conservative_rate = max(
        float(row["cycles_per_second"]) for row in calibration_rows
    )

    targets = []
    for dataset_id, supersteps, campaign, job_id in TARGETS:
        run_dir = root / campaign / "run"
        state = _load_json(run_dir / "campaign_state.json")
        job = next(row for row in state["jobs"] if row["job_id"] == job_id)
        elapsed_seconds, peak_rss_bytes = historical_job_observation(run_dir, job)
        progress = _load_json(run_dir / "jobs" / job_id / "progress.json")
        projection = project_target(
            directed_records=_records(root, dataset_id),
            supersteps=supersteps,
            current_cycles=int(progress["simulated_cycles"]),
            elapsed_seconds=elapsed_seconds,
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
                "peak_rss_bytes": peak_rss_bytes,
                "superstep_source": "GRASU_SST_NATIVE_SUPERSTEPS in frozen running SST environment",
            }
        )
        targets.append(projection)

    r19_preflight = _load_json(r19_preflight_path.resolve())
    if (
        r19_preflight.get("status") != "PASS"
        or r19_preflight.get("claim_class")
        != "validated_publication_case_preflight_not_simulated_performance"
        or r19_preflight.get("case", {}).get("dataset_id") != "rmat_19_32"
    ):
        raise ValueError("R19 publication preflight is not admitted")
    r19_child = r19_preflight["child_preflight"]
    r19_projection = project_preflight_target(
        directed_records=int(r19_child["directed_records"]),
        supersteps=int(r19_child["selected_supersteps"]),
        coefficient=coefficient,
        cycles_per_second=calibration_rate,
        wall_budget_hours=wall_budget_hours,
    )
    r19_projection.update(
        {
            "dataset_id": "rmat_19_32",
            "execution_id": str(r19_preflight["case"]["execution_id"]),
            "preflight_path": str(r19_preflight_path.resolve()),
            "preflight_claim_class": str(r19_preflight["claim_class"]),
            "preflight_source_external": int(r19_child["source_external"]),
            "destination_partitions": int(r19_child["destination_partitions"]),
            "nonempty_destination_partitions": int(
                r19_child["nonempty_destination_partitions"]
            ),
        }
    )

    campaign_manifest_path = root / "formal_v6_sssp_exact" / "campaign_manifest.json"
    campaign_manifest = _load_json(campaign_manifest_path)
    completed_datasets = {row[0] for row in COMPLETED}
    observed_target_datasets = {row[0] for row in TARGETS}
    one_round_targets = []
    for job in campaign_manifest["jobs"]:
        if (
            job.get("algorithm") != "weighted_sssp"
            or job.get("system") != "grasu_regraph_k4_shared"
            or job.get("dataset_id") in completed_datasets | observed_target_datasets
        ):
            continue
        dataset_id = str(job["dataset_id"])
        identity = _directed_graph_identity(root, dataset_id)
        projection = project_one_round_target(
            directed_records=int(identity["directed_records"]),
            coefficient=conservative_coefficient,
            cycles_per_second=conservative_rate,
            wall_budget_hours=wall_budget_hours,
        )
        projection.update(identity)
        projection.update(
            {
                "dataset_id": dataset_id,
                "execution_id": str(job["job_id"]).rsplit(".", 1)[-1],
                "job_id": str(job["job_id"]),
                "campaign_manifest_path": str(campaign_manifest_path.resolve()),
                "campaign_manifest_sha256": _sha256(campaign_manifest_path),
                "coefficient_policy": "minimum_completed_cycles_per_edge_round",
                "rate_policy": "maximum_completed_cycles_per_host_second",
            }
        )
        one_round_targets.append(projection)
    one_round_targets.sort(key=lambda row: str(row["dataset_id"]))

    return {
        "schema_version": 2,
        "evidence_id": "formal_v6_large_sssp_runtime_projection_v2_20260730",
        "model": "median admitted cycles / (directed records * oracle-minimum supersteps)",
        "cycles_per_edge_round": coefficient,
        "calibration_cycles_per_second": calibration_rate,
        "one_round_screen_model": (
            "minimum admitted cycles per edge-round / maximum admitted cycles per "
            "host second, with one mandatory full-graph round"
        ),
        "one_round_screen_cycles_per_edge_round": conservative_coefficient,
        "one_round_screen_cycles_per_second": conservative_rate,
        "calibration_rows": calibration_rows,
        "targets": targets,
        "preflight_targets": [r19_projection],
        "one_round_screen_targets": one_round_targets,
        "all_targets_wall_time_infeasible": all(
            not row["wall_budget_feasible"] for row in targets
        )
        and not r19_projection["wall_budget_feasible"]
        and bool(one_round_targets)
        and all(not row["wall_budget_feasible"] for row in one_round_targets),
        "claim_boundary": (
            "This is a host-runtime feasibility decision, not an accelerator-cycle result. "
            "The one-round screen is an empirical admission projection, not a completed "
            "host oracle preflight. Stopped and screened rows do not enter architecture "
            "performance aggregates."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--wall-budget-hours", type=float, default=3.0)
    parser.add_argument("--r19-preflight", type=Path, default=DEFAULT_R19_PREFLIGHT)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    payload = build_projection(
        args.campaign_root.resolve(),
        args.wall_budget_hours,
        r19_preflight_path=args.r19_preflight,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="ascii")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
