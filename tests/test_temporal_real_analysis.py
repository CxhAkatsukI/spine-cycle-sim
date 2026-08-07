from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.temporal_real_analysis import (
    _differential_scenario_rows,
    _group_summaries,
    _small_batch_expected_runs,
    _small_batch_paper_rows,
    _validate_update_shape,
)


class TemporalRealAnalysisTest(unittest.TestCase):
    def test_update_shape_distinguishes_semantic_and_physical_records(self) -> None:
        for scenario, records, edge_delta in (
            ("insert", 8, 8),
            ("delete", 8, -8),
            ("mixed", 8, 0),
            ("weight_change", 16, 0),
        ):
            _validate_update_shape(
                {
                    "run_id": scenario,
                    "scenario": scenario,
                    "user_mutations": 8,
                    "physical_records": records,
                    "initial_edges": 100,
                    "final_edges": 100 + edge_delta,
                }
            )
        with self.assertRaisesRegex(ValueError, "invalid weight_change"):
            _validate_update_shape(
                {
                    "run_id": "bad",
                    "scenario": "weight_change",
                    "user_mutations": 8,
                    "physical_records": 8,
                    "initial_edges": 100,
                    "final_edges": 100,
                }
            )

    def test_differential_scenario_rows_require_five_correct_pairs(self) -> None:
        systems = []
        pairs = []
        for scenario in ("delete", "insert", "mixed", "weight_change"):
            for index in range(5):
                run_id = f"{scenario}_{index}"
                pairs.append(
                    {
                        "run_id": run_id,
                        "scenario": scenario,
                        "cross_system_ranks_match": True,
                    }
                )
                for system, mups, e2e in (
                    ("spine", 2.0e6, 4.0),
                    ("grasu_regraph", 4.0e6, 2.0),
                ):
                    systems.append(
                        {
                            "run_id": run_id,
                            "scenario": scenario,
                            "system": system,
                            "user_mutations": 8,
                            "physical_records": 16 if scenario == "weight_change" else 8,
                            "user_mutations_per_second_update": mups,
                            "e2e_ms": e2e,
                        }
                    )
        rows = _differential_scenario_rows(systems, pairs)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[-1]["scenario"], "Weight-chg")
        self.assertEqual(rows[-1]["physical_records_per_user_mutation"], 2.0)
        self.assertAlmostEqual(rows[0]["spine_update_speedup"], 0.5)
        self.assertAlmostEqual(rows[0]["spine_e2e_norm"], 2.0)

        with self.assertRaisesRegex(ValueError, "incomplete five-dataset"):
            _differential_scenario_rows(systems, pairs[:-1])
    def test_group_summary_uses_geometric_speedups(self) -> None:
        rows = []
        for dataset, scenario, speedup in (
            ("a", "insert", 0.25),
            ("a", "delete", 1.0),
            ("b", "insert", 4.0),
        ):
            rows.append(
                {
                    "dataset_id": dataset,
                    "scenario": scenario,
                    "spine_e2e_ms": 4.0,
                    "grasu_e2e_ms": 4.0 * speedup,
                    "spine_speedup_over_grasu_e2e": speedup,
                    "spine_speedup_over_grasu_update": speedup,
                    "spine_speedup_over_grasu_compute": speedup,
                    "grasu_to_spine_backend_request_ratio": 2.0,
                    "grasu_to_spine_backend_byte_ratio": 3.0,
                    "spine_dram_row_hit_rate": 0.5,
                    "grasu_dram_row_hit_rate": 0.75,
                    "spine_dram_average_read_latency": 20.0,
                    "grasu_dram_average_read_latency": 30.0,
                }
            )
        summaries = _group_summaries(rows)
        overall = summaries[0]
        self.assertAlmostEqual(overall["spine_speedup_e2e_geomean"], 1.0)
        self.assertEqual(overall["spine_wins"], 1)
        self.assertEqual(len(summaries), 1 + 2 + 2)

    def test_small_batch_expected_runs_respects_missing_mixed_u1(self) -> None:
        manifest = {
            "runs": [
                {"run_id": "i1", "batch_size": 1, "scenario": "insert"},
                {"run_id": "i8", "batch_size": 8, "scenario": "insert"},
                {"run_id": "m8", "batch_size": 8, "scenario": "mixed"},
                {"run_id": "w8", "batch_size": 8, "scenario": "weight_change"},
                {"run_id": "i512", "batch_size": 512, "scenario": "insert"},
            ]
        }
        self.assertEqual(_small_batch_expected_runs(manifest), {"i1", "i8", "m8"})

    def test_small_batch_paper_rows_use_successful_user_throughput(self) -> None:
        systems = []
        pairs = []
        for batch in (1, 8, 64):
            pairs.append({"user_mutations": batch})
            systems.extend(
                [
                    {
                        "user_mutations": batch,
                        "system": "spine",
                        "user_mutations_per_second_update": 2.0e6,
                        "e2e_ms": 4.0,
                    },
                    {
                        "user_mutations": batch,
                        "system": "grasu_regraph",
                        "user_mutations_per_second_update": 4.0e6,
                        "e2e_ms": 2.0,
                    },
                ]
            )
        throughput, e2e = _small_batch_paper_rows(systems, pairs)
        self.assertEqual([row["batch"] for row in throughput], [1, 8, 64])
        self.assertAlmostEqual(throughput[0]["spine_mups"], 2.0)
        self.assertAlmostEqual(throughput[0]["spine_speedup"], 0.5)
        self.assertAlmostEqual(e2e[0]["spine_norm"], 2.0)


if __name__ == "__main__":
    unittest.main()
