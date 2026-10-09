from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.publication_match import assess_study


ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / "docs/experiments/comparisons/grasu_regraph_publication_match"


class PublicationValidationDeliveryTests(unittest.TestCase):
    def test_source_contract_and_admission_report_are_consistent(self) -> None:
        path = ROOT / "configs/experiments/grasu_regraph_publication_match_v1.json"
        contract = json.loads(path.read_text())
        report = json.loads((DELIVERY / "publication_audit.json").read_text())
        self.assertEqual(report["contract_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(report["comparisons"], assess_study(contract)["comparisons"])
        self.assertEqual(report["matched_comparisons"], 0)
        self.assertEqual(report["execution_class"], "source_audit_no_new_publication_timing_samples")
        for item in contract["local_evidence"]:
            self.assertEqual(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest(), item["sha256"])

    def test_published_CC_alias_is_explicitly_rejected(self) -> None:
        report = json.loads((DELIVERY / "publication_audit.json").read_text())
        row = next(row for row in report["comparisons"] if row["id"] == "Reject_ReGraph_CC_name_alias")
        self.assertIn("algorithm", row["mismatches"])
        self.assertIsNone(row["absolute_rate_error_pct"])

    def test_all_packaged_raw_artifact_hashes_match(self) -> None:
        report = json.loads((DELIVERY / "smoke_report.json").read_text())
        for item in report["artifacts"]:
            with self.subTest(path=item["path"]):
                self.assertEqual(hashlib.sha256((DELIVERY / item["path"]).read_bytes()).hexdigest(), item["sha256"])
        for item in report["source_files"]:
            with self.subTest(source=item["path"]):
                self.assertEqual(hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest(), item["sha256"])

    def test_refactor_equivalence_does_not_upgrade_failed_correctness(self) -> None:
        report = json.loads((DELIVERY / "smoke_report.json").read_text())
        self.assertEqual(report["refactor_status"], "ALL_RESULT_FIELDS_EQUIVALENT")
        for row in report["cases"]:
            case_dir = DELIVERY / "smoke" / row["case"]
            before = json.loads((case_dir / "before.result.json").read_text())
            after = json.loads((case_dir / "after.result.json").read_text())
            self.assertEqual(before, after)
            self.assertEqual(after["success"], row["admission"] == "ACCEPTED")
        campaign = json.loads((DELIVERY / "smoke/campaign_state.json").read_text())
        self.assertEqual({job["status"] for job in campaign["jobs"]}, {"pass", "fail"})

    def test_three_round_diagnostic_is_not_two_round_hardware_calibration(self) -> None:
        report = json.loads((DELIVERY / "smoke_report.json").read_text())
        self.assertEqual(report["publication_timing_match"], "NOT_TESTED_BY_THIS_SMOKE")
        diagnostic = report["three_round_diagnostic"]
        self.assertEqual(diagnostic["correctness_mismatches"], 0)
        self.assertEqual(diagnostic["claim"], "correctness_only_not_compared_with_two_round_hardware_log")


if __name__ == "__main__":
    unittest.main()
