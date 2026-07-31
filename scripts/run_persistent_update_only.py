#!/usr/bin/env python3
"""Run one correctness-gated persistent update-only comparison."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.persistent_update_only import (  # noqa: E402
    HostRuntimeModel,
    analyze_persistent_update_pair,
)


DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_LIB_DIR = ROOT / "build/sst"
DEFAULT_HOST_TOOL = ROOT / "build/cpp/persistent_update_host_benchmark"
SPINE_CHANNELS = tuple(range(32))
GRASU_PMA_CHANNELS = (0, 1, 2, 3)
SPINE_MAX_VERTICES = 1 << 24


def _slice_vertices(path: Path) -> int:
    with path.open("r", encoding="ascii") as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if line.startswith("# vertices="):
                vertices = int(line.split("=", 1)[1])
                if vertices <= 0:
                    break
                return vertices
            if line and not line.startswith("#"):
                break
    raise ValueError(f"slice has no positive vertices metadata: {path}")


def _run_sst(
    *,
    name: str,
    config: Path,
    environment: Mapping[str, str],
    out_dir: Path,
    sst: Path,
    lib_dir: Path,
) -> tuple[dict[str, object], float]:
    run_dir = out_dir / name
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "result.json"
    if result_path.exists():
        result_path.unlink()
    env = os.environ.copy()
    env.update(environment)
    command = [
        str(sst.resolve()),
        f"--add-lib-path={lib_dir.resolve()}",
        str(config.resolve()),
    ]
    start = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    wall_seconds = time.monotonic() - start
    (run_dir / "sst.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(
            f"{name} SST failed with rc={completed.returncode}; "
            f"see {run_dir / 'sst.log'}"
        )
    if not result_path.is_file():
        raise RuntimeError(f"{name} SST did not produce {result_path}")
    return json.loads(result_path.read_text(encoding="utf-8")), wall_seconds


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--scenario", default="insert")
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--updates", type=Path, required=True)
    parser.add_argument("--batch-count", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIB_DIR)
    parser.add_argument("--host-tool", type=Path, default=DEFAULT_HOST_TOOL)
    parser.add_argument("--host-repeats", type=int, default=3)
    parser.add_argument("--max-cycles", type=int, default=2_000_000_000)
    parser.add_argument("--h2d-gbps", type=float, default=12.0)
    parser.add_argument("--launch-sync-us", type=float, default=10.0)
    args = parser.parse_args()

    if args.batch_count <= 0 or args.host_repeats <= 0 or args.max_cycles <= 0:
        parser.error("batch-count, host-repeats, and max-cycles must be positive")
    if args.scenario == "weight_change":
        parser.error(
            "the frozen Spine differential merge cannot represent a weight "
            "increase in pure update-only mode; evaluate its full-rebuild "
            "fallback instead"
        )
    graph = args.graph.resolve()
    updates = args.updates.resolve()
    for path in (graph, updates, args.sst, args.host_tool):
        if not path.is_file():
            parser.error(f"required file does not exist: {path}")
    if not args.lib_dir.is_dir():
        parser.error(f"SST library directory does not exist: {args.lib_dir}")
    graph_vertices = _slice_vertices(graph)
    update_vertices = _slice_vertices(updates)
    if graph_vertices != update_vertices:
        parser.error("graph and update slices have different vertex counts")
    if graph_vertices > SPINE_MAX_VERTICES:
        parser.error(
            f"graph has {graph_vertices} vertices, exceeding the frozen Spine "
            f"MAX_N={SPINE_MAX_VERTICES}; use a separately labeled bounded slice"
        )

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    common = {
        "SPINE_CAMPAIGN_PROGRESS_INTERVAL_CYCLES": "1000000",
    }
    spine_result, spine_wall = _run_sst(
        name="spine",
        config=ROOT / "sst/spine_vertical_slice.py",
        environment={
            **common,
            "SPINE_SST_MODE": "spine_update_trace",
            "SPINE_SST_WORKLOAD": str(graph),
            "SPINE_SST_UPDATE_WORKLOAD": str(updates),
            "SPINE_SST_UPDATE_BATCH_COUNT": str(args.batch_count),
            "SPINE_SST_OUTPUT": str(out_dir / "spine/result.json"),
            "SPINE_SST_DRAM_OUTPUT": str(out_dir / "spine/dram"),
            "SPINE_SST_CHANNELS": "32",
            "SPINE_SST_ACTIVE_CHANNELS": ",".join(map(str, SPINE_CHANNELS)),
            "SPINE_SST_CORE_MHZ": "141",
            "SPINE_SST_MAX_CYCLES": str(args.max_cycles),
        },
        out_dir=out_dir,
        sst=args.sst,
        lib_dir=args.lib_dir,
    )
    grasu_result, grasu_wall = _run_sst(
        name="grasu",
        config=ROOT / "sst/grasu_regraph_vertical.py",
        environment={
            **common,
            "GRASU_SST_MODE": "grasu_update_trace",
            "GRASU_SST_WORKLOAD": str(graph),
            "GRASU_SST_UPDATE_WORKLOAD": str(updates),
            "GRASU_SST_UPDATE_BATCH_COUNT": str(args.batch_count),
            "GRASU_SST_OUTPUT": str(out_dir / "grasu/result.json"),
            "GRASU_SST_DRAM_OUTPUT": str(out_dir / "grasu/dram"),
            "GRASU_SST_CHANNELS": "32",
            "GRASU_SST_ACTIVE_CHANNELS": ",".join(
                map(str, GRASU_PMA_CHANNELS)
            ),
            "GRASU_SST_CORE_MHZ": "150",
            "GRASU_SST_MAX_CYCLES": str(args.max_cycles),
            "GRASU_SST_PARTITION_VERTICES": "65536",
            "GRASU_SST_PACKED_PARTITION_ADDRESSES": "1",
        },
        out_dir=out_dir,
        sst=args.sst,
        lib_dir=args.lib_dir,
    )

    host_command = [
        str(args.host_tool.resolve()),
        str(graph),
        str(updates),
        str(args.batch_count),
        "65536",
        str(args.host_repeats),
    ]
    host_start = time.monotonic()
    host_completed = subprocess.run(
        host_command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    host_wall = time.monotonic() - host_start
    (out_dir / "host.log").write_text(host_completed.stderr, encoding="utf-8")
    if host_completed.returncode != 0:
        raise RuntimeError(
            f"host benchmark failed with rc={host_completed.returncode}; "
            f"see {out_dir / 'host.log'}"
        )
    host = json.loads(host_completed.stdout)
    _write_json(out_dir / "host.json", host)

    comparison = analyze_persistent_update_pair(
        dataset_id=args.dataset,
        scenario=args.scenario,
        host=host,
        spine_result=spine_result,
        grasu_result=grasu_result,
        runtime=HostRuntimeModel(args.h2d_gbps, args.launch_sync_us),
    )
    _write_json(out_dir / "comparison.json", comparison)
    manifest = {
        "schema_version": 1,
        "dataset": args.dataset,
        "scenario": args.scenario,
        "graph": str(graph),
        "updates": str(updates),
        "vertices": graph_vertices,
        "batch_count": args.batch_count,
        "host_repeats": args.host_repeats,
        "max_cycles": args.max_cycles,
        "memory_backend": "sst_memHierarchy_dramsim3",
        "spine_active_channels": list(SPINE_CHANNELS),
        "grasu_active_channels": list(GRASU_PMA_CHANNELS),
        "grasu_partition_vertices": 65536,
        "grasu_trace_aware": True,
        "grasu_packed_partition_addresses": True,
        "wall_seconds": {
            "spine_sst": spine_wall,
            "grasu_sst": grasu_wall,
            "host_benchmark": host_wall,
        },
    }
    _write_json(out_dir / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "dataset": args.dataset,
                "logical_updates": comparison["logical_updates"],
                "batch_count": comparison["batch_count"],
                "spine_speedup": comparison["spine_speedup"],
                "wall_seconds": manifest["wall_seconds"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
