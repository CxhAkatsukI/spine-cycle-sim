#!/usr/bin/env python3
"""Run one correctness-gated formal publication execution."""

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

from spine_cycle_sim.experiments.comparison import (  # noqa: E402
    build_invocation,
    load_system_result,
    result_row,
    validate_system_result,
)
from spine_cycle_sim.experiments.large_graph_campaign import (  # noqa: E402
    load_large_graph_campaign_contract,
)
from spine_cycle_sim.experiments.publication_cases import (  # noqa: E402
    architecture_profile_paths,
    comparison_run,
    load_materialization_manifest,
    select_publication_case,
)
from spine_cycle_sim.experiments.publication_workloads import sha256_file  # noqa: E402


DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_LIB_DIR = Path(
    "/data/tmp/chuxiao/candidate92-capacity-hot-ledger-native-pgo-build-20260729"
)
DEFAULT_CAPABILITY = (
    ROOT / "configs/contracts/grasu_regraph_publication_capabilities_v6.json"
)


def _replace_option(command: tuple[str, ...], option: str, value: str) -> tuple[str, ...]:
    updated = list(command)
    positions = [index for index, argument in enumerate(updated) if argument == option]
    if len(positions) != 1 or positions[0] + 1 >= len(updated):
        raise ValueError(f"child command must contain exactly one {option}")
    updated[positions[0] + 1] = value
    return tuple(updated)


