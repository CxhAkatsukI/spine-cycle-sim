import copy
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.composition import banked_analysis as analysis
from spine_cycle_sim.experiments.evaluation_impact.composition.banked_delivery import deliver
from spine_cycle_sim.experiments.evaluation_impact.composition.analysis import FIXTURES
from spine_cycle_sim.experiments.evaluation_impact.common_g.finite_search.preparation import matrix
from spine_cycle_sim.experiments.evaluation_impact.common_g.finite_search.study import settings

DELIVERY = Path(__file__).resolve().parents[1] / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/composition/banked/evidence")


def observations():
    return [(tag, {"vertices": v, "cache_segments": c, "empty": empty, "reverse": reverse,
                   "g_cycles": 0 if empty else (80 if tag.startswith("BANKED") else 100),
                   "r_cycles": 200, "rounds": 5, "r_read_bytes": 256, "r_write_bytes": 128,
                   "physical_handoff_pass": True, "performance_admitted": False})
            for v, c, empty in FIXTURES
            for tag, orders in (("HANDOFF_RESULT", (False,)), ("BANKED_HANDOFF_RESULT", (False, True)))
            for reverse in orders]


def stdout(rows):
    return "\n".join(tag + " " + json.dumps(row) for tag, row in rows)


def replay_report():
    return {"status": "G_FINITE_SEARCH_PREDICTIONS_CHECKED", "errors": [], **settings(),
            "rows": [{"case": case, "latency": latency, "updates": count, "arm": arm,
                      "observation": {"cycles": 100},
                      "state_sha256": "complete-state-hash", "diagnostics": {"credits": 32}}
                     for latency, case, count, arm in matrix()]}


class BankedHandoffAnalysisTests(unittest.TestCase):
    def test_all_arms_are_correctness_not_performance(self):
        result = analysis.analyze(stdout(observations()))
        self.assertEqual(len(result["direct_rows"]), 4)
        self.assertEqual(len(result["finite_rows"]), 8)
        self.assertTrue(result["r_time_work_traffic_exact"])
        self.assertTrue(result["finite_search_sharded_correctness"])
        for flag in ("full_cached_sharded_candidate", "baseline_admitted", "hardware_timing_admitted",
                     "publication_match_admitted", "host_window_measured"):
            self.assertFalse(result[flag])

    def test_incomplete_duplicate_and_undeclared_rejected(self):
        rows = observations()
        for bad in (rows[:-1], rows + [rows[0]], []):
            with self.subTest(count=len(bad)), self.assertRaises(ValueError):
                analysis.analyze(stdout(bad))
        rows[0][1]["vertices"] += 1
        with self.assertRaises(ValueError):
            analysis.analyze(stdout(rows))

    def test_flags_and_real_work_required(self):
        for field, value in (("g_cycles", 0), ("r_cycles", 0), ("rounds", True),
                             ("r_write_bytes", -1), ("empty", 0), ("reverse", 0),
                             ("physical_handoff_pass", False), ("performance_admitted", True)):
            rows = observations()
            rows[0][1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                analysis.analyze(stdout(rows))

    def test_registration_and_r_counts_must_be_exact(self):
        for field in ("g_cycles", "r_cycles", "rounds", "r_read_bytes", "r_write_bytes"):
            rows = observations()
            rows[1][1][field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                analysis.analyze(stdout(rows))
        rows = observations()
        for tag, row in rows:
            if tag == "BANKED_HANDOFF_RESULT":
                row["r_cycles"] += 1
        with self.assertRaises(ValueError):
            analysis.analyze(stdout(rows))

    def test_replay_requires_complete_exact_state_counters_and_diagnostics(self):
        previous = replay_report()
        current = copy.deepcopy(previous)
        self.assertEqual(analysis.replay(current, previous)["exact_replayed_rows"], 228)
        for field, value in (("observation", {"cycles": 101}), ("state_sha256", "changed"),
                             ("diagnostics", {"credits": 64})):
            bad = copy.deepcopy(current)
            bad["rows"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                analysis.replay(bad, previous)
        for victim in ("current", "previous"):
            new, old = copy.deepcopy(current), copy.deepcopy(previous)
            (new if victim == "current" else old)["rows"].pop()
            with self.subTest(victim=victim), self.assertRaises(ValueError):
                analysis.replay(new, old)
        for field, value in (("errors", ["failure"]), ("status", "RUNNING")):
            bad = copy.deepcopy(previous)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                analysis.replay(current if field == "status" else bad, bad if field == "status" else previous)
        name, value = next(iter(settings().items()))
        current[name] = not value if isinstance(value, bool) else "different"
        with self.assertRaises(ValueError):
            analysis.replay(current, previous)


class BankedHandoffDeliveryTests(unittest.TestCase):
    def test_portable_evidence_recomputes_and_preserves_exact_default_sst(self):
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
            checked = analysis.analyze(archive.extractfile("verified/raw/banked-handoff.stdout.txt").read().decode())
            self.assertEqual(checked, report["analysis"])
            for field, value in checked.items():
                self.assertEqual(index[field], value)
            for name in ("sst-memory/summary.json", "sst-native/result.json"):
                old = json.loads(archive.extractfile("previous-sst/" + name).read())
                new = json.loads(archive.extractfile("verified/compatibility/" + name).read())
                self.assertEqual(old, new)
            self.assertIn("verified/compatibility/sources.tar.gz", archive.getnames())
            self.assertIn("pre-edit/freeze.json", archive.getnames())
        self.assertEqual(index["core_tests"], 33)
        self.assertEqual(index["exact_previous_g_rows"], 228)
        self.assertEqual(len(index["steps"]), 12)
        for step in index["steps"]:
            self.assertEqual(step["exit_code"], 0)
            self.assertFalse(step["timed_out"])
            self.assertGreater(step["memory_limit_gib"], 0)
            self.assertLessEqual(step["memory_limit_gib"], 2)
            self.assertGreaterEqual(step["reserve_gib"], 8)

    def test_complete_g_matrix_and_raw_snapshots_preserved(self):
        root = DELIVERY / "g_replay"
        index = json.loads((root / "index.json").read_text())
        current = json.loads((root / "matrix.json").read_text())
        previous = json.loads((root / "previous_finite.json").read_text())
        self.assertEqual(analysis.replay(current, previous)["exact_replayed_rows"], 228)
        self.assertEqual(index["prediction_rows"], 228)
        with tarfile.open(root / "raw_runs.tar.gz") as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(row["member"] for row in index["raw_members"]))
            for row in index["raw_members"]:
                content = archive.extractfile(row["member"]).read()
                self.assertEqual(len(content), row["bytes"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])

    def test_failed_or_changed_evidence_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "report.json"
            path.write_text(json.dumps({"status": "RUNNING"}))
            with self.assertRaises(ValueError):
                deliver(path, root / "output", root, root, root)
            path.write_text(json.dumps({"status": analysis.STATUS, "pins_unchanged": True,
                "legacy_handoff_stdout_exact": True, "default_sst_json_fields_exact": True,
                "core_tests": 33, "exact_previous_g_rows": 228,
                "pins": [{"path": str(path), "sha256": "changed"}]}))
            with self.assertRaises(ValueError):
                deliver(path, root / "output", root, root, root)
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
