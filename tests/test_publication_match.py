from __future__ import annotations

import copy
import unittest

from spine_cycle_sim.experiments.publication_match import (
    REQUIRED_CONDITIONS, assess_comparison, assess_study,
)


class PublicationMatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = {
            "id": "test_only_not_a_research_result",
            "reference_rate": 100.0, "candidate_rate": 95.0,
            "conditions": {
                name: {"status": "matched", "evidence": "unit-test fixture"}
                for name in REQUIRED_CONDITIONS
            },
        }

    def assess(self, case=None):
        return assess_comparison(self.case if case is None else case, threshold_pct=10)

    def test_admits_error_only_after_all_conditions_match(self) -> None:
        result = self.assess()
        self.assertEqual(result["status"], "WITHIN_THRESHOLD")
        self.assertAlmostEqual(result["absolute_rate_error_pct"], 5)

    def test_threshold_is_relative_to_reference_not_candidate(self) -> None:
        self.case["candidate_rate"] = 110
        self.assertEqual(self.assess()["status"], "WITHIN_THRESHOLD")
        self.case["candidate_rate"] = 111
        self.assertEqual(self.assess()["status"], "OUTSIDE_THRESHOLD")

    def test_a_same_speed_wrong_algorithm_is_not_a_match(self) -> None:
        self.case["candidate_rate"] = 100
        self.case["conditions"]["algorithm"] = {
            "status": "mismatch", "evidence": "closeness vs connected components",
        }
        result = self.assess()
        self.assertEqual(result["status"], "NOT_COMPARABLE_AS_CONFIGURED")
        self.assertIsNone(result["absolute_rate_error_pct"])

    def test_missing_sample_or_unresolved_gate_is_insufficient(self) -> None:
        for field in REQUIRED_CONDITIONS:
            case = copy.deepcopy(self.case)
            case["conditions"][field]["status"] = "unresolved"
            self.assertEqual(self.assess(case)["status"], "INSUFFICIENT_EVIDENCE")
        self.case["candidate_rate"] = None
        self.assertEqual(self.assess()["status"], "INSUFFICIENT_EVIDENCE")

    def test_missing_gate_or_proof_cannot_silently_pass(self) -> None:
        del self.case["conditions"]["boundary"]
        with self.assertRaises(ValueError):
            self.assess()
        self.setUp()
        self.case["conditions"]["clock"]["evidence"] = ""
        with self.assertRaises(ValueError):
            self.assess()

    def test_invalid_rates_are_rejected_not_counted_as_a_mismatch(self) -> None:
        for value in (0, -1, float("nan"), float("inf"), True, "100"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                case = copy.deepcopy(self.case)
                case["candidate_rate"] = value
                self.assess(case)

    def test_duplicate_predeclared_comparisons_are_rejected(self) -> None:
        contract = {"schema_version": 1, "threshold_pct": 10, "comparisons": [self.case] * 2}
        with self.assertRaises(ValueError):
            assess_study(contract)

    def test_no_candidate_is_never_reported_as_a_completed_match(self) -> None:
        self.case["candidate_rate"] = None
        result = assess_study({"schema_version": 1, "threshold_pct": 10, "comparisons": [self.case]})
        self.assertFalse(result["all_comparisons_matched"])
        self.assertEqual(result["matched_comparisons"], 0)


if __name__ == "__main__":
    unittest.main()
