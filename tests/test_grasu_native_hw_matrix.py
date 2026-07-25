from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.run_grasu_native_hw_matrix import (
    artifact_errors,
    group_summary,
    load_matrix,
    selected_cases,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs" / "evidence" / "grasu_native_hw_matrix"


class GraSuNativeHardwareMatrixTests(unittest.TestCase):
    def test_frozen_matrix_has_disjoint_calibration_holdout_and_stress(self) -> None:
        matrix = load_matrix()
        calibration = selected_cases(matrix, {"calibration"}, set())
        holdout = selected_cases(matrix, {"holdout"}, set())
        stress = selected_cases(matrix, {"stress"}, set())
        calibration_names = {case["case"] for case in calibration}
        holdout_names = {case["case"] for case in holdout}

        self.assertEqual(len(calibration), 5)
        self.assertEqual(len(holdout), 5)
        self.assertEqual(len(stress), 1)
        self.assertTrue(calibration_names.isdisjoint(holdout_names))
        self.assertEqual(stress[0]["case"], "large_chain_v4096")
        self.assertEqual(
            {case["family"] for case in [*calibration, *holdout]},
            {"chain", "hot-source", "spread", "hot-dest"},
        )

    def test_all_raw_workload_and_hardware_hashes_match(self) -> None:
        self.assertEqual(artifact_errors(load_matrix()), [])

    def test_unknown_case_and_role_are_rejected(self) -> None:
        matrix = load_matrix()
        with self.assertRaises(ValueError):
            selected_cases(matrix, {"future"}, set())
        with self.assertRaises(ValueError):
            selected_cases(matrix, {"holdout"}, {"missing"})

    def test_summary_keeps_calibration_and_holdout_separate(self) -> None:
        rows = []
        for role, error in (("calibration", 10.0), ("holdout", 30.0)):
            row = {"role": role, "structure_matches": True}
            for target in ("update", "conversion", "compute_span", "event_e2e"):
                row[f"{target}_absolute_error_pct"] = error
                row[f"{target}_signed_error_pct"] = -error
            rows.append(row)
        summaries = group_summary(rows)
        event = {
            item["role"]: item
            for item in summaries
            if item["target"] == "event_e2e"
        }
        self.assertEqual(event["calibration"]["median_absolute_error_pct"], 10.0)
        self.assertEqual(event["holdout"]["median_absolute_error_pct"], 30.0)
        self.assertEqual(event["all"]["median_absolute_error_pct"], 20.0)

    def test_committed_default_matrix_evidence_passes_structural_gate(self) -> None:
        manifest = json.loads((EVIDENCE / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "PASS")
        self.assertTrue(manifest["structure_gate_passed"])
        self.assertEqual(manifest["timing_claim"], "unfitted_trend_only_not_cycle_calibrated")
        self.assertEqual(len(manifest["cases"]), 10)
        self.assertEqual({case["status"] for case in manifest["cases"]}, {"PASS"})
        for case in manifest["cases"]:
            name = case["case"]
            result = json.loads(
                (EVIDENCE / "simulation" / f"{name}.result.json").read_text()
            )
            alignment = json.loads(
                (EVIDENCE / "simulation" / f"{name}.alignment.json").read_text()
            )
            self.assertEqual(result["correctness_mismatches"], 0)
            self.assertTrue(result["native_hls_contract_safe"])
            self.assertTrue(alignment["structure_matches"])


if __name__ == "__main__":
    unittest.main()
