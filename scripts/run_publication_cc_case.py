#!/usr/bin/env python3
"""Run one correctness-gated Connected Components publication execution."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.large_graph_campaign import (  # noqa: E402
    load_large_graph_campaign_contract,
)
from spine_cycle_sim.experiments.publication_cases import (  # noqa: E402
    architecture_profile_path,
    comparison_run,
    load_materialization_manifest,
    publication_dataset_labels,
    select_publication_case,
)
from spine_cycle_sim.experiments.publication_workloads import sha256_file  # noqa: E402


DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_LIB_DIR = Path(
    "/data/tmp/chuxiao/candidate86-cc-unweighted-native-pgo-build-20260729"
)
DEFAULT_CAPABILITY = (
    ROOT / "configs/contracts/grasu_regraph_publication_capabilities_v6.json"
)


def final_state_identity(result: Mapping[str, Any]) -> dict[str, Any]:
    labels = result.get("labels")
    if not isinstance(labels, list):
        raise ValueError("formal CC result lacks its full label vector")
    encoded = json.dumps(labels, separators=(",", ":")).encode("ascii")
    return {
        "field": "labels",
        "count": len(labels),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def scalar_metrics(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if isinstance(value, (bool, int, float, str)) or value is None
    }


def expected_profile_hash(
    contract: Mapping[str, Any], system: str, algorithm: str
) -> str:
    baselines = contract["architecture_baselines"]
    if system == "spine":
        return str(baselines["spine"]["sha256"])
    return str(baselines[system]["profiles"][algorithm][1])


def result_row(
    case: Any,
    result: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    wall_seconds: float,
) -> dict[str, Any]:
    dataset_kind, role = publication_dataset_labels(case.dataset_id)
    traffic = result.get("backend_traffic", {})
    reads = traffic.get("reads", {}) if isinstance(traffic, Mapping) else {}
    writes = traffic.get("writes", {}) if isinstance(traffic, Mapping) else {}
    cycles = int(result["cycles"])
    clock_mhz = float(manifest["core_mhz"])
    return {
        "run_id": case.execution_id,
        "fixture_id": case.dataset_id,
        "dataset_kind": dataset_kind,
        "role": role,
        "algorithm": "connected_components",
        "reporting_algorithm": "connected_components",
        "scenario": case.scenario,
        "system": case.system,
        "architecture_profile_id": manifest["profile_id"],
        "architecture_profile_sha256": manifest["profile_sha256"],
        "vertices": int(case.graph["vertices"]),
        "initial_edges": int(case.graph["records"]),
        "update_records": int(case.update["records"]),
        "logical_user_mutations": int(case.update["user_mutations"]),
        "cycles": cycles,
        "clock_mhz": clock_mhz,
        "e2e_us": cycles / clock_mhz,
        "iterations": int(result["iterations"]),
        "active_edges": int(result["active_edges"]),
        "backend_requests": int(result["backend_requests"]),
        "read_bytes": int(reads.get("bytes", 0)),
        "write_bytes": int(writes.get("bytes", 0)),
        "dram_reads": int(manifest["dram"]["reads"]),
        "dram_writes": int(manifest["dram"]["writes"]),
        "dram_energy_pj": float(manifest["dram"]["total_energy_pj"]),
        "hbm_queue_stalls": int(result.get("backend_submit_stalls", 0)),
        "hbm_response_queue_stalls": int(
            result.get("backend_response_queue_stalls", 0)
        ),
        "destination_partitions": int(result.get("destination_partitions", 1)),
        "compute_pipelines": int(manifest["compute_pipelines"]),
        "downstream_sharing": manifest.get("downstream_sharing") or "native",
        "architecture_correctness_mismatches": int(
            result["architecture_correctness_mismatches"]
        ),
        "mathematical_correctness_mismatches": int(
            result["mathematical_correctness_mismatches"]
        ),
        "host_wall_seconds": wall_seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialization-manifest", type=Path, required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument("--algorithm", default="connected_components")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIB_DIR)
    parser.add_argument("--capability-catalog", type=Path, default=DEFAULT_CAPABILITY)
    parser.add_argument("--max-cycles", type=int, default=10_000_000_000_000)
    parser.add_argument("--logical-view", action="append", default=[])
    args = parser.parse_args()
    if args.algorithm != "connected_components":
        raise ValueError("the CC publication runner only accepts connected_components")
    if args.max_cycles <= 0:
        raise ValueError("max cycles must be positive")

    contract = load_large_graph_campaign_contract(
        args.contract
        if args.contract is not None
        else ROOT / "configs/contracts/large_graph_publication_campaign_v1.json"
    )
    materialization = load_materialization_manifest(
        args.materialization_manifest.resolve()
    )
    case = select_publication_case(
        materialization,
        system=args.system,
        algorithm="connected_components",
        scenario=args.scenario,
        batch_size=args.batch_size,
    )
    for artifact in (case.graph, case.update):
        path = Path(str(artifact["path"]))
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise ValueError(f"formal CC artifact is missing or changed: {path}")

    plugin = args.lib_dir.resolve() / "libspine_cycle.so"
    expected_plugin = contract["architecture_baselines"]["simulator_baseline"]
    if not plugin.is_file() or sha256_file(plugin) != expected_plugin["plugin_sha256"]:
        raise ValueError("formal CC SST plugin differs from the frozen baseline")
    capability_identity = contract["architecture_baselines"][
        "grasu_regraph_capability_catalog"
    ]
    if args.system != "spine" and (
        args.capability_catalog.resolve()
        != (ROOT / str(capability_identity["path"])).resolve()
        or sha256_file(args.capability_catalog.resolve())
        != capability_identity["sha256"]
    ):
        raise ValueError("formal CC capability catalog differs from the contract")
    profile = architecture_profile_path(
        contract, args.system, "connected_components", ROOT
    )
    if sha256_file(profile) != expected_profile_hash(
        contract, args.system, "connected_components"
    ):
        raise ValueError(f"CC architecture profile differs from contract: {profile}")

    child_system = "spine" if args.system == "spine" else "grasu"
    child_dir = args.out_dir.resolve() / "child"
    command = [
        sys.executable,
        str(ROOT / "scripts/run_sst_connected_components.py"),
        "--architecture",
        child_system,
        "--workload",
        str(Path(str(case.graph["path"]))),
        "--update-workload",
        str(Path(str(case.update["path"]))),
        "--out-dir",
        str(child_dir),
        "--profile",
        str(profile),
        "--capability-catalog",
        str(args.capability_catalog.resolve()),
        "--sst",
        str(args.sst.resolve()),
        "--lib-dir",
        str(args.lib_dir.resolve()),
        "--max-cycles",
        str(args.max_cycles),
        "--no-build",
    ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    wall_seconds = time.monotonic() - start
    (args.out_dir / "child_runner.log").write_text(
        completed.stdout, encoding="utf-8"
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"publication CC child failed with rc={completed.returncode}; "
            f"see {args.out_dir / 'child_runner.log'}"
        )

    result_path = child_dir / "result.json"
    manifest_path = child_dir / "run_manifest.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = {
        "admitted": manifest.get("admitted") is True,
        "profile": manifest.get("profile_sha256") == sha256_file(profile),
        "plugin": manifest.get("sst_plugin_sha256") == sha256_file(plugin),
        "workload": manifest.get("workload_sha256") == case.graph["sha256"],
        "update": manifest.get("update_sha256") == case.update["sha256"],
        "architecture_oracle": result.get("architecture_correctness_mismatches")
        == 0,
        "mathematical_oracle": result.get("mathematical_correctness_mismatches")
        == 0,
        "dram_ledger": manifest.get("checks", {}).get("dram_request_ledger")
        is True,
    }
    problems = [name for name, passed in checks.items() if not passed]
    if problems:
        raise RuntimeError("publication CC parent admission failed: " + ", ".join(problems))

    run = comparison_run(case)
    row = result_row(case, result, manifest, wall_seconds=wall_seconds)
    output = {
        "schema_version": 1,
        "status": "pass",
        "case": asdict(case),
        "logical_views": sorted(set(args.logical_view)),
        "run_contract": run,
        "row": row,
        "final_state": final_state_identity(result),
        "scalar_metrics": scalar_metrics(result),
        "backend_arbitration": result.get("backend_arbitration"),
        "backend_traffic": result.get("backend_traffic"),
        "dram": manifest["dram"],
        "sst_memory_binding": manifest["sst_memory_binding"],
        "physical_hbm_address_regions": manifest.get(
            "physical_hbm_address_regions"
        ),
        "raw_result_path": str(result_path),
        "raw_result_sha256": sha256_file(result_path),
        "plugin_sha256": sha256_file(plugin),
        "host_wall_seconds": wall_seconds,
        "admission": {
            "child_returncode": completed.returncode,
            "parent_checks": checks,
            "architecture_correctness_mismatches": result.get(
                "architecture_correctness_mismatches"
            ),
            "mathematical_correctness_mismatches": result.get(
                "mathematical_correctness_mismatches"
            ),
        },
    }
    output_path = args.out_dir / "case_result.json"
    output_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        f"PASS {case.dataset_id}/connected_components/{case.system}: "
        f"cycles={row['cycles']} wall={wall_seconds:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
