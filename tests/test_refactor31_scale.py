from __future__ import annotations

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from spine_cycle_sim.calibration.refactor31_scale import (
    load_refactor31_rmat_runs,
    summarize_refactor31_rmat_runs,
    validate_semantic_comparison,
)


FIELDS = [
    "graph", "graph_edges", "cohort", "state_class", "update_edges",
    "trial", "warmup", "processed_edges", "replay_payloads",
    "dispatch_status", "dispatch_cursor_mismatches", "ack_status",
    "task_error", "maintenance_ms", "reader_ms", "compute_ms",
    "convergence_ms", "e2e_ms", "errors",
]


def row(*, warmup: int = 0, errors: int = 0) -> dict[str, object]:
    return {
        "graph": "raw_rmat24_9", "graph_edges": 150994944,
        "cohort": "historical", "state_class": "pristine",
        "update_edges": 1, "trial": 1, "warmup": warmup,
        "processed_edges": 2, "replay_payloads": 2,
        "dispatch_status": 0, "dispatch_cursor_mismatches": 0,
        "ack_status": 0, "task_error": 0, "maintenance_ms": 1.0,
        "reader_ms": 2.0, "compute_ms": 2.1, "convergence_ms": 2.2,
        "e2e_ms": 3.3, "errors": errors,
    }


class Refactor31ScaleTests(unittest.TestCase):
    def write_rows(self, path: Path, rows: list[dict[str, object]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_loader_admits_closed_hardware_row(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.csv"
            self.write_rows(path, [row()])
            record = load_refactor31_rmat_runs(path)[0]
        self.assertTrue(record.admitted)

    def test_loader_keeps_failed_row_but_does_not_admit_it(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.csv"
            self.write_rows(path, [row(errors=1)])
            record = load_refactor31_rmat_runs(path)[0]
        self.assertFalse(record.admitted)

    def test_semantic_comparison_requires_equal_hashes_and_empty_mismatch(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            hashes = root / "hashes.csv"
            hashes.write_text(
                "key,baseline_sha256,candidate_sha256,status\n"
                "case,abc,abc,PASS\n", encoding="utf-8"
            )
            mismatches = root / "mismatches.csv"
            mismatches.write_text("key,field,baseline,candidate\n", encoding="utf-8")
            self.assertEqual(validate_semantic_comparison(hashes, mismatches), 1)

    def test_semantic_comparison_rejects_mismatch(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            hashes = root / "hashes.csv"
            hashes.write_text(
                "key,baseline_sha256,candidate_sha256,status\n"
                "case,abc,def,FAIL\n", encoding="utf-8"
            )
            mismatches = root / "mismatches.csv"
            mismatches.write_text("key,field,baseline,candidate\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "semantic hash mismatch"):
                validate_semantic_comparison(hashes, mismatches)

    def test_summary_exposes_repeat_and_ledger_gates(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "runs.csv"
            rows = [row(warmup=1), row(warmup=1)] + [row() for _ in range(40)]
            self.write_rows(path, rows)
            summary = summarize_refactor31_rmat_runs(
                load_refactor31_rmat_runs(path)
            )[0]
        self.assertEqual(summary["repeat_gate"], 1)
        self.assertEqual(summary["semantic_ledger_gate"], 1)
        self.assertEqual(summary["measured_rows"], 40)


if __name__ == "__main__":
    unittest.main()
