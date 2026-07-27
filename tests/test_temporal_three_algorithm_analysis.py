from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.temporal_three_algorithm_analysis import (
    ALGORITHM_LABELS,
    EXPANDED_BATCHES,
    _expanded_paper_tables,
    _paper_tables,
)


class TemporalThreeAlgorithmAnalysisTest(unittest.TestCase):
    def test_expanded_tables_require_three_by_three_by_five(self) -> None:
        pairs = [
            {
                "algorithm": algorithm,
                "batch_size": batch,
                "spine_e2e_ms": 4.0,
                "grasu_e2e_ms": 2.0,
                "cross_system_correct": True,
            }
            for algorithm in ALGORITHM_LABELS
            for batch in EXPANDED_BATCHES
            for _ in range(5)
        ]
        correctness, batches = _expanded_paper_tables(pairs)
        self.assertEqual([row["real_pairs"] for row in correctness], [15, 15, 15])
        self.assertEqual(len(batches), 9)
        self.assertTrue(all(row["spine_speedup"] == 0.5 for row in batches))

        pairs[-1]["cross_system_correct"] = False
        with self.assertRaisesRegex(ValueError, "lacks five correct pairs"):
            _expanded_paper_tables(pairs)
    def test_paper_tables_require_complete_cross_product(self) -> None:
        abbreviations = {f"d{index}": f"D{index}" for index in range(5)}
        pairs = [
            {
                "dataset_id": dataset,
                "algorithm": algorithm,
                "spine_e2e_ms": 2.0,
                "grasu_e2e_ms": 4.0,
                "spine_speedup": 2.0,
                "cross_system_correct": True,
            }
            for dataset in abbreviations
            for algorithm in ALGORITHM_LABELS
        ]
        correctness, algorithms, datasets = _paper_tables(pairs, abbreviations)
        self.assertEqual([row["real_pairs"] for row in correctness], [5, 5, 5])
        self.assertEqual([row["spine_speedup"] for row in algorithms], [2.0] * 3)
        self.assertEqual(len(datasets), 5)

        with self.assertRaisesRegex(ValueError, "lacks five correct pairs"):
            _paper_tables(pairs[:-1], abbreviations)

    def test_paper_tables_fail_on_incorrect_pair(self) -> None:
        abbreviations = {f"d{index}": f"D{index}" for index in range(5)}
        pairs = [
            {
                "dataset_id": dataset,
                "algorithm": algorithm,
                "spine_e2e_ms": 2.0,
                "grasu_e2e_ms": 4.0,
                "spine_speedup": 2.0,
                "cross_system_correct": not (
                    dataset == "d0" and algorithm == "weighted_sssp"
                ),
            }
            for dataset in abbreviations
            for algorithm in ALGORITHM_LABELS
        ]
        with self.assertRaisesRegex(ValueError, "lacks five correct pairs"):
            _paper_tables(pairs, abbreviations)
