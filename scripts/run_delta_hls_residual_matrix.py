#!/usr/bin/env python3
"""Run correctness-gated Delta.hls residual PageRank architecture pairs."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.shared_workloads import sha256_file  # noqa: E402


DEFAULT_MANIFEST = ROOT / "configs/experiments/deltahls_sinkfree_real_v1.json"
DEFAULT_SPINE_PROFILE = (
    ROOT / "configs/architectures/spine_candidate10_normalized_v1.json"
)
DEFAULT_GRASU_PROFILE = (
    ROOT
    / "configs/architectures/grasu_regraph_candidate10_k1_multipart_residual_v4.json"
)
DEFAULT_CAPABILITIES = (
    ROOT / "configs/contracts/grasu_regraph_k1_multipart_capabilities_v4.json"
)
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DELTA_CONTRACT = "deltahls_sink_free_linf_warm"
DAMPING = 0.85
MAX_ITERATIONS = 256
CROSS_SYSTEM_TOLERANCE = 1.0e-5


def epsilon_slug(epsilon: float) -> str:
    return f"eps_{epsilon:.0e}".replace("+", "")


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def _validate_input_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("matrix_id") not in {
        "deltahls_sinkfree_real_v1",
        "deltahls_sinkfree_scalability_p4_v1",
    }:
        raise ValueError("runner requires the frozen Delta.hls sink-free matrix")
    invariants = manifest.get("invariants", {})
    required_invariants = {
        "new_snapshot_sinks": 0,
        "old_snapshot_sinks": 0,
        "one_sided_updates_rejected": True,
        "weighted_reciprocal_edges": True,
    }
    if any(invariants.get(key) != value for key, value in required_invariants.items()):
        raise ValueError("Delta.hls sink-free matrix invariants changed")
    for run in manifest["runs"]:
        for key in ("graph", "update"):
            item = run[key]
            path = ROOT / item["path"]
            if sha256_file(path) != item["sha256"]:
                raise ValueError(f"workload hash changed: {path}")
    return manifest


def _command(
    architecture: str,
    run: Mapping[str, Any],
    destination: Path,
    *,
    args: argparse.Namespace,
    epsilon: float,
) -> list[str]:
    graph = (ROOT / run["graph"]["path"]).resolve()
    update = (ROOT / run["update"]["path"]).resolve()
    common = [
        "--workload",
        str(graph),
        "--update-workload",
        str(update),
        "--out-dir",
        str(destination.resolve()),
        "--sst",
        str(args.sst.resolve()),
        "--lib-dir",
        str(args.lib_dir.resolve()),
        "--max-cycles",
        str(args.max_cycles),
        "--residual-contract",
        DELTA_CONTRACT,
        "--pagerank-epsilon",
        str(epsilon),
        "--residual-max-iterations",
        str(MAX_ITERATIONS),
        "--no-build",
    ]
    if architecture == "spine":
        return [
            args.python,
            str(ROOT / "scripts/run_sst_spine_vertical.py"),
            "--scenario",
            "residual_pagerank",
            "--validation-mode",
            "generic",
            "--profile",
            str(args.spine_profile.resolve()),
            "--pagerank-damping",
            str(DAMPING),
            *common,
        ]
    if architecture == "grasu_regraph":
        return [
            args.python,
            str(ROOT / "scripts/run_sst_grasu_regraph_hls_residual_pagerank.py"),
            "--profile",
            str(args.grasu_profile.resolve()),
            "--capability-catalog",
            str(args.capability_catalog.resolve()),
            "--downstream-sharing",
            args.downstream_sharing,
            *common,
        ]
    raise ValueError(f"unknown architecture: {architecture}")


def _raw_paths(destination: Path, architecture: str) -> tuple[Path, Path | None]:
    if architecture == "spine":
        return destination / "summary.json", None
    return destination / "manifest.json", destination / "result.json"


def _run_child(command: list[str], log_path: Path, timeout: float) -> float:
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    wall_seconds = time.monotonic() - started
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"child failed with rc={completed.returncode}; see {log_path}"
        )
    return wall_seconds


def _finite_vector(result: Mapping[str, Any], key: str, vertices: int) -> tuple[float, ...]:
    values = result.get(key)
    if not isinstance(values, list) or len(values) != vertices:
        raise RuntimeError(f"{key} has the wrong vertex count")
    vector = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in vector):
        raise RuntimeError(f"{key} contains a non-finite value")
    return vector


def _validate_result(
    payload: Mapping[str, Any],
    architecture: str,
    run: Mapping[str, Any],
    epsilon: float,
    *,
    args: argparse.Namespace,
) -> tuple[Mapping[str, Any], tuple[float, ...], tuple[float, ...]]:
    graph_path = (ROOT / run["graph"]["path"]).resolve()
    update_path = (ROOT / run["update"]["path"]).resolve()
    plugin_sha256 = sha256_file(args.lib_dir.resolve() / "libspine_cycle.so")
    if architecture == "spine":
        result = payload
        rank_key, residual_key = "ranks", "residuals"
        profile_id = json.loads(args.spine_profile.read_text())["profile_id"]
        provenance = (
            result.get("architecture_profile_id") == profile_id
            and result.get("architecture_profile_sha256")
            == sha256_file(args.spine_profile)
            and result.get("workload_sha256") == sha256_file(graph_path)
            and result.get("update_workload_sha256") == sha256_file(update_path)
            and result.get("sst_plugin_sha256") == plugin_sha256
        )
        memory_ledger = (
            result.get("memory_ledger_match") is True
            and result.get("memory_locality_ledger_match") is True
            and result.get("active_edge_execution_ledger_match") is True
            and result.get("reader_edges_total")
            == result.get("compute_edges_total")
            == result.get("expected_active_edges")
        )
    else:
        result = payload.get("result", {})
        if not isinstance(result, Mapping):
            raise RuntimeError("GraSU manifest has no result object")
        rank_key, residual_key = "ranks_external", "residuals_external"
        provenance = (
            payload.get("status") == "PASS"
            and payload.get("profile_sha256") == sha256_file(args.grasu_profile)
            and payload.get("workload_sha256") == sha256_file(graph_path)
            and payload.get("update_workload_sha256") == sha256_file(update_path)
            and payload.get("sst_plugin_sha256") == plugin_sha256
        )
        memory_ledger = (
            result.get("memory_locality_ledger_match") is True
            and result.get("active_edge_execution_ledger_match") is True
            and result.get("expected_backend_requests")
            == result.get("backend_requests")
        )
    vertices = int(run["graph"]["vertices"])
    ranks = _finite_vector(result, rank_key, vertices)
    residuals = _finite_vector(result, residual_key, vertices)
    frontier_in = result.get("frontier_in_sizes")
    frontier_out = result.get("frontier_out_sizes")
    checks = {
        "success": result.get("success") is True,
        "provenance": provenance,
        "contract": result.get("residual_contract") == DELTA_CONTRACT,
        "damping": math.isclose(
            float(result.get("pagerank_damping", math.nan)), DAMPING, abs_tol=1e-7
        ),
        "epsilon": math.isclose(
            float(result.get("pagerank_epsilon", math.nan)), epsilon, abs_tol=1e-15
        ),
        "sink_free": result.get("old_sink_vertices") == 0
        and result.get("new_sink_vertices") == 0,
        "converged": result.get("converged") is True
        and result.get("residual_bound_passed") is True
        and float(result.get("residual_linf", math.inf)) <= epsilon * 1.01,
        "frontier": isinstance(frontier_in, list)
        and isinstance(frontier_out, list)
        and len(frontier_in) == len(frontier_out) == result.get("iterations")
        and bool(frontier_in)
        and frontier_in[0] == result.get("initial_active_vertices")
        and frontier_out[-1] == 0,
        "dual_oracle": result.get("architecture_correctness_mismatches") == 0
        and result.get("mathematical_correctness_mismatches") == 0
        and result.get("correctness_mismatches") == 0,
        "mathematical_bound": result.get("mathematical_error_bound")
        == "l1_fixed_point_defect_plus_final_residual_over_one_minus_d"
        and float(result.get("mathematical_max_abs_error", math.inf))
        <= float(result.get("mathematical_error_tolerance", -1.0)),
        "memory_ledger": memory_ledger,
        "shape": result.get("vertices") == vertices
        and result.get("initial_edges") == run["graph"]["records"],
    }
    if architecture == "grasu_regraph":
        expected_pipelines = int(
            json.loads(args.grasu_profile.read_text())["parameters"].get(
                "regraph_compute_pipelines", 1
            )
        )
        destination_partitions = int(result.get("destination_partitions", 0))
        checks.update(
            {
                "compute_pipelines": result.get("compute_pipelines")
                == expected_pipelines,
                "downstream_sharing": result.get("downstream_sharing")
                == args.downstream_sharing,
                "downstream_parallelism": result.get(
                    "max_parallel_downstream_partitions"
                )
                == (
                    min(expected_pipelines, destination_partitions)
                    if args.downstream_sharing == "direct"
                    else 1
                ),
            }
        )
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"{run['run_id']}/{architecture} failed gates: {failed}")
    return result, ranks, residuals


def _traffic_bytes(result: Mapping[str, Any], key: str) -> int:
    traffic = result.get(key, {})
    if not isinstance(traffic, Mapping):
        return 0
    combined = traffic.get("combined", {})
    return int(combined.get("bytes", 0)) if isinstance(combined, Mapping) else 0


def _run_case(
    run: Mapping[str, Any],
    architecture: str,
    epsilon: float,
    *,
    args: argparse.Namespace,
) -> dict[str, Any]:
    destination = (
        args.out_dir / str(run["run_id"]) / epsilon_slug(epsilon) / architecture
    )
    destination.mkdir(parents=True, exist_ok=True)
    command = _command(
        architecture, run, destination, args=args, epsilon=epsilon
    )
    raw_path, _ = _raw_paths(destination, architecture)
    wall_seconds = None
    if not args.reuse_results or not raw_path.is_file():
        wall_seconds = _run_child(
            command, destination / "matrix_driver.log", args.timeout_seconds
        )
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    result, ranks, residuals = _validate_result(
        payload, architecture, run, epsilon, args=args
    )
    core_mhz = float(result["core_mhz"])
    cycles = int(result["cycles"])
    update_cycles = int(
        result["maintenance_cycles"]
        if architecture == "spine"
        else result["update_cycles"]
    )
    compute_cycles = cycles - update_cycles
    update_traffic = (
        "maintenance_backend_traffic"
        if architecture == "spine"
        else "update_backend_traffic"
    )
    return {
        "run_id": run["run_id"],
        "role": run["role"],
        "architecture": architecture,
        "compute_pipelines": int(result.get("compute_pipelines", 1)),
        "downstream_sharing": result.get(
            "downstream_sharing", "spine_native"
        ),
        "residual_contract": DELTA_CONTRACT,
        "epsilon": epsilon,
        "damping": DAMPING,
        "vertices": run["graph"]["vertices"],
        "initial_edges": run["graph"]["records"],
        "user_mutations": run["user_mutations"],
        "physical_records": run["physical_records"],
        "core_mhz": core_mhz,
        "cycles": cycles,
        "time_us": cycles / core_mhz,
        "update_cycles": update_cycles,
        "compute_cycles": compute_cycles,
        "iterations": result["iterations"],
        "initial_active_vertices": result["initial_active_vertices"],
        "active_edges": result.get(
            "compute_active_edges", result.get("compute_edges_total")
        ),
        "residual_l1": result["residual_l1"],
        "residual_linf": result["residual_linf"],
        "backend_requests": result["backend_requests"],
        "backend_bytes": _traffic_bytes(result, "backend_traffic"),
        "update_backend_bytes": _traffic_bytes(result, update_traffic),
        "compute_backend_bytes": _traffic_bytes(result, "compute_backend_traffic"),
        "backend_submit_stalls": result.get("backend_submit_stalls", 0),
        "backend_response_queue_stalls": result.get(
            "backend_response_queue_stalls", 0
        ),
        "sst_host_wall_seconds": result.get(
            "sst_host_wall_seconds",
            payload.get("sst_host_wall_seconds", wall_seconds),
        ),
        "correctness_mismatches": result["correctness_mismatches"],
        "ranks": ranks,
        "residuals": residuals,
        "frontier_in": tuple(result["frontier_in_sizes"]),
        "frontier_out": tuple(result["frontier_out_sizes"]),
        "result_path": _display_path(raw_path),
    }


def _pair(spine: Mapping[str, Any], grasu: Mapping[str, Any]) -> dict[str, Any]:
    rank_difference = max(
        abs(a - b) for a, b in zip(spine["ranks"], grasu["ranks"], strict=True)
    )
    residual_difference = max(
        abs(a - b)
        for a, b in zip(spine["residuals"], grasu["residuals"], strict=True)
    )
    frontiers_match = (
        spine["frontier_in"] == grasu["frontier_in"]
        and spine["frontier_out"] == grasu["frontier_out"]
    )
    if (
        rank_difference > CROSS_SYSTEM_TOLERANCE
        or residual_difference > CROSS_SYSTEM_TOLERANCE
        or not frontiers_match
    ):
        raise RuntimeError(f"cross-system state mismatch for {spine['run_id']}")
    return {
        "run_id": spine["run_id"],
        "role": spine["role"],
        "epsilon": spine["epsilon"],
        "user_mutations": spine["user_mutations"],
        "iterations": spine["iterations"],
        "spine_cycles": spine["cycles"],
        "grasu_cycles": grasu["cycles"],
        "spine_speedup_over_grasu": grasu["time_us"] / spine["time_us"],
        "spine_backend_bytes": spine["backend_bytes"],
        "grasu_backend_bytes": grasu["backend_bytes"],
        "grasu_to_spine_backend_byte_ratio": grasu["backend_bytes"]
        / spine["backend_bytes"],
        "cross_system_max_abs_rank_difference": rank_difference,
        "cross_system_max_abs_residual_difference": residual_difference,
        "cross_system_frontiers_match": frontiers_match,
        "correctness_admitted": True,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--spine-profile", type=Path, default=DEFAULT_SPINE_PROFILE)
    parser.add_argument("--grasu-profile", type=Path, default=DEFAULT_GRASU_PROFILE)
    parser.add_argument(
        "--capability-catalog", type=Path, default=DEFAULT_CAPABILITIES
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build/sst")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--run-id", action="append", dest="run_ids")
    parser.add_argument("--role", action="append", dest="roles")
    parser.add_argument("--epsilon", action="append", type=float, dest="epsilons")
    parser.add_argument("--architecture", action="append", dest="architectures")
    parser.add_argument(
        "--downstream-sharing", choices=("direct", "shared"), default="direct"
    )
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--max-cycles", type=int, default=1_000_000_000)
    parser.add_argument("--reuse-results", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    epsilons = tuple(args.epsilons or (1.0e-6,))
    architectures = tuple(args.architectures or ("spine", "grasu_regraph"))
    if (
        args.jobs <= 0
        or args.timeout_seconds <= 0.0
        or args.max_cycles <= 0
        or any(epsilon <= 0.0 for epsilon in epsilons)
        or any(value not in {"spine", "grasu_regraph"} for value in architectures)
    ):
        raise ValueError("matrix timing, epsilons, and architectures must be valid")
    manifest = _validate_input_manifest(args.manifest.resolve())
    runs = list(manifest["runs"])
    if args.run_ids:
        requested = set(args.run_ids)
        runs = [run for run in runs if run["run_id"] in requested]
        missing = requested - {run["run_id"] for run in runs}
        if missing:
            raise ValueError(f"unknown run IDs: {sorted(missing)}")
    if args.roles:
        roles = set(args.roles)
        runs = [run for run in runs if run["role"] in roles]
    if not runs:
        raise ValueError("Delta.hls residual matrix selection is empty")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    work = [
        (run, architecture, epsilon)
        for run in runs
        for epsilon in epsilons
        for architecture in architectures
    ]
    rows: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                _run_case, run, architecture, epsilon, args=args
            ): (run["run_id"], architecture, epsilon)
            for run, architecture, epsilon in work
        }
        for future in concurrent.futures.as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: (row["run_id"], row["epsilon"], row["architecture"]))
    pairs = []
    by_case: dict[tuple[str, float], dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_case.setdefault((row["run_id"], row["epsilon"]), {})[
            row["architecture"]
        ] = row
    for systems in by_case.values():
        if {"spine", "grasu_regraph"}.issubset(systems):
            pairs.append(_pair(systems["spine"], systems["grasu_regraph"]))
    pairs.sort(key=lambda row: (row["run_id"], row["epsilon"]))
    compact_rows = [
        {k: v for k, v in row.items() if k not in {"ranks", "residuals", "frontier_in", "frontier_out"}}
        for row in rows
    ]
    _write_csv(args.out_dir / "runs.csv", compact_rows)
    if pairs:
        _write_csv(args.out_dir / "pairs.csv", pairs)
    summary = {
        "schema_version": 1,
        "matrix_id": "deltahls_per_vertex_residual_comparison_v1",
        "residual_contract": DELTA_CONTRACT,
        "threshold_semantics": "activate_vertex_when_abs_residual_gt_epsilon",
        "stopping_norm": "linf",
        "not_gap_global_l1": True,
        "damping": DAMPING,
        "epsilons": epsilons,
        "max_iterations": MAX_ITERATIONS,
        "input_manifest": _display_path(args.manifest),
        "input_manifest_sha256": sha256_file(args.manifest.resolve()),
        "spine_profile_sha256": sha256_file(args.spine_profile.resolve()),
        "grasu_profile_sha256": sha256_file(args.grasu_profile.resolve()),
        "capability_catalog_sha256": sha256_file(args.capability_catalog.resolve()),
        "grasu_downstream_sharing": args.downstream_sharing,
        "sst_plugin_sha256": sha256_file(args.lib_dir.resolve() / "libspine_cycle.so"),
        "runs": compact_rows,
        "pairs": pairs,
        "all_correct": all(row["correctness_mismatches"] == 0 for row in rows),
        "matrix_wall_seconds": time.monotonic() - started,
        "limitations": [
            "The input is a reciprocal sink-free transform of a compact real Flickr slice.",
            "The threshold is per vertex and is not the GAP global-L1 stopping rule.",
            "Insert batches are synthetic and nested on the frozen real topology.",
            "Cycles are execution-driven simulator results, not FPGA cycle calibration.",
        ],
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"PASS Delta.hls residual matrix: rows={len(rows)} pairs={len(pairs)} "
        f"wall_s={summary['matrix_wall_seconds']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
