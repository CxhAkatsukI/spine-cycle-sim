#!/usr/bin/env python3
"""Audit whether committed Candidate10 evidence covers the publication claims."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT
    / "configs"
    / "experiments"
    / "candidate10_publication_real_coverage_v1.json"
)
DEFAULT_REAL_ROWS = (
    ROOT
    / "docs"
    / "evidence"
    / "candidate10_hls_v3_real_small_batches_20260727"
    / "analysis"
    / "system_rows.csv"
)
DEFAULT_DENSE_ROWS = (
    ROOT
    / "docs"
    / "evidence"
    / "candidate10_hls_v3_dense_full_pagerank_20260727"
    / "timing"
    / "system_rows.csv"
)
DEFAULT_LARGE_ROWS = (
    ROOT
    / "docs"
    / "evidence"
    / "candidate10_hls_v3_large_runtime_idle_optimized_20260727"
    / "system_rows.csv"
)
DEFAULT_MEMORY_ROWS = (
    ROOT
    / "docs"
    / "evidence"
    / "real_memory_traffic_locality_20260726"
    / "memory_system_rows.csv"
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _values(rows: Iterable[dict[str, str]], key: str) -> set[str]:
    return {row[key] for row in rows if row.get(key, "") != ""}


def _integers(rows: Iterable[dict[str, str]], key: str) -> set[int]:
    return {int(row[key]) for row in rows if row.get(key, "") != ""}


def _paired_runs(rows: Iterable[dict[str, str]]) -> tuple[int, int]:
    systems_by_run: dict[tuple[str, str], set[str]] = {}
    bad_runs: set[tuple[str, str]] = set()
    for row in rows:
        run_key = (row["run_id"], row.get("algorithm", ""))
        systems_by_run.setdefault(run_key, set()).add(row["system"])
        if int(row.get("correctness_mismatches", "0")) != 0:
            bad_runs.add(run_key)
    pairs = sum(
        systems == {"spine", "grasu_regraph"}
        for systems in systems_by_run.values()
    )
    return pairs, len(bad_runs)


def audit(
    contract: dict[str, object],
    real_rows: list[dict[str, str]],
    dense_rows: list[dict[str, str]],
    large_rows: list[dict[str, str]],
    memory_rows: list[dict[str, str]],
) -> dict[str, object]:
    reference = contract["reference_datasets"]
    assert isinstance(reference, dict)
    reference_ids = set(reference["grasu_temporal"]) | set(
        reference["dynamic_acts_real"]
    )
    real_datasets = _values(real_rows, "dataset_id")
    real_algorithms = _values(real_rows, "algorithm")
    real_scenarios = _values(real_rows, "scenario")
    real_batches = _integers(real_rows, "user_mutations")
    real_pairs, bad_real_runs = _paired_runs(real_rows)
    dense_pairs, bad_dense_runs = _paired_runs(dense_rows)
    large_pairs, bad_large_runs = _paired_runs(large_rows)
    memory_pairs, bad_memory_runs = _paired_runs(memory_rows)
    paper_datasets = real_datasets & reference_ids

    gates = contract["required_gates"]
    assert isinstance(gates, dict)
    correctness = gates["correctness"]
    e2e = gates["end_to_end_small_batch"]
    update = gates["update_throughput"]
    dense = gates["dense_batch"]
    memory = gates["memory"]
    assert all(isinstance(item, dict) for item in (correctness, e2e, update, dense, memory))

    statuses = {
        "existing_real_rows_are_correct": bad_real_runs == 0 and real_pairs > 0,
        "paper_reference_dataset_breadth": len(paper_datasets)
        >= int(correctness["minimum_paper_reference_datasets"]),
        "three_algorithm_real_coverage": set(correctness["algorithms"])
        <= real_algorithms,
        "differential_scenario_breadth": set(correctness["update_scenarios"])
        <= real_scenarios,
        "small_batch_size_sweep": set(e2e["batch_sizes"]) <= real_batches,
        "update_batch_size_sweep": set(update["batch_sizes"]) <= real_batches,
        "real_dense_coverage": len(_values(dense_rows, "dataset_id"))
        >= int(dense["minimum_real_datasets"])
        and all(row.get("dataset_kind") != "synthetic" for row in dense_rows),
        "physical_memory_locality": bool(memory_rows)
        and {"dram_row_hits", "dram_average_read_latency"}
        <= set(memory_rows[0]),
    }
    statuses["publication_real_matrix_complete"] = all(statuses.values())

    return {
        "contract_id": contract["contract_id"],
        "status": "PASS" if statuses["publication_real_matrix_complete"] else "INCOMPLETE",
        "coverage": {
            "real_system_rows": len(real_rows),
            "real_pairs": real_pairs,
            "real_datasets": sorted(real_datasets),
            "paper_reference_datasets": sorted(paper_datasets),
            "real_algorithms": sorted(real_algorithms),
            "real_update_scenarios": sorted(real_scenarios),
            "real_batch_sizes": sorted(real_batches),
            "large_real_pairs": large_pairs,
            "large_real_bad_runs": bad_large_runs,
            "dense_pairs": dense_pairs,
            "dense_bad_runs": bad_dense_runs,
            "memory_pairs": memory_pairs,
            "memory_bad_runs": bad_memory_runs,
        },
        "gates": statuses,
        "interpretation": (
            "Existing evidence is a correct compact pilot, not a complete "
            "paper-reference real-dataset evaluation."
        ),
    }


def _write_gate_csv(path: Path, report: dict[str, object]) -> None:
    gates = report["gates"]
    assert isinstance(gates, dict)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("gate", "passed"))
        writer.writeheader()
        for gate, passed in gates.items():
            writer.writerow({"gate": gate, "passed": str(bool(passed)).lower()})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--real-rows", type=Path, default=DEFAULT_REAL_ROWS)
    parser.add_argument("--dense-rows", type=Path, default=DEFAULT_DENSE_ROWS)
    parser.add_argument("--large-rows", type=Path, default=DEFAULT_LARGE_ROWS)
    parser.add_argument("--memory-rows", type=Path, default=DEFAULT_MEMORY_ROWS)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    report = audit(
        contract,
        _read_csv(args.real_rows),
        _read_csv(args.dense_rows),
        _read_csv(args.large_rows),
        _read_csv(args.memory_rows),
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "coverage.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_gate_csv(args.out_dir / "coverage_gates.csv", report)
    coverage = report["coverage"]
    assert isinstance(coverage, dict)
    print(
        f"{report['status']} publication coverage: "
        f"real_pairs={coverage['real_pairs']} "
        f"paper_datasets={len(coverage['paper_reference_datasets'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
