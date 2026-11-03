"""Repair checkpoints must retain failed gates and the actually executed hosts."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import checkpoint
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity, save


class SourceRetentionCheckpointTest(unittest.TestCase):
    def fixture(self, root):
        campaign, analysis, hosts, production, output = [root / name for name in
                                                      ("campaign", "analysis", "hosts", "production", "output")]
        for directory in (campaign, analysis, hosts, production):
            directory.mkdir()
        host = hosts / "r_reference"
        host.write_bytes(b"fixed host")
        log = campaign / "stdout.txt"
        log.write_text("raw measurement\n")
        report = {"status": "BOARD_EXECUTION_PASS_PENDING_ANALYSIS", "pins": {"r_host": identity(host)},
                  "input_pins": {}, "rows": [{"stdout": identity(log)}]}
        save(campaign / "results.json", report)
        save(analysis / "summary.json", {"status": "PERFORMANCE_GATE_FAILED",
                                        "input_reports": [identity(campaign / "results.json")]})
        for name in ("comparison.csv", "repetitions.csv"):
            (analysis / name).write_text("header\n")
        save(hosts / "manifest.json", {"status": "SINGLE_RUN_HOSTS_BUILD_PASS_NOT_BOARD",
                                      "builds": [{"arm": "reference", "binary": identity(host)}]})
        return campaign, analysis, hosts, production, output

    def test_failure_is_packaged_as_failure_not_final_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            with patch.object(checkpoint, "archive"), \
                    patch.object(checkpoint.subprocess, "check_output", return_value="test-commit\n"):
                result = checkpoint.checkpoint(*args)
            self.assertEqual(result["status"], "REPAIR_CHECKPOINT_NOT_FINAL_EVALUATION")
            self.assertEqual(result["analysis_status"], "PERFORMANCE_GATE_FAILED")
            self.assertFalse(result["publication_match"])
            self.assertTrue((args[-1] / "data/comparison.csv").is_file())

    def test_altered_log_rejects_before_creating_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            (args[0] / "stdout.txt").write_text("altered\n")
            with self.assertRaisesRegex(ValueError, "execution input changed"):
                checkpoint.checkpoint(*args)
            self.assertFalse(args[-1].exists())

    def test_mismatched_host_build_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            report = json.loads((args[2] / "manifest.json").read_text())
            report["builds"][0]["binary"]["sha256"] = "different"
            save(args[2] / "manifest.json", report)
            with self.assertRaisesRegex(ValueError, "executed host differs"):
                checkpoint.checkpoint(*args)
            self.assertFalse(args[-1].exists())


if __name__ == "__main__":
    unittest.main()
