import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.delivery import package, verify
from tests import test_grasu_cache_probe as probe_tests


class CacheProbeDeliveryTests(unittest.TestCase):
    def fixture(self, root):
        attempt = root / "attempt"
        source = attempt / "source"
        source.mkdir(parents=True)
        pin = source / "probe.cpp"
        pin.write_text("frozen probe\n")
        arm = attempt / "original"
        probe_tests.CacheProbeTests().fixture(arm, clock="3.65")
        script = arm / "run.tcl"
        script.write_text("csynth_design\n")
        report = {"status": "ISOLATED_BANK_RTL_PASS_WITH_SEPARATE_CLOCK_GATES",
                  "source": [{"path": str(pin), "sha256": sha256_file(pin)}],
                  "declared_arms": ["original"],
                  "arms": [{"arm": "original", "script_sha256": sha256_file(script),
                            "analysis": analyze(arm)}],
                  "hardware_timing_admitted": False, "production_baseline_admitted": False,
                  "publication_match_admitted": False}
        (attempt / "results.json").write_text(json.dumps(report))
        return attempt, report

    def test_archive_rechecks_raw_scope_and_does_not_promote_g(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, _ = self.fixture(root)
            index = package(root / "evidence", [attempt])
            self.assertEqual(verify(root / "evidence"), index)
            self.assertFalse(index["production_baseline_admitted"])
            self.assertFalse(index["new_spine_comparison_executed"])
            archive = root / "evidence" / index["attempts"][0]["archive"]
            with archive.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "archive identity"):
                verify(root / "evidence")

    def test_running_missing_arms_or_promoted_claim_rejected(self):
        for change in ({"status": "RUNNING"}, {"status": "WAITING_FOR_MEMORY"},
                       {"status": "UNKNOWN"}, {"declared_arms": ["original", "missing"]},
                       {"hardware_timing_admitted": True}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                attempt, report = self.fixture(root)
                report.update(change)
                (attempt / "results.json").write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    package(root / "evidence", [attempt])

    def test_frozen_sources_scripts_and_raw_reports_cannot_change(self):
        for relative in ("source/probe.cpp", "original/run.tcl",
                         "original/project/solution/sim/report/cache_bank_probe_cosim.rpt"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                attempt, _ = self.fixture(root)
                with (attempt / relative).open("a") as stream:
                    stream.write("changed\n")
                with self.assertRaises(ValueError):
                    package(root / "evidence", [attempt])

    def test_committed_checkpoint_keeps_component_and_baseline_claims_separate(self):
        folder = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/cache_probe/evidence")
        index = verify(folder)
        self.assertEqual(index["status"], "CACHE_PROBE_CHECKPOINT_NOT_G_ADMISSION")
        for field in ("hardware_timing_admitted", "production_baseline_admitted",
                      "publication_match_admitted", "new_spine_comparison_executed"):
            self.assertIs(index[field], False)
        attempts = {row["attempt"]: row for row in index["attempts"]}
        bank = attempts["g-cache-bank-v4"]
        self.assertEqual([row["arm"] for row in bank["arms"]],
                         ["original", "lane_wiring", "registered_wiring"])
        self.assertEqual([row["target_5ns_met"] for row in bank["arms"]],
                         [True, False, True])
        full = attempts["g-cache-full-comparison-v1"]
        self.assertEqual(full["status"], "FAILED_RETAINED")
        self.assertEqual(full["arms"][0]["state_control_calls"], 6)
        self.assertIn("error", full["arms"][1])
        waiting = attempts["g-cache-full-comparison-v2"]
        self.assertEqual(waiting["status"], "FAILED_RETAINED")
        self.assertEqual([row["arm"] for row in waiting["arms"]],
                         ["original_full", "registered_full"])
        for row in waiting["arms"]:
            self.assertIn("no tool launched", row["error"])


if __name__ == "__main__":
    unittest.main()
