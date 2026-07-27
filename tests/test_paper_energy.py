from __future__ import annotations

import unittest

from spine_cycle_sim.evidence.paper_energy import paper_hbm_energy_rows


def _row(algorithm: str, dataset: str) -> dict[str, object]:
    return {
        "algorithm": algorithm,
        "dataset_id": dataset,
        "spine_dram_energy_pj": 100.0,
        "grasu_dram_energy_pj": 200.0,
        "grasu_to_spine_dram_energy_ratio": 2.0,
        "spine_dram_command_dynamic_energy_pj": 20.0,
        "grasu_dram_command_dynamic_energy_pj": 60.0,
        "grasu_to_spine_dram_command_dynamic_energy_ratio": 3.0,
        "spine_dram_background_refresh_energy_pj": 80.0,
        "grasu_dram_background_refresh_energy_pj": 140.0,
        "partial_energy_ratio_valid_as_total": False,
        "dram_energy_ratio_valid": True,
        "dram_energy_scope": "all_32_hbm_controller_instances",
    }


class PaperEnergyTest(unittest.TestCase):
    def test_requires_and_aggregates_matched_hbm_only(self) -> None:
        rows = [
            _row(algorithm, f"d{index}")
            for algorithm in (
                "weighted_sssp",
                "full_pagerank",
                "thresholded_residual_pagerank",
            )
            for index in range(3)
        ]
        result = paper_hbm_energy_rows(rows)
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(result[0]["grasu_to_spine_total_hbm"], 2.0)
        self.assertAlmostEqual(
            result[0]["grasu_to_spine_command_dynamic"], 3.0
        )

    def test_rejects_partial_energy_as_total(self) -> None:
        rows = [
            _row(algorithm, f"d{index}")
            for algorithm in (
                "weighted_sssp",
                "full_pagerank",
                "thresholded_residual_pagerank",
            )
            for index in range(3)
        ]
        rows[0]["partial_energy_ratio_valid_as_total"] = True
        with self.assertRaisesRegex(ValueError, "claim boundary"):
            paper_hbm_energy_rows(rows)
