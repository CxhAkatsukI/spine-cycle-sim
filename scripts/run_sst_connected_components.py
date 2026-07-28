#!/usr/bin/env python3
"""Run one correctness-gated dynamic CC case on SST-HBM."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.connected_components_workloads import (  # noqa: E402
    ReciprocalUpdateAnalysis,
    analyze_reciprocal_update,
    connected_components_labels,
    materialize_reciprocal_update,
)
from spine_cycle_sim.experiments.shared_workloads import (  # noqa: E402
    load_slice,
    sha256_file,
)


DEFAULT_WORKLOAD = ROOT / "tests/data/connected_components_bridge_initial.slice"
DEFAULT_UPDATE = ROOT / "tests/data/connected_components_bridge_insert.slice"
DEFAULT_WRAPPER = ROOT / "scripts/run_sst_exact_idle_dramsim3.sh"
DEFAULT_SST_INSTALL_PREFIX = Path(
    "/data/tmp/chuxiao/candidate10-idle-script-repro-v1-install"
)
DEFAULT_DRAMSIM3_SRC = Path(
    "/data/tmp/chuxiao/candidate10-idle-script-repro-v1/dramsim3"
)


def expected_update_mode(analysis: ReciprocalUpdateAnalysis) -> str:
    if analysis.zero_net:
        return "zero_net_no_repair"
    if analysis.deletions:
        return "deletion_full_recompute"
    return "insertion_incremental_repair"


def validate_result(
    result: dict[str, Any],
    *,
    architecture: str,
    expected_labels: tuple[int, ...],
    analysis: ReciprocalUpdateAnalysis,
    compute_pipelines: int,
) -> dict[str, bool]:
    expected_mode = (
        "spine_connected_components"
        if architecture == "spine"
        else "grasu_regraph_connected_components"
    )
    labels = tuple(int(value) for value in result.get("labels", []))
    checks = {
        "success": result.get("success") is True,
        "mode": result.get("mode") == expected_mode,
        "algorithm_contract": result.get("algorithm_contract")
        == "weakly_connected_min_vertex_reciprocal_v1",
        "dual_oracle": result.get("architecture_correctness_mismatches") == 0
        and result.get("mathematical_correctness_mismatches") == 0
        and result.get("correctness_mismatches") == 0,
        "external_labels": labels == expected_labels,
        "converged": result.get("converged") is True
        and bool(result.get("frontier_out_sizes"))
        and result["frontier_out_sizes"][-1] == 0,
        "update_mode": result.get("update_mode") == expected_update_mode(analysis),
        "effective_mutations": result.get("logical_mutations")
        == analysis.effective_mutations,
        "physical_records": result.get("physical_update_records")
        == analysis.physical_records,
        "active_edge_ledger": result.get("active_edge_execution_ledger_match")
        is True,
        "memory_ledger": result.get("memory_locality_ledger_match") is True,
        "zero_net_no_analytic_work": (not analysis.zero_net)
        or (
            result.get("initial_active_vertices") == 0
            and result.get("active_edges") == 0
        ),
    }
    if architecture == "grasu":
        checks.update(
            {
                "conversion_free": result.get("conversion_cost_included") is False,
                "pma_state": result.get("update_state_mismatches") == 0,
                "compute_pipelines": result.get("compute_pipelines")
                == compute_pipelines,
                "partition_work": result.get("partition_passes")
                == result.get("destination_partitions")
                * result.get("iterations"),
            }
        )
    return checks


def _git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", choices=("spine", "grasu"), required=True)
    parser.add_argument("--workload", type=Path, default=DEFAULT_WORKLOAD)
    parser.add_argument("--update-workload", type=Path, default=DEFAULT_UPDATE)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--wrapper", type=Path, default=DEFAULT_WRAPPER)
    parser.add_argument(
        "--sst-install-prefix", type=Path, default=DEFAULT_SST_INSTALL_PREFIX
    )
    parser.add_argument("--dramsim3-src", type=Path, default=DEFAULT_DRAMSIM3_SRC)
    parser.add_argument("--core-mhz", type=float, default=150.0)
    parser.add_argument("--max-cycles", type=int, default=1_000_000_000)
    parser.add_argument("--max-rounds", type=int, default=4096)
    parser.add_argument("--partition-vertices", type=int, default=65_536)
    parser.add_argument("--compute-pipelines", type=int, default=1)
    parser.add_argument("--source-buffer-vertices", type=int, default=4096)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--reuse-result", action="store_true")
    args = parser.parse_args()
    if (
        args.core_mhz <= 0
        or args.max_cycles <= 0
        or args.max_rounds <= 0
        or args.compute_pipelines <= 0
        or args.partition_vertices <= 0
    ):
        raise ValueError("CC runner timing and architecture parameters must be positive")

    workload_path = args.workload.resolve()
    update_path = args.update_workload.resolve()
    graph = load_slice(workload_path)
    update = load_slice(update_path)
    analysis = analyze_reciprocal_update(graph, update)
    final_graph = materialize_reciprocal_update(graph, update)
    oracle_labels = connected_components_labels(final_graph)

    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    plugin = ROOT / "build/sst/libspine_cycle.so"
    if not plugin.is_file():
        raise FileNotFoundError(f"missing SST plugin: {plugin}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result_path = (args.out_dir / "result.json").resolve()
    log_path = args.out_dir / "sst.log"
    dram_path = (args.out_dir / "dram").resolve()
    if not args.reuse_result:
        result_path.unlink(missing_ok=True)
        shutil.rmtree(dram_path, ignore_errors=True)

    env = os.environ.copy()
    env.update(
        {
            "SPINE_IDLE_SST_INSTALL_PREFIX": str(args.sst_install_prefix.resolve()),
            "SPINE_IDLE_DRAMSIM3_SRC": str(args.dramsim3_src.resolve()),
        }
    )
    if args.architecture == "spine":
        env.update(
            {
                "SPINE_SST_MODE": "spine_connected_components",
                "SPINE_SST_WORKLOAD": str(workload_path),
                "SPINE_SST_UPDATE_WORKLOAD": str(update_path),
                "SPINE_SST_OUTPUT": str(result_path),
                "SPINE_SST_DRAM_OUTPUT": str(dram_path),
                "SPINE_SST_CHANNELS": "32",
                "SPINE_SST_ACTIVE_CHANNELS": ",".join(str(value) for value in range(23)),
                "SPINE_SST_CORE_MHZ": str(args.core_mhz),
                "SPINE_SST_MAX_CYCLES": str(args.max_cycles),
                "SPINE_SST_MAX_ROUNDS": str(args.max_rounds),
            }
        )
        sst_config = ROOT / "sst/spine_vertical_slice.py"
    else:
        env.update(
            {
                "GRASU_SST_MODE": "grasu_regraph_connected_components",
                "GRASU_SST_WORKLOAD": str(workload_path),
                "GRASU_SST_UPDATE_WORKLOAD": str(update_path),
                "GRASU_SST_OUTPUT": str(result_path),
                "GRASU_SST_DRAM_OUTPUT": str(dram_path),
                "GRASU_SST_CHANNELS": "32",
                "GRASU_SST_ACTIVE_CHANNELS": "0,1,2,3,30",
                "GRASU_SST_CORE_MHZ": str(args.core_mhz),
                "GRASU_SST_MAX_CYCLES": str(args.max_cycles),
                "GRASU_SST_MAX_ROUNDS": str(args.max_rounds),
                "GRASU_SST_PARTITION_VERTICES": str(args.partition_vertices),
                "GRASU_SST_COMPUTE_PIPELINES": str(args.compute_pipelines),
                "GRASU_SST_SOURCE_BUFFER_VERTICES": str(args.source_buffer_vertices),
            }
        )
        sst_config = ROOT / "sst/grasu_regraph_vertical.py"

    start = time.monotonic()
    if not args.reuse_result:
        completed = subprocess.run(
            [str(args.wrapper.resolve()), str(sst_config)],
            cwd=ROOT,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log_path.write_text(completed.stdout, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"SST CC run failed with rc={completed.returncode}; see {log_path}"
            )
    wall_seconds = time.monotonic() - start
    result = json.loads(result_path.read_text(encoding="utf-8"))
    checks = validate_result(
        result,
        architecture=args.architecture,
        expected_labels=oracle_labels,
        analysis=analysis,
        compute_pipelines=args.compute_pipelines,
    )
    failed = [name for name, passed in checks.items() if not passed]
    manifest = {
        "schema_version": 1,
        "architecture": args.architecture,
        "source_revision": _git_revision(),
        "algorithm_contract": "weakly_connected_min_vertex_reciprocal_v1",
        "workload": str(workload_path),
        "workload_sha256": sha256_file(workload_path),
        "update_workload": str(update_path),
        "update_sha256": sha256_file(update_path),
        "sst_plugin": str(plugin),
        "sst_plugin_sha256": sha256_file(plugin),
        "sst_install_prefix": str(args.sst_install_prefix.resolve()),
        "dramsim3_src": str(args.dramsim3_src.resolve()),
        "core_mhz": args.core_mhz,
        "compute_pipelines": args.compute_pipelines if args.architecture == "grasu" else 1,
        "partition_vertices": args.partition_vertices if args.architecture == "grasu" else None,
        "logical_user_mutations": analysis.logical_user_mutations,
        "effective_mutations": analysis.effective_mutations,
        "physical_records": analysis.physical_records,
        "update_mode": expected_update_mode(analysis),
        "sst_host_wall_seconds": wall_seconds,
        "checks": checks,
        "admitted": not failed,
    }
    (args.out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    if failed:
        raise AssertionError(f"CC result failed admission checks: {', '.join(failed)}")
    print(
        f"PASS {args.architecture} CC: cycles={result['cycles']} "
        f"iterations={result['iterations']} components={result['components']} "
        f"K={manifest['compute_pipelines']} wall={wall_seconds:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
