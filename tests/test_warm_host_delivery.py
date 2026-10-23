"""The delivered CPU microbenchmark retains samples and its partial boundary."""

import copy
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.warm_comparison import host_analysis, host_delivery

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/warm_comparison"


class WarmHostDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = host_delivery.verify(OWNER / "host_cpu", OWNER / "evidence")
        with tarfile.open(OWNER / "host_cpu/evidence.tar.gz") as archive:
            cls.files = {m.name: archive.extractfile(m).read() for m in archive.getmembers()}
        cls.report = json.loads(cls.files["results.json"])

    def test_complete_measurements_and_successful_pilot_retained(self):
        result = host_analysis.validate(self.report, self.files.__getitem__)
        self.assertEqual(len(self.report["rows"]), 14)
        self.assertEqual(len(self.index["prior_attempts"]), 1)
        self.assertEqual(self.index["prior_attempts"][0]["status"], host_analysis.STATUS)
        self.assertTrue(all(r["full_host_inclusive_speedup"] is None for r in result))
        self.assertFalse(self.index["baseline_admitted"])

    def test_changed_raw_sample_rejected(self):
        files = dict(self.files)
        files["raw/amazon_repeat0.stdout.txt"] = b"HOST_PREPARATION {}\n"
        with self.assertRaisesRegex(ValueError, "samples"):
            host_analysis.validate(self.report, files.__getitem__)

    def test_changed_arithmetic_or_claimed_full_host_time_rejected(self):
        for change in ("arithmetic", "boundary"):
            report = copy.deepcopy(self.report)
            if change == "arithmetic":
                report["comparisons"][0]["full_host_inclusive_speedup"] = 10
            else:
                report["full_host_time_included"] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                host_analysis.validate(report, self.files.__getitem__)

    def test_failed_or_missing_command_record_rejected(self):
        report = copy.deepcopy(self.report)
        report["steps"].pop()
        with self.assertRaises(ValueError):
            host_analysis.validate(report, self.files.__getitem__)
        report = copy.deepcopy(self.report)
        report["steps"][0]["exit_code"] = 1
        with self.assertRaisesRegex(ValueError, "command"):
            host_analysis.validate(report, self.files.__getitem__)


if __name__ == "__main__":
    unittest.main()
