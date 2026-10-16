import copy
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline import delivery as shared_delivery
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.native_geometry import analysis, delivery

EVIDENCE = Path(__file__).resolve().parents[1] / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/"
    "hardware_validation/complete_pipeline/native_geometry/evidence")


class DeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index = json.loads((EVIDENCE / "index.json").read_text())
        with tarfile.open(EVIDENCE / index["attempts"][0]["archive"]) as bundle:
            cls.files = {item.name: bundle.extractfile(item).read().decode("utf-8")
                         for item in bundle if item.isfile()}
        cls.report = json.loads(cls.files["results.json"])

    def test_actual_six_rows_replay_without_live_paths(self):
        delivery.recheck(self.report, self.files.__getitem__)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "portable"
            shutil.copytree(EVIDENCE, root)

            def archive_only(path):
                self.assertTrue(Path(path).is_relative_to(root))
                return sha256_file(path)

            with patch.object(shared_delivery, "sha256_file", side_effect=archive_only):
                index = delivery.verify(root)
            self.assertEqual(index["attempts"][0]["status"], analysis.PASS)
            self.assertEqual(len(index["attempts"][0]["rows"]), 6)

    def test_all_functional_rows_remain_source_checks_not_hardware(self):
        self.assertEqual(sum(row["updates"] for row in self.report["rows"]), 80)
        self.assertEqual(self.report["setup"]["executed_operations"], 40)
        self.assertTrue(all(self.report[key] is False for key in analysis.CLAIMS))
        for key in analysis.CLAIMS:
            changed = copy.deepcopy(self.report)
            changed[key] = True
            with self.subTest(key=key), self.assertRaises(ValueError):
                delivery.recheck(changed, self.files.__getitem__)

    def test_rejects_scope_drift_oom_missing_budget_or_changed_rows(self):
        changes = [lambda r: r["rows"][1].update(cold_even=0),
                   lambda r: r["contract"].update(cache_segments_per_half=4),
                   lambda r: r.update(memory_events_after="oom 1\noom_kill 0\noom_group_kill 0\n"),
                   lambda r: r["policy"].update(reserve_gib=0),
                   lambda r: r["admission"].update(admitted=False)]
        for change in changes:
            report = copy.deepcopy(self.report)
            change(report)
            with self.assertRaises(ValueError):
                delivery.recheck(report, self.files.__getitem__)

    def test_rejects_changed_raw_or_resource_record(self):
        for name, value in (("raw/native.stderr.txt", self.files["raw/native.stderr.txt"] + "unknown"),
                            ("raw/compile.resources.json", "{}"), ("raw/compile.stderr.txt", "unexpected note")):
            files = {**self.files, name: value}
            with self.subTest(name=name), self.assertRaises(ValueError):
                delivery.recheck(self.report, files.__getitem__)

    def test_missing_runner_pin_is_not_portable_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "tampered"
            shutil.copytree(EVIDENCE, root)
            index = json.loads((root / "index.json").read_text())
            entry = index["attempts"][0]
            selected = next(key for key, value in entry["pin_members"].items() if value.startswith("runner_snapshot/"))
            del entry["pin_members"][selected]
            (root / "index.json").write_text(json.dumps(index))
            with self.assertRaises(ValueError):
                delivery.verify(root)


if __name__ == "__main__":
    unittest.main()
