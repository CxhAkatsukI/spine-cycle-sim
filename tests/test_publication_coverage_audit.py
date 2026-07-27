from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_candidate10_publication_coverage.py"
SPEC = importlib.util.spec_from_file_location("publication_coverage_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _row(run_id: str, algorithm: str, system: str, mismatches: int = 0) -> dict[str, str]:
    return {
        "run_id": run_id,
        "algorithm": algorithm,
        "system": system,
        "correctness_mismatches": str(mismatches),
    }


class PublicationCoverageAuditTest(unittest.TestCase):
    def test_paired_runs_keeps_algorithms_separate(self) -> None:
        rows = [
            _row(run_id, algorithm, system)
            for run_id in ("case_a", "case_b")
            for algorithm in ("weighted_sssp", "full_pagerank")
            for system in ("spine", "grasu_regraph")
        ]
        self.assertEqual(MODULE._paired_runs(rows), (4, 0))

    def test_paired_runs_rejects_incomplete_and_counts_bad_pair(self) -> None:
        rows = [
            _row("complete", "full_pagerank", "spine"),
            _row("complete", "full_pagerank", "grasu_regraph", 1),
            _row("incomplete", "full_pagerank", "spine"),
        ]
        self.assertEqual(MODULE._paired_runs(rows), (1, 1))

    def test_cross_product_does_not_combine_disjoint_coverage(self) -> None:
        rows = [
            {"dataset_id": "a", "algorithm": "sssp", "batch_size": "8"},
            {"dataset_id": "b", "algorithm": "pagerank", "batch_size": "8"},
        ]
        self.assertFalse(
            MODULE._has_cross_product(
                rows,
                {
                    "dataset_id": {"a", "b"},
                    "algorithm": {"sssp", "pagerank"},
                },
            )
        )

    def test_cross_product_accepts_complete_grid_with_batch_alias(self) -> None:
        rows = [
            {
                "dataset_id": dataset,
                "algorithm": algorithm,
                "user_mutations": str(batch),
            }
            for dataset in ("a", "b")
            for algorithm in ("sssp", "pagerank")
            for batch in (1, 8)
        ]
        self.assertTrue(
            MODULE._has_cross_product(
                rows,
                {
                    "dataset_id": {"a", "b"},
                    "algorithm": {"sssp", "pagerank"},
                    "batch": {1, 8},
                },
            )
        )
