import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding import rtl_review


class SearchBindingReviewTests(unittest.TestCase):
    def fixture(self, root):
        attempt = root / "attempt"
        (attempt / "attempt").mkdir(parents=True)
        script = attempt / "attempt/run.tcl"
        script.write_text("frozen script")
        execution = {"exit_code": 0, "timed_out": False}
        (attempt / "attempt/execution.resources.json").write_text(json.dumps(execution))
        original_analysis = dict.fromkeys(rtl_review.STABLE, False)
        original_analysis.update(csim_pass=True, rtl_pass=True, top_clock_ns=3.65,
                                 target_5ns_met=True, artifacts=[], errors={"abi": "parser failure"})
        original = {"status": "FAILED_RETAINED", "analysis": original_analysis,
                    "source": [], "basis": [], "runner_source": [], "execution": execution,
                    "script": {"path": str(script), "sha256": sha256_file(script)}}
        report = attempt / "results.json"
        report.write_text(json.dumps(original))
        observation = {**original_analysis, "errors": {}, "abi_pass": True}
        return attempt, observation

    def test_review_keeps_original_failure_and_reuses_only_same_rtl(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, observation = self.fixture(root)
            digest = sha256_file(attempt / "results.json")
            with patch.object(rtl_review, "analyze", return_value=observation):
                result = rtl_review.review(root / "review", attempt)
            self.assertEqual(result["status"], "WRAPPER_RTL_ABI_PASS_TARGET_MET_REQUIRES_INTEGRATION")
            self.assertEqual(result["original_status"], "FAILED_RETAINED")
            self.assertEqual(sha256_file(attempt / "results.json"), digest)
            self.assertFalse(result["new_hardware_execution"])
            self.assertFalse(result["production_baseline_admitted"])
            self.assertTrue(result["runner_source"])

    def test_changed_clock_is_not_hidden_as_an_abi_fix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, observation = self.fixture(root)
            observation["top_clock_ns"] = 2.5
            with patch.object(rtl_review, "analyze", return_value=observation), \
                    self.assertRaisesRegex(ValueError, "non-ABI"):
                rtl_review.review(root / "review", attempt)
            self.assertEqual(json.loads((root / "review/results.json").read_text())["status"],
                             "FAILED_RETAINED")

    def test_mutated_frozen_source_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, _ = self.fixture(root)
            (attempt / "attempt/run.tcl").write_text("changed script")
            with self.assertRaisesRegex(ValueError, "source changed"):
                rtl_review.review(root / "review", attempt)
            self.assertFalse((root / "review").exists())

    def test_timeout_is_not_reinterpreted_as_a_parser_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            attempt, _ = self.fixture(root)
            path = attempt / "results.json"
            record = json.loads(path.read_text())
            record["execution"]["timed_out"] = True
            path.write_text(json.dumps(record))
            (attempt / "attempt/execution.resources.json").write_text(json.dumps(record["execution"]))
            with self.assertRaisesRegex(ValueError, "successful unchanged"):
                rtl_review.review(root / "review", attempt)
            self.assertFalse((root / "review").exists())
