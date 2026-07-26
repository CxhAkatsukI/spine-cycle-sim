from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.feasibility import (
    FeasibilityError,
    load_normalized_hls_feasibility,
    require_claim_eligibility,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "configs"
    / "contracts"
    / "candidate10_normalized_hls_feasibility_v1.json"
)


class NormalizedHlsFeasibilityTests(unittest.TestCase):
    def test_current_gate_allows_structural_but_blocks_headline(self) -> None:
        result = load_normalized_hls_feasibility(ROOT)
        self.assertTrue(result["spine_matching_hls"])
        self.assertEqual(result["grasu_matching_hls_algorithms"], 0)
        self.assertEqual(result["grasu_required_algorithms"], 3)
        self.assertFalse(result["all_matching_hls"])
        gate = require_claim_eligibility(result, "structural_exploratory")
        self.assertEqual(
            gate["label"],
            "candidate10_derived_normalized_structural_execution_driven",
        )
        with self.assertRaisesRegex(FeasibilityError, "matching whole-system"):
            require_claim_eligibility(
                result, "headline_normalized_performance"
            )

    def test_crosswalk_is_machine_checked_against_profiles(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="ascii"))
        crosswalk = contract["algorithms"]["weighted_sssp"][
            "parameter_crosswalk"
        ]
        lanes = next(
            item
            for item in crosswalk
            if item["field"] == "/parameters/regraph_map_reduce_lanes"
        )
        lanes["normalized_value"] = 8
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(contract), encoding="ascii")
            with self.assertRaisesRegex(FeasibilityError, "crosswalk is stale"):
                load_normalized_hls_feasibility(ROOT, path)

    def test_profile_identity_is_immutable(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="ascii"))
        contract["algorithms"]["full_pagerank"]["normalized_profile"][
            "sha256"
        ] = "0" * 64
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(contract), encoding="ascii")
            with self.assertRaisesRegex(FeasibilityError, "SHA-256 mismatch"):
                load_normalized_hls_feasibility(ROOT, path)

    def test_matching_status_cannot_ignore_remaining_blockers(self) -> None:
        contract = json.loads(CONTRACT.read_text(encoding="ascii"))
        contract["algorithms"]["weighted_sssp"]["matching_hls"] = True
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            path = Path(temporary) / "contract.json"
            path.write_text(json.dumps(contract), encoding="ascii")
            with self.assertRaisesRegex(FeasibilityError, "blockers remain"):
                load_normalized_hls_feasibility(ROOT, path)

    def test_normalized_result_cannot_be_called_fpga_measured(self) -> None:
        result = load_normalized_hls_feasibility(ROOT)
        with self.assertRaisesRegex(FeasibilityError, "fpga_measured_performance"):
            require_claim_eligibility(result, "fpga_measured_performance")


if __name__ == "__main__":
    unittest.main()
