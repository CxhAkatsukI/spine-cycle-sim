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
DEFAULT_REAL_ROWS = [
    ROOT
    / "docs"
    / "evidence"
    / "candidate10_hls_v3_real_small_batches_20260727"
    / "analysis"
    / "system_rows.csv",
    ROOT
    / "docs"
    / "evidence"
    / "candidate10_grasu_temporal_full_pr_small_batches_20260727"
    / "system_rows_enriched.csv",
    ROOT
    / "docs"
    / "evidence"
    / "candidate10_grasu_temporal_three_algorithms_insert_u8_20260727"
    / "system_rows.csv",
]
DEFAULT_DENSE_ROWS = (
    ROOT
    / "docs"
    / "evidence"
    / "candidate10_grasu_temporal_real_dense_full_pr_20260727"
    / "system_rows_enriched.csv"
)
DEFAULT_LARGE_ROWS = (
    ROOT
    / "docs"
    / "evidence"
    / "candidate10_hls_v3_large_runtime_idle_optimized_20260727"
    / "system_rows.csv"
)
DEFAULT_MEMORY_ROWS = [
    ROOT
    / "docs"
    / "evidence"
    / "real_memory_traffic_locality_20260726"
    / "memory_system_rows.csv",
    ROOT
    / "docs"
    / "evidence"
    / "candidate10_grasu_temporal_full_pr_small_batches_20260727"
    / "system_rows_enriched.csv",
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _values(rows: Iterable[dict[str, str]], key: str) -> set[str]:
    return {row[key] for row in rows if row.get(key, "") != ""}


def _integers(rows: Iterable[dict[str, str]], key: str) -> set[int]:
    return {int(row[key]) for row in rows if row.get(key, "") != ""}


def _batch(row: dict[str, str]) -> int | None:
    value = row.get("batch_size") or row.get("user_mutations")
    return int(value) if value not in (None, "") else None


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


def _correct_pair_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault((row["run_id"], row.get("algorithm", "")), []).append(row)
    result: list[dict[str, str]] = []
    for paired in grouped.values():
        if {row["system"] for row in paired} != {"spine", "grasu_regraph"}:
            continue
        if any(int(row.get("correctness_mismatches", "0")) != 0 for row in paired):
            continue
        result.append(paired[0])
    return result


def _has_cross_product(
    rows: Iterable[dict[str, str]], dimensions: dict[str, set[object]]
) -> bool:
    required: set[tuple[object, ...]] = {()}
    keys = list(dimensions)
    for key in keys:
        required = {
            prefix + (value,) for prefix in required for value in dimensions[key]
        }
    observed = {
        tuple(_batch(row) if key == "batch" else row.get(key, "") for key in keys)
        for row in rows
    }
    return required <= observed


def _has_fields(rows: Iterable[dict[str, str]], fields: set[str]) -> bool:
    rows = list(rows)
    return bool(rows) and all(fields <= set(row) for row in rows)


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
    real_batches = {batch for row in real_rows if (batch := _batch(row)) is not None}
    real_pairs, bad_real_runs = _paired_runs(real_rows)
    dense_pairs, bad_dense_runs = _paired_runs(dense_rows)
    large_pairs, bad_large_runs = _paired_runs(large_rows)
    memory_pairs, bad_memory_runs = _paired_runs(memory_rows)
    paper_datasets = real_datasets & reference_ids
    correct_pairs = _correct_pair_rows(real_rows)
    correct_paper_pairs = [
        row for row in correct_pairs if row.get("dataset_id") in paper_datasets
    ]

    gates = contract["required_gates"]
    assert isinstance(gates, dict)
    correctness = gates["correctness"]
    e2e = gates["end_to_end_small_batch"]
    update = gates["update_throughput"]
    dense = gates["dense_batch"]
    memory = gates["memory"]
    assert all(isinstance(item, dict) for item in (correctness, e2e, update, dense, memory))

    required_algorithms = set(correctness["algorithms"])
    required_scenarios = set(correctness["update_scenarios"])
    required_small_batches = set(e2e["batch_sizes"])
    required_update_batches = set(update["batch_sizes"])
    required_update_scenarios = set(update["update_scenarios"])
    controller_rows = [
        row for row in memory_rows if row.get("dataset_id") in paper_datasets
    ]
    controller_partial_fields = {
        "backend_requests",
        "backend_bytes",
        "dram_reads",
        "dram_writes",
        "dram_read_row_hits",
        "dram_activates",
        "dram_precharges",
        "dram_average_read_latency",
    }
    complete_memory_fields = controller_partial_fields | {
        "backend_nominal_64b_bytes",
        "axis_push_stalls",
        "axi_issue_stalls",
        "hbm_queue_stalls",
    }

    statuses = {
        "existing_real_rows_are_correct": bad_real_runs == 0 and real_pairs > 0,
        "paper_reference_dataset_breadth": len(paper_datasets)
        >= int(correctness["minimum_paper_reference_datasets"]),
        "paper_reference_three_algorithm_matrix": _has_cross_product(
            correct_paper_pairs,
            {
                "dataset_id": set(paper_datasets),
                "algorithm": required_algorithms,
            },
        ),
        "paper_reference_differential_scenarios": _has_cross_product(
            correct_paper_pairs,
            {
                "dataset_id": set(paper_datasets),
                "scenario": required_scenarios,
            },
        ),
        "paper_reference_small_batch_matrix": _has_cross_product(
            correct_paper_pairs,
            {
                "dataset_id": set(paper_datasets),
                "algorithm": required_algorithms,
                "batch": required_small_batches,
            },
        ),
        "paper_reference_update_matrix": _has_cross_product(
            correct_paper_pairs,
            {
                "dataset_id": set(paper_datasets),
                "scenario": {"insert", "delete"},
                "batch": required_update_batches,
            },
        )
        and _has_cross_product(
            correct_paper_pairs,
            {
                "dataset_id": set(paper_datasets),
                "scenario": required_update_scenarios - {"insert", "delete"},
                "batch": required_update_batches - {1},
            },
        ),
        "real_dense_coverage": len(_values(dense_rows, "dataset_id"))
        >= int(dense["minimum_real_datasets"])
        and all(row.get("dataset_kind") != "synthetic" for row in dense_rows),
        "controller_memory_partial_coverage": len(
            {row.get("dataset_id") for row in controller_rows}
        )
        >= int(memory["minimum_paper_reference_datasets"])
        and _has_fields(controller_rows, controller_partial_fields),
        "complete_memory_metric_set": _has_fields(
            controller_rows, complete_memory_fields
        ),
    }
    required_statuses = {
        key: value
        for key, value in statuses.items()
        if key != "controller_memory_partial_coverage"
    }
    statuses["publication_real_matrix_complete"] = all(required_statuses.values())

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
            "correct_paper_pairs": len(correct_paper_pairs),
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
        writer = csv.DictWriter(
            stream, fieldnames=("gate", "passed"), lineterminator="\n"
        )
        writer.writeheader()
        for gate, passed in gates.items():
            writer.writerow({"gate": gate, "passed": str(bool(passed)).lower()})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--real-rows", type=Path, action="append")
    parser.add_argument("--dense-rows", type=Path, default=DEFAULT_DENSE_ROWS)
    parser.add_argument("--large-rows", type=Path, default=DEFAULT_LARGE_ROWS)
    parser.add_argument("--memory-rows", type=Path, action="append")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    report = audit(
        contract,
        [
            row
            for path in (args.real_rows or DEFAULT_REAL_ROWS)
            for row in _read_csv(path)
        ],
        _read_csv(args.dense_rows),
        _read_csv(args.large_rows),
        [
            row
            for path in (args.memory_rows or DEFAULT_MEMORY_ROWS)
            for row in _read_csv(path)
        ],
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