def _final_state_identity(
    result: Mapping[str, Any], algorithm: str | None = None
) -> dict[str, Any]:
    # The Spine dynamic SSSP runner compacts its post-update final vector to
    # this digest.  cold_final_values is the pre-update baseline and must not
    # be admitted as the publication final state.
    if result.get("final_values_sha256"):
        return {
            "field": "final_values",
            "count": int(result["final_values_count"]),
            "sha256": str(result["final_values_sha256"]),
        }
    fields: tuple[str, ...]
    if algorithm == "weighted_sssp":
        fields = ("distances_external", "final_values")
    elif algorithm in {"full_pagerank", "thresholded_residual_pagerank"}:
        fields = ("ranks_external", "ranks", "final_values")
    else:
        fields = (
            "distances_external",
            "ranks_external",
            "labels_external",
            "final_values",
            "ranks",
            "labels",
        )
    for field in fields:
        raw_values = result.get(field)
        if not isinstance(raw_values, list):
            continue
        values = raw_values
        canonical_field = field
        if algorithm == "weighted_sssp":
            values = [
                0xFFFFFFFF if int(value) >= 0x7FFFFFFE else int(value)
                for value in raw_values
            ]
            canonical_field = "distances_external"
        elif algorithm in {"full_pagerank", "thresholded_residual_pagerank"}:
            canonical_field = "ranks_external"
        encoded = json.dumps(values, separators=(",", ":")).encode("ascii")
        return {
            "field": canonical_field,
            "count": len(values),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    raise ValueError("formal result lacks a full final-state vector")


def _scalar_metrics(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in result.items()
        if isinstance(value, (bool, int, float, str)) or value is None
    }


def _publication_system_row(
    row: Mapping[str, Any], formal_system: str
) -> dict[str, Any]:
    labeled = dict(row)
    labeled["model_system"] = row["system"]
    labeled["system"] = formal_system
    return labeled


def _reused_wall_seconds(invocation: Any) -> float:
    for name in ("manifest.json", "summary.json", "result.json"):
        path = invocation.out_dir / name
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in ("sst_host_wall_seconds", "wall_seconds"):
            value = payload.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                return float(value)
    return 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialization-manifest", type=Path, required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument("--algorithm", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--batch-size", type=int, required=True)
    parser.add_argument("--source-cohort", default="default")
    parser.add_argument("--full-pagerank-edge-cap", type=int, default=4_000_000)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIB_DIR)
    parser.add_argument("--capability-catalog", type=Path, default=DEFAULT_CAPABILITY)
    parser.add_argument("--max-cycles", type=int, default=10_000_000_000_000)
    parser.add_argument("--logical-view", action="append", default=[])
    parser.add_argument("--reuse-child", action="store_true")
    args = parser.parse_args()
    if args.algorithm == "connected_components":
        raise ValueError("connected_components uses the dedicated publication CC runner")
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
        algorithm=args.algorithm,
        scenario=args.scenario,
        batch_size=args.batch_size,
        full_pagerank_edge_cap=args.full_pagerank_edge_cap,
        source_cohort=args.source_cohort,
    )
    for artifact in (case.graph, case.update):
        path = Path(str(artifact["path"]))
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise ValueError(f"formal case artifact is missing or changed: {path}")

    plugin = args.lib_dir.resolve() / "libspine_cycle.so"
    expected_plugin = contract["architecture_baselines"]["simulator_baseline"]
    if not plugin.is_file() or sha256_file(plugin) != expected_plugin["plugin_sha256"]:
        raise ValueError("formal SST plugin differs from the frozen simulator baseline")
    capability_identity = contract["architecture_baselines"][
        "grasu_regraph_capability_catalog"
    ]
    if args.system != "spine" and (
        args.capability_catalog.resolve()
        != (ROOT / str(capability_identity["path"])).resolve()
        or sha256_file(args.capability_catalog.resolve())
        != capability_identity["sha256"]
    ):
        raise ValueError("formal capability catalog differs from the contract")
    profiles = architecture_profile_paths(contract, args.system, ROOT)
    expected_profiles = contract["architecture_baselines"][args.system]
    if args.system == "spine":
        expected_hashes = (str(expected_profiles["sha256"]),)
    else:
        expected_hashes = tuple(
            str(expected_profiles["profiles"][algorithm][1])
            for algorithm in (
                "weighted_sssp",
                "full_pagerank",
                "thresholded_residual_pagerank",
            )
        )
    for path, expected_hash in zip(profiles, expected_hashes):
        if sha256_file(path) != expected_hash:
            raise ValueError(f"architecture profile differs from contract: {path}")

    run = comparison_run(case)
    child_system = "spine" if args.system == "spine" else "grasu_regraph"
    child_root = args.out_dir.resolve() / "child"
    invocation = build_invocation(
        ROOT,
        run,
        system=child_system,
        output_root=child_root,
        python=sys.executable,
        sst=args.sst,
        lib_dir=args.lib_dir,
        spine_profile=profiles[0] if args.system == "spine" else architecture_profile_paths(contract, "spine", ROOT)[0],
        grasu_profile_paths=profiles if args.system != "spine" else None,
        grasu_capability_catalog=(
            args.capability_catalog if args.system != "spine" else None
        ),
    )
    invocation = type(invocation)(
        **{
            **invocation.__dict__,
            "command": _replace_option(
                invocation.command, "--max-cycles", str(args.max_cycles)
            ),
        }
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.reuse_child:
        child_returncode = 0
        wall_seconds = _reused_wall_seconds(invocation)
    else:
        start = time.monotonic()
        completed = subprocess.run(
            invocation.command,
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
        child_returncode = completed.returncode
        if child_returncode != 0:
            raise RuntimeError(
                f"publication child failed with rc={child_returncode}; "
                f"see {args.out_dir / 'child_runner.log'}"
            )

    result, dram, binding = load_system_result(invocation)
    problems = validate_system_result(run, invocation, result, dram, binding)
    if problems:
        raise RuntimeError("publication parent admission failed: " + ", ".join(problems))
    row = _publication_system_row(
        result_row(
            run,
            invocation,
            result,
            dram,
            binding,
            wall_seconds=wall_seconds,
        ),
        case.system,
    )
    raw_result_path = invocation.out_dir / (
        "summary.json" if child_system == "spine" else "result.json"
    )
    output = {
        "schema_version": 1,
        "status": "pass",
        "case": asdict(case),
        "logical_views": sorted(set(args.logical_view)),
        "run_contract": run,
        "row": row,
        "final_state": _final_state_identity(result, case.algorithm),
        "scalar_metrics": _scalar_metrics(result),
        "backend_arbitration": result.get("backend_arbitration"),
        "backend_traffic": result.get("backend_traffic"),
        "dram": dram,
        "sst_memory_binding": binding,
        "raw_result_path": str(raw_result_path),
        "raw_result_sha256": sha256_file(raw_result_path),
        "plugin_sha256": sha256_file(plugin),
        "host_wall_seconds": wall_seconds,
        "admission": {
            "child_returncode": child_returncode,
            "reused_child": args.reuse_child,
            "parent_problems": problems,
            "architecture_correctness_mismatches": result.get(
                "architecture_correctness_mismatches"
            ),
            "mathematical_correctness_mismatches": result.get(
                "mathematical_correctness_mismatches"
            ),
        },
    }
    result_path = args.out_dir / "case_result.json"
    result_path.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        f"PASS {case.dataset_id}/{case.algorithm}/{case.system}: "
        f"cycles={row['cycles']} wall={wall_seconds:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
