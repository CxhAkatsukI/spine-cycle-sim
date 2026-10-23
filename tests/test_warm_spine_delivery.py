"""Portable diagnostic evidence keeps negative rows and common-state checks."""

import copy
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.warm_comparison import delivery

EVIDENCE = (Path(__file__).resolve().parents[1] /
    "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/warm_comparison/evidence")


class WarmDeliveryTests(unittest.TestCase):
    def test_committed_capsule_without_machine_local_paths(self):
        index = delivery.verify(EVIDENCE)
        self.assertEqual(len(index["comparisons"]), 4)
        self.assertEqual(len(index["states"]), 36)
        self.assertEqual(len(index["failures"]), 5)
        self.assertLess(index["comparisons"][1]["speedup_gr_over_spine"], 1)
        self.assertGreater(index["comparisons"][2]["speedup_gr_over_spine"], 5)

    def test_missing_matrix_row_is_rejected(self):
        with tarfile.open(EVIDENCE / "evidence.tar.gz") as archive:
            report = json.load(archive.extractfile("results.json"))
            report["rows"].pop()
            with self.assertRaisesRegex(ValueError, "complete matrix"):
                delivery.validate(report, lambda name: archive.extractfile(name).read(), {})

    def test_raw_result_and_full_state_identity_cannot_be_relabelled(self):
        index = json.loads((EVIDENCE / "index.json").read_text())
        with tarfile.open(EVIDENCE / "evidence.tar.gz") as archive:
            report = json.load(archive.extractfile("results.json"))
            changed = copy.deepcopy(report)
            changed["rows"][0]["result"]["cycles"] += 1
            read = lambda name: archive.extractfile(name).read()
            with self.assertRaisesRegex(ValueError, "raw input/result"):
                delivery.validate(changed, read, index["states"])
            changed_states = copy.deepcopy(index["states"])
            changed_states["smoke_lat64_gr_order0/final.u32le"]["bytes"] -= 4
            with self.assertRaisesRegex(ValueError, "complete state"):
                delivery.validate(report, read, changed_states)

    def test_host_inclusive_or_admitted_label_is_rejected(self):
        with tarfile.open(EVIDENCE / "evidence.tar.gz") as archive:
            original = json.load(archive.extractfile("results.json"))
            for key in ("host_time_included", "baseline_admitted"):
                report = copy.deepcopy(original)
                report[key] = True
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "exploratory"):
                    delivery.validate(report, lambda name: archive.extractfile(name).read(), {})


if __name__ == "__main__":
    unittest.main()
