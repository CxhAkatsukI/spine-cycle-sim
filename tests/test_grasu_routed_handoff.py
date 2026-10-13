import copy
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.composition.analysis import analyze, FIXTURES, REJECTIONS
from spine_cycle_sim.experiments.evaluation_impact.composition.delivery import deliver


DELIVERY = Path(__file__).resolve().parents[1] / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/composition/evidence")


def records():
    rows = [{"vertices": v, "cache_segments": cache, "empty": empty, "reverse": reverse,
             "g_cycles": 0 if empty else 100, "r_cycles": 200, "rounds": 4,
             "r_read_bytes": 256, "r_write_bytes": 128, "physical_handoff_pass": True,
             "performance_admitted": False}
            for v, cache, empty in FIXTURES for reverse in (False, True)]
    rejects = [{"case": name, "rejected": True} for name in sorted(REJECTIONS)]
    return rows, rejects


def stdout(rows, rejects):
    return "\n".join(["HANDOFF_RESULT " + json.dumps(row) for row in rows] +
                     ["HANDOFF_REJECTION " + json.dumps(row) for row in rejects])


class HandoffAnalysisTests(unittest.TestCase):
    def test_complete_matrix_is_correctness_only(self):
        result = analyze(stdout(*records()))
        self.assertEqual(len(result["rows"]), 8)
        self.assertEqual(len(result["rejections"]), 7)
        self.assertTrue(result["physical_handoff_admitted"])
        for flag in ("whole_g_candidate_integrated", "host_window_measured", "baseline_admitted",
                     "hardware_timing_admitted", "publication_match_admitted", "new_spine_comparison_executed"):
            self.assertFalse(result[flag])

    def test_rejects_missing_duplicate_and_wrong_matrix(self):
        rows, rejects = records()
        for bad in (rows[:-1], rows + [rows[0]], []):
            with self.subTest(rows=len(bad)), self.assertRaises(ValueError):
                analyze(stdout(bad, rejects))
        rows[0]["vertices"] = 128
        with self.assertRaises(ValueError):
            analyze(stdout(rows, rejects))

    def test_requires_rejections_and_registration_equivalence(self):
        rows, rejects = records()
        with self.assertRaises(ValueError):
            analyze(stdout(rows, rejects[:-1]))
        rejects[-1] = copy.deepcopy(rejects[0])
        with self.assertRaises(ValueError):
            analyze(stdout(rows, rejects))
        rows, rejects = records()
        rows[0]["r_cycles"] += 1
        with self.assertRaises(ValueError):
            analyze(stdout(rows, rejects))

    def test_rejects_free_work_and_performance_promotion(self):
        for field, value in (("g_cycles", 0), ("r_cycles", 0), ("r_read_bytes", -1),
                             ("rounds", True), ("reverse", 0), ("empty", 0),
                             ("physical_handoff_pass", False), ("performance_admitted", True)):
            rows, rejects = records()
            rows[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                analyze(stdout(rows, rejects))


class HandoffDeliveryTests(unittest.TestCase):
    def test_capsule_recomputes_from_raw_and_retains_failed_build(self):
        index = json.loads((DELIVERY / "index.json").read_text())
        report = json.loads((DELIVERY / "report.json").read_text())
        for row in index["files"]:
            path = DELIVERY / row["file"]
            self.assertEqual(path.stat().st_size, row["bytes"])
            self.assertEqual(sha256_file(path), row["sha256"])
        with tarfile.open(DELIVERY / "raw.tar.gz") as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(row["member"] for row in index["raw_members"]))
            for row in index["raw_members"]:
                content = archive.extractfile(row["member"]).read()
                self.assertEqual(len(content), row["bytes"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])
            analysis = analyze(archive.extractfile("verified/raw/handoff.stdout.txt").read().decode())
            self.assertEqual(report["analysis"], analysis)
            for field, value in analysis.items():
                self.assertEqual(index[field], value)
            failed = archive.extractfile("retained-1/build-run.stderr.txt").read().decode()
            self.assertIn("dangling-reference", failed)
            self.assertIn("verified/build-flags/compile_commands.json", archive.getnames())
        self.assertEqual(index["core_tests"], 32)
        self.assertEqual(len(index["steps"]), 10)
        for row in index["steps"]:
            self.assertEqual(row["exit_code"], 0)
            self.assertFalse(row["timed_out"])
            self.assertGreater(row["memory_limit_gib"], 0)
            self.assertLessEqual(row["memory_limit_gib"], 2)
            self.assertGreaterEqual(row["reserve_gib"], 8)

    def test_capsule_preserves_exact_default_only_sst_scope(self):
        index = json.loads((DELIVERY / "index.json").read_text())
        self.assertTrue(index["default_routed_stdout_exact"])
        self.assertEqual(len(index["sst_exact_default_smokes"]), 2)
        self.assertIn("default-only", index["sst_scope"])
        with tarfile.open(DELIVERY / "raw.tar.gz") as archive:
            for row in index["sst_exact_default_smokes"]:
                old_name = row["file"].replace("sst-memory/", "memory/").replace("sst-native/", "native/")
                old = archive.extractfile("previous-sst/" + old_name).read()
                new = archive.extractfile("verified/" + row["file"]).read()
                self.assertEqual(json.loads(old), json.loads(new))
                self.assertEqual(hashlib.sha256(old).hexdigest(), row["previous_sha256"])
                self.assertEqual(hashlib.sha256(new).hexdigest(), row["current_sha256"])

    def test_delivery_refuses_failed_or_changed_identity_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.json"
            report.write_text(json.dumps({"status": "FAILED_RETAINED"}))
            with self.assertRaises(ValueError):
                deliver(report, root / "out", [], root)
            self.assertFalse((root / "out").exists())
            report.write_text(json.dumps({"status": "RESIDENT_HANDOFF_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION",
                "pins_unchanged": True, "default_routed_stdout_exact": True,
                "pins": [{"path": str(report), "sha256": "wrong"}]}))
            with self.assertRaises(ValueError):
                deliver(report, root / "out", [], root)
            self.assertFalse((root / "out").exists())


if __name__ == "__main__":
    unittest.main()
