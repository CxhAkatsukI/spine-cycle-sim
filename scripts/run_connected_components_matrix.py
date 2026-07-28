#!/usr/bin/env python3
"""Run and summarize the frozen dynamic connected-components SST matrix."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "configs/experiments/connected_components_formal_v1.json"


def _run_case(
    run: dict[str, Any],
    architecture: str,
    out_dir: Path,
    *,
    compute_pipelines: int,
    downstream_sharing: str,
    partition_vertices: int,
    max_cycles: int,
    max_rounds: int,
    reuse_results: bool,
) -> dict[str, Any]:
    destination = out_dir / run["run_id"] / (
        "spine_k1"
        if architecture == "spine"
        else f"grasu_k{compute_pipelines}_{downstream_sharing}"
    )
    legacy_destination = out_dir / run["run_id"] / f"grasu_k{compute_pipelines}"
    if (
        reuse_results
        and architecture == "grasu"
        and not (destination / "result.json").is_file()
        and (legacy_destination / "result.json").is_file()
    ):
        destination = legacy_destination
    command = [
        sys.executable,
        str(ROOT / "scripts/run_sst_connected_components.py"),
        "--architecture",
        architecture,
        "--workload",
        str(ROOT / run["graph"]["path"]),
        "--update-workload",
        str(ROOT / run["update"]["path"]),
        "--out-dir",
        str(destination),
        "--max-cycles",
        str(max_cycles),
        "--max-rounds",
        str(max_rounds),
        "--no-build",
    ]
    if architecture == "grasu":
        command.extend(
            [
                "--compute-pipelines",
                str(compute_pipelines),
                "--partition-vertices",
                str(partition_vertices),
                "--downstream-sharing",
                downstream_sharing,
            ]
        )
    if reuse_results:
        command.append("--reuse-result")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{run['run_id']} {architecture} failed:\n{completed.stdout}"
        )
    result = json.loads((destination / "result.json").read_text(encoding="utf-8"))
    admission = json.loads(
        (destination / "run_manifest.json").read_text(encoding="utf-8")
    )
    traffic = result.get("backend_traffic", {})
    return {
        "run_id": run["run_id"],
        "workload_class": run["workload_class"],
        "role": run["role"],
        "architecture": architecture,
        "compute_pipelines": 1 if architecture == "spine" else compute_pipelines,
        "downstream_sharing": (
            "native" if architecture == "spine" else downstream_sharing
        ),
        "vertices": run["graph"]["vertices"],
        "initial_edges": run["graph"]["records"],
        "logical_user_mutations": run["logical_user_mutations"],
        "effective_mutations": run["effective_mutations"],
        "physical_records": run["physical_records"],
        "initial_components": run["initial_components"],
        "final_components": run["final_components"],
        "cycles": result["cycles"],
        "time_us_at_150mhz": float(result["cycles"]) / 150.0,
        "iterations": result["iterations"],
        "active_edges": result["active_edges"],
        "backend_requests": result["backend_requests"],
        "read_bytes": traffic.get("reads", {}).get("bytes", 0),
        "write_bytes": traffic.get("writes", {}).get("bytes", 0),
        "hbm_queue_stalls": result.get("backend_submit_stalls", 0),
        "hbm_response_queue_stalls": result.get(
            "backend_response_queue_stalls", 0
        ),
        "destination_partitions": result.get("destination_partitions", 1),
        "max_parallel_partitions": result.get("max_parallel_partitions", 1),
        "max_parallel_downstream_partitions": result.get(
            "max_parallel_downstream_partitions", 1
        ) or 1,
        "correctness_mismatches": result["correctness_mismatches"],
        "performance_admitted": admission["admitted"]
        and run["effective_mutations"] > 0,
        "sst_host_wall_seconds": admission["sst_host_wall_seconds"],
        "source_revision": admission["source_revision"],
        "workload_sha256": admission["workload_sha256"],
        "update_sha256": admission["update_sha256"],
        "sst_plugin_sha256": admission["sst_plugin_sha256"],
        "result_path": str((destination / "result.json").resolve()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--run-id", action="append", dest="run_ids")
    parser.add_argument("--role", action="append", dest="roles")
    parser.add_argument(
        "--architecture",
        action="append",
        choices=("spine", "grasu"),
        dest="architectures",
    )
    parser.add_argument("--compute-pipelines", type=int, default=1)
    parser.add_argument(
        "--downstream-sharing", choices=("direct", "shared"), default="direct"
    )
    parser.add_argument("--partition-vertices", type=int, default=65_536)
    parser.add_argument("--max-cycles", type=int, default=1_000_000_000)
    parser.add_argument("--max-rounds", type=int, default=4096)
    parser.add_argument("--max-concurrent", type=int, default=2)
    parser.add_argument("--reuse-results", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if args.max_concurrent <= 0 or args.compute_pipelines <= 0:
        raise ValueError("matrix concurrency and compute pipelines must be positive")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    runs = manifest["runs"]
    if args.run_ids:
        selected = set(args.run_ids)
        runs = [run for run in runs if run["run_id"] in selected]
        missing = selected - {run["run_id"] for run in runs}
        if missing:
            raise ValueError(f"unknown CC run IDs: {sorted(missing)}")
    if args.roles:
        roles = set(args.roles)
        runs = [run for run in runs if run["role"] in roles]
    if not runs:
        raise ValueError("CC matrix selection is empty")
    architectures = tuple(args.architectures or ("spine", "grasu"))
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    work = [(run, architecture) for run in runs for architecture in architectures]
    rows: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.max_concurrent
    ) as executor:
        futures = {
            executor.submit(
                _run_case,
                run,
                architecture,
                args.out_dir,
                compute_pipelines=args.compute_pipelines,
                downstream_sharing=args.downstream_sharing,
                partition_vertices=args.partition_vertices,
                max_cycles=args.max_cycles,
                max_rounds=args.max_rounds,
                reuse_results=args.reuse_results,
            ): (run["run_id"], architecture)
            for run, architecture in work
        }
        for future in concurrent.futures.as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: (row["run_id"], row["architecture"]))

    fieldnames = list(rows[0])
    with (args.out_dir / "runs.csv").open("w", encoding="ascii", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    by_run: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        by_run.setdefault(row["run_id"], {})[row["architecture"]] = row
    pairs = []
    for run_id, architectures_by_id in sorted(by_run.items()):
        if {"spine", "grasu"}.issubset(architectures_by_id):
            spine = architectures_by_id["spine"]
            grasu = architectures_by_id["grasu"]
            pairs.append(
                {
                    "run_id": run_id,
                    "role": spine["role"],
                    "workload_class": spine["workload_class"],
                    "spine_cycles": spine["cycles"],
                    "grasu_cycles": grasu["cycles"],
                    "spine_speedup_over_grasu": grasu["cycles"] / spine["cycles"],
                    "performance_admitted": spine["performance_admitted"]
                    and grasu["performance_admitted"],
                }
            )
    summary = {
        "schema_version": 1,
        "matrix_id": manifest["matrix_id"],
        "compute_pipelines": args.compute_pipelines,
        "downstream_sharing": args.downstream_sharing,
        "partition_vertices": args.partition_vertices,
        "rows": rows,
        "pairs": pairs,
        "all_correct": all(row["correctness_mismatches"] == 0 for row in rows),
        "all_admission_checks_passed": all(
            row["performance_admitted"] or row["effective_mutations"] == 0
            for row in rows
        ),
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        f"PASS CC matrix: cases={len(runs)} rows={len(rows)} "
        f"pairs={len(pairs)} out={args.out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
