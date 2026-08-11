from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.analyze_current_fpga_spine_composed_v4 import expected_pairs, role_for


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT / "configs/contracts/current_fpga_spine_composed_cases_v4.json"
)


class CurrentFPGAV4ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_roles_are_frozen_and_disjoint(self) -> None:
        self.assertEqual(
            self.contract["status"], "frozen_before_holdout_execution"
        )
        for algorithm in ("weighted_sssp", "connected_components"):
            spec = self.contract["algorithms"][algorithm]
            roles = [
                set(spec["calibration"]),
                set(spec["development_validation"]),
                set(spec["holdout"]),
            ]
            self.assertEqual(len(set.union(*roles)), sum(map(len, roles)))

    def test_residual_propagation_holdout_cannot_fit(self) -> None:
        spec = self.contract["algorithms"]["thresholded_residual_pagerank"]
        self.assertEqual(spec["iterative_strategy"], "simulator_scale_only")
        self.assertEqual(spec["iterative_calibration"], ["ask540"])
        self.assertEqual(spec["iterative_holdout"], ["ask904"])
        self.assertTrue(
            set(spec["iterative_calibration"]).isdisjoint(
                spec["iterative_holdout"]
            )
        )

    def test_plugin_and_source_identities_are_pinned(self) -> None:
        self.assertEqual(len(self.contract["simulator_plugin"]["sha256"]), 64)
        self.assertEqual(len(self.contract["simulator_source_revision"]), 40)
        self.assertEqual(len(self.contract["hardware_source_revision"]), 40)
        for spec in self.contract["algorithms"].values():
            profile = ROOT / spec["profile_path"]
            self.assertTrue(profile.is_file())
            self.assertEqual(len(spec["profile_sha256"]), 64)

    def test_expected_matrix_and_roles_are_unambiguous(self) -> None:
        pairs = expected_pairs(self.contract)
        self.assertEqual(len(pairs), 26)
        self.assertEqual(
            role_for(self.contract, "weighted_sssp", "lj"), "holdout"
        )
        self.assertEqual(
            role_for(
                self.contract, "thresholded_residual_pagerank", "ask540"
            ),
            "calibration",
        )
        self.assertEqual(
            role_for(
                self.contract, "thresholded_residual_pagerank", "ask904"
            ),
            "holdout",
        )


if __name__ == "__main__":
    unittest.main()
