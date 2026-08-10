#!/usr/bin/env python3
"""Build current-model update-only evidence for evaluation-refresh Fig. 8."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORMAL_ROOT = (
    Path("/data/tmp/chuxiao/large_graph_campaign_v1")
    / "formal_v8_au_update_scaling"
)
DEFAULT_HOST_TOOL = (
    Path("/data/tmp/chuxiao/spine-cycle-sim-sharded-k4-v3-build")
    / "cpp"
    / "persistent_update_host_benchmark"
)


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.persistent_update_only import (  # noqa: E402
    HostRuntimeModel,
    analyze_persistent_update_pair,
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def directed_insert_updates(materialization: dict[str, Any]) -> dict[int, Path]:
    updates: dict[int, Path] = {}
    for artifact in materialization.get("updates", []):
        if (
            artifact.get("projection") == "directed"
            and artifact.get("scenario") == "insert"
        ):
            updates[int(artifact["user_mutations"])] = Path(str(artifact["path"]))
    return updates


def case_result(formal_root: Path, system: str, updates: int) -> dict[str, Any]:
    path = formal_root / "runs_update_only" / f"{system}_u{updates}" / "case_result.json"
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = load_json(path)
    if str(payload.get("status", "")).lower() != "pass":
        raise ValueError(f"case result did not pass: {path}")
    return payload


def update_traffic(raw: dict[str, Any]) -> dict[str, Any]:
    traffic = raw.get("update_backend_traffic", raw.get("backend_traffic"))
    if not isinstance(traffic, dict):
        return {"combined": {"requests": 0, "bytes": 0}}
    return traffic


def pure_result_from_case(case: dict[str, Any], system: str) -> dict[str, Any]:
    raw = load_json(Path(str(case["raw_result_path"])))
    row = case["row"]
    if system == "spine":
        cycles = int(raw.get("maintenance_cycles", row.get("cycles", 0)))
        mode = "spine_maintenance_from_current_dynamic_run"
    else:
        cycles = int(raw.get("update_cycles", row.get("cycles", 0)))
        mode = "grasu_update_from_current_dynamic_run"
    if cycles <= 0:
        raise ValueError(f"non-positive update-only cycles for {system}")
    correctness = int(raw.get("correctness_mismatches", 0))
    correctness += int(raw.get("architecture_correctness_mismatches", 0))
    correctness += int(raw.get("mathematical_correctness_mismatches", 0))
    return {
        "success": bool(raw.get("success", False)),
        "mode": mode,
        "measurement_window": "pure_update_only",
        "graph_compute_executed": False,
        "resident_state_persistent": True,
        "core_mhz": float(row["core_mhz"]),
        "logical_updates": int(row["updates"]),
        "batch_count": 1,
        "device_cycles": cycles,
        "correctness_mismatches": correctness,
        "backend_traffic": update_traffic(raw),
        "raw_result_path": case["raw_result_path"],
        "raw_result_sha256": case.get("raw_result_sha256", ""),
        "source_measurement_window": row.get("measurement_window", ""),
    }


def run_host_benchmark(
    *,
    host_tool: Path,
    graph: Path,
    updates: Path,
    partition_vertices: int,
    host_repeats: int,
) -> dict[str, Any]:
    command = [
        str(host_tool.resolve()),
        str(graph.resolve()),
        str(updates.resolve()),
        "1",
        str(partition_vertices),
        str(host_repeats),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"host benchmark failed with rc={completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def build_one(
    *,
    formal_root: Path,
    materialization: dict[str, Any],
    update_paths: dict[int, Path],
    updates: int,
    host_tool: Path,
    partition_vertices: int,
    host_repeats: int,
    runtime: HostRuntimeModel,
    dataset_id: str,
    out_dir: Path,
) -> None:
    if updates not in update_paths:
        raise ValueError(f"missing directed insert update slice for {updates}")
    graph = Path(str(materialization["graphs"]["directed"]["path"]))
    host = run_host_benchmark(
        host_tool=host_tool,
        graph=graph,
        updates=update_paths[updates],
        partition_vertices=partition_vertices,
        host_repeats=host_repeats,
    )
    spine_case = case_result(formal_root, "spine", updates)
    grasu_case = case_result(formal_root, "grasu_regraph_k4_shared", updates)
    spine = pure_result_from_case(spine_case, "spine")
    grasu = pure_result_from_case(grasu_case, "grasu_regraph")
    comparison = analyze_persistent_update_pair(
        dataset_id=dataset_id,
        scenario="insert",
        host=host,
        spine_result=spine,
        grasu_result=grasu,
        runtime=runtime,
    )
    write_json(out_dir / "host.json", host)
    write_json(out_dir / "spine.json", spine)
    write_json(out_dir / "grasu.json", grasu)
    write_json(out_dir / "comparison.json", comparison)
    write_json(
        out_dir / "manifest.json",
        {
            "schema_version": 1,
            "status": "PASS",
            "dataset_id": dataset_id,
            "source_formal_root": str(formal_root),
            "graph": str(graph),
            "updates": str(update_paths[updates]),
            "logical_updates": updates,
            "host_repeats": host_repeats,
            "partition_vertices": partition_vertices,
            "device_cycle_source": {
                "spine": "raw maintenance_cycles from current dynamic run",
                "grasu_regraph": "raw update_cycles from current dynamic run",
            },
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formal-root", type=Path, default=DEFAULT_FORMAL_ROOT)
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--dataset-id", default="sx_askubuntu")
    parser.add_argument("--dataset-key", default="au")
    parser.add_argument("--host-tool", type=Path, default=DEFAULT_HOST_TOOL)
    parser.add_argument("--host-repeats", type=int, default=3)
    parser.add_argument("--partition-vertices", type=int, default=65536)
    parser.add_argument("--h2d-gbps", type=float, default=12.0)
    parser.add_argument("--launch-sync-us", type=float, default=10.0)
    parser.add_argument(
        "--batch-update-count",
        action="append",
        type=int,
        dest="batch_update_counts",
    )
    parser.add_argument("--cross-update-count", type=int, default=1024)
    args = parser.parse_args()
    if args.host_repeats <= 0 or args.partition_vertices <= 0:
        raise ValueError("host repeats and partition vertices must be positive")
    formal_root = args.formal_root.resolve()
    materialization = load_json(
        formal_root / "workloads" / args.dataset_id / "materialization_manifest.json"
    )
    update_paths = directed_insert_updates(materialization)
    batch_counts = (
        tuple(args.batch_update_counts)
        if args.batch_update_counts
        else tuple(sorted(update_paths))
    )
    out_root = args.out_root.resolve()
    runtime = HostRuntimeModel(args.h2d_gbps, args.launch_sync_us)
    for updates in batch_counts:
        build_one(
            formal_root=formal_root,
            materialization=materialization,
            update_paths=update_paths,
            updates=updates,
            host_tool=args.host_tool,
            partition_vertices=args.partition_vertices,
            host_repeats=args.host_repeats,
            runtime=runtime,
            dataset_id=args.dataset_id,
            out_dir=out_root / "batch_sensitivity" / f"b{updates}",
        )
    build_one(
        formal_root=formal_root,
        materialization=materialization,
        update_paths=update_paths,
        updates=args.cross_update_count,
        host_tool=args.host_tool,
        partition_vertices=args.partition_vertices,
        host_repeats=args.host_repeats,
        runtime=runtime,
        dataset_id=args.dataset_id,
        out_dir=out_root / "cross_dataset" / args.dataset_key,
    )
    write_json(
        out_root / "manifest.json",
        {
            "schema_version": 1,
            "status": "PARTIAL_CURRENT_MODEL_DATA",
            "metric": "setup_inclusive_update_only_throughput",
            "dataset_id": args.dataset_id,
            "dataset_key": args.dataset_key,
            "source_formal_root": str(formal_root),
            "batch_update_counts": list(batch_counts),
            "cross_update_count": args.cross_update_count,
            "note": (
                "Partial current-model evidence. It covers one dataset and "
                "must not be promoted to Fig. 8 PASS_CURRENT_MODEL_DATA."
            ),
        },
    )
    print(
        f"FIG8_CURRENT_UPDATE_ONLY_PARTIAL dataset={args.dataset_id} "
        f"batch={len(batch_counts)} out={out_root}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
