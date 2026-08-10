#!/usr/bin/env python3
"""Validate and summarize GraSU + ReGraph K-pipeline sensitivity runs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ALGORITHMS = {
    "weighted_sssp",
    "full_pagerank",
    "thresholded_residual_pagerank",
}
CONSERVATION_FIELDS = (
    "destination_partitions",
    "partition_passes",
    "backend_requests",
    "compute_backend_requests",
    "compute_row_reads",
    "source_cache_requests",
    "source_cache_lines",
    "gather_rows_emitted",
    "merger_bursts_emitted",
    "apply_input_bursts",
    "hbm_wrapper_input_bursts",
    "compute_live_edges",
    "compute_active_edges",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_run(text: str) -> tuple[str, int, Path]:
    fields = text.split(":", 2)
    if len(fields) != 3:
        raise ValueError("run must use ALGORITHM:K:DIRECTORY")
    algorithm, k_text, directory_text = fields
    if algorithm not in ALGORITHMS:
        raise ValueError(f"unsupported algorithm: {algorithm}")
    k = int(k_text)
    if k not in {1, 2, 4}:
        raise ValueError("K must be one of 1, 2, or 4")
    return algorithm, k, Path(directory_text).resolve()


def load_run(algorithm: str, k: int, directory: Path) -> dict[str, Any]:
    result_path = directory / "result.json"
    manifest_path = directory / "manifest.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if result.get("success") is not True:
        raise ValueError(f"{algorithm} K={k} did not succeed")
    mismatch_fields = (
        "correctness_mismatches",
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
        "update_state_mismatches",
        "degree_state_mismatches",
    )
    for field in mismatch_fields:
        if field in result and result[field] != 0:
            raise ValueError(f"{algorithm} K={k} has nonzero {field}")
    if result.get("compute_pipelines") != k:
        raise ValueError(f"{algorithm} K={k} reports a different pipeline count")
    partitions = int(result.get("destination_partitions", 0))
    if partitions < 2:
        raise ValueError(f"{algorithm} K={k} is not a multi-partition run")
    expected_parallel = min(k, partitions)
    if result.get("max_parallel_partitions") != expected_parallel:
        raise ValueError(
            f"{algorithm} K={k} did not reach parallelism {expected_parallel}"
        )
    if result.get("memory_locality_ledger_match") is not True:
        raise ValueError(f"{algorithm} K={k} memory ledger did not close")
    arbitration = result.get("backend_arbitration", {})
    if not isinstance(arbitration, dict) or arbitration.get("ledger_closed") is not True:
        raise ValueError(f"{algorithm} K={k} arbitration ledger did not close")
    identity = {
        "workload_sha256": manifest.get("workload_sha256"),
        "update_workload_sha256": manifest.get("update_workload_sha256"),
        "sst_plugin_sha256": manifest.get("sst_plugin_sha256"),
    }
    missing_identity = sorted(name for name, value in identity.items() if not value)
    if missing_identity:
        raise ValueError(
            f"{algorithm} K={k} lacks run identity: {', '.join(missing_identity)}"
        )
    conservation = {field: result.get(field) for field in CONSERVATION_FIELDS}
    missing_conservation = sorted(
        name for name, value in conservation.items() if value is None
    )
    if missing_conservation:
        raise ValueError(
            f"{algorithm} K={k} lacks conservation fields: "
            + ", ".join(missing_conservation)
        )
    return {
        "algorithm": algorithm,
        "compute_pipelines": k,
        "directory": str(directory),
        "result_sha256": sha256(result_path),
        "manifest_sha256": sha256(manifest_path),
        "profile": manifest.get("profile"),
        "profile_sha256": manifest.get("profile_sha256"),
        "sst_plugin_sha256": manifest.get("sst_plugin_sha256"),
        "sst_host_wall_seconds": manifest.get("sst_host_wall_seconds"),
        "identity": identity,
        "cycles": int(result["cycles"]),
        "compute_cycles": int(result["compute_cycles"]),
        "update_cycles": int(result["update_cycles"]),
        "max_parallel_partitions": int(result["max_parallel_partitions"]),
        "conservation": conservation,
    }


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[int, dict[str, Any]]] = {}
    for run in runs:
        algorithm = str(run["algorithm"])
        k = int(run["compute_pipelines"])
        if k in grouped.setdefault(algorithm, {}):
            raise ValueError(f"duplicate {algorithm} K={k} run")
        grouped[algorithm][k] = run
    output: dict[str, Any] = {}
    for algorithm, by_k in sorted(grouped.items()):
        if set(by_k) != {1, 2, 4}:
            raise ValueError(f"{algorithm} requires exactly K=1,2,4")
        reference = by_k[1]
        for k in (2, 4):
            if by_k[k].get("identity") != reference.get("identity"):
                raise ValueError(f"{algorithm} K={k} uses different run inputs")
            if by_k[k]["conservation"] != reference["conservation"]:
                raise ValueError(f"{algorithm} K={k} does not conserve work")
            if by_k[k]["cycles"] > by_k[k // 2]["cycles"]:
                raise ValueError(f"{algorithm} cycles increase at K={k}")
        output[algorithm] = {
            "work_conservation": "PASS",
            "correctness": "PASS",
            "runs": {
                str(k): {
                    **by_k[k],
                    "speedup_over_k1": reference["cycles"] / by_k[k]["cycles"],
                }
                for k in (1, 2, 4)
            },
        }
    return {
        "schema_version": 1,
        "claim_class": "execution_driven_projected_scalability_sensitivity",
        "algorithms": output,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        help="ALGORITHM:K:DIRECTORY; repeat for every K point",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runs = [load_run(*parse_run(spec)) for spec in args.run]
    supplied_algorithms = {str(run["algorithm"]) for run in runs}
    if supplied_algorithms != ALGORITHMS:
        missing = sorted(ALGORITHMS - supplied_algorithms)
        extra = sorted(supplied_algorithms - ALGORITHMS)
        raise ValueError(
            f"formal summary requires all three algorithms; missing={missing} "
            f"extra={extra}"
        )
    summary = summarize(runs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"PASS wrote {args.out} for {len(runs)} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
