import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.composition import cached_analysis as analysis
from spine_cycle_sim.experiments.evaluation_impact.composition import banked_analysis
from spine_cycle_sim.experiments.evaluation_impact.composition.cached_delivery import deliver

DELIVERY = Path(__file__).resolve().parents[1] / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/composition/cached/evidence")


def observations():
    result = []
    for v, cold, empty in analysis.FIXTURES:
        for cached, reverse in ((False, False), (True, False), (True, True)):
            updates = 0 if empty else 8
            ddr = 4 if cold and updates else 0
            pma_bytes = (33554432 if cached and updates else 0) + (ddr if cached else updates) * 64
            result.append({"vertices": v, "high_source": (v - 1) // 65536 * 65536,
                "cold_high_source": cold, "empty": empty, "cached": cached, "reverse": reverse,
                "g_cycles": 0 if empty else (600000 if cached else 200),
                "r_cycles": 1000000, "rounds": 5, "r_read_bytes": 100000000, "r_write_bytes": 2000000,
                "cache_updates": updates - ddr, "ddr_updates": ddr,
                "pma_read_bytes": pma_bytes, "pma_write_bytes": pma_bytes,
                "physical_handoff_pass": True, "performance_admitted": False})
    return result


def stdout(rows):
    return "\n".join("CACHED_HANDOFF_RESULT " + json.dumps(row) for row in rows)


class CachedHandoffAnalysisTests(unittest.TestCase):
    def test_complete_cached_matrix_has_no_performance_admission(self):
        result = analysis.analyze(stdout(observations()))
        self.assertEqual(len(result["rows"]), 12)
        self.assertTrue(result["full_cached_sharded_correctness"])
        self.assertTrue(result["complete_pma_oracle_pass"])
        for field in ("baseline_admitted", "hardware_timing_admitted", "publication_match_admitted",
                      "host_window_measured", "new_spine_comparison_executed"):
            self.assertFalse(result[field])

    def test_incomplete_duplicate_and_undeclared_rejected(self):
        rows = observations()
        for bad in (rows[:-1], [], rows + [rows[0]]):
            with self.assertRaises(ValueError):
                analysis.analyze(stdout(bad))
        rows[0]["vertices"] += 1
        with self.assertRaises(ValueError):
            analysis.analyze(stdout(rows))

    def test_cache_transfer_ddr_high_id_and_flags_cannot_be_omitted(self):
        for field, value in (("high_source", 0), ("pma_read_bytes", 0), ("pma_write_bytes", 0),
                ("cache_updates", 7), ("ddr_updates", 1), ("g_cycles", 0), ("r_cycles", 0),
                ("rounds", True), ("empty", 0), ("cached", 1), ("reverse", 0),
                ("cold_high_source", 0), ("physical_handoff_pass", False), ("performance_admitted", True)):
            rows = observations()
            rows[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                analysis.analyze(stdout(rows))

    def test_r_exact_and_order_exact_required(self):
        for field in analysis.COUNTERS:
            rows = observations()
            rows[1][field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                analysis.analyze(stdout(rows))

    def test_core_target_count_tracks_actual_ctest_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ctest.stdout.txt"
            for count in (33, 34):
                path.write_text(f"100% tests passed, 0 tests failed out of {count}\n")
                self.assertEqual(banked_analysis.core_tests({"steps": [{"label": "ctest", "stdout": str(path),
                    "exit_code": 0, "timed_out": False}]}), count)
            path.write_text("99% tests passed, 1 tests failed out of 34\n")
            with self.assertRaises(ValueError):
                banked_analysis.core_tests({"steps": [{"label": "ctest", "stdout": str(path),
                    "exit_code": 0, "timed_out": False}]})


class CachedHandoffDeliveryTests(unittest.TestCase):
    def test_portable_capsule_recomputes_raw_and_full_regression(self):
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
            checked = analysis.analyze(archive.extractfile("verified/raw/cached-handoff.stdout.txt").read().decode())
            self.assertEqual(checked, report["analysis"])
            for field, value in checked.items():
                self.assertEqual(index[field], value)
            previous = json.loads(archive.extractfile("regression/g_replay/previous_finite.json").read())
            current = json.loads(archive.extractfile("regression/g_replay/matrix.json").read())
            self.assertEqual(banked_analysis.replay(current, previous)["exact_replayed_rows"], 228)
            with tarfile.open(fileobj=io.BytesIO(archive.extractfile("regression/raw.tar.gz").read())) as regression:
                for name in ("sst-memory/summary.json", "sst-native/result.json"):
                    self.assertEqual(json.loads(regression.extractfile("previous-sst/" + name).read()),
                                     json.loads(regression.extractfile("verified/compatibility/" + name).read()))
                for name, current in (("handoff", "compatibility/raw/handoff"),
                                      ("finite-search", "raw/metadata-routing"), ("banked-handoff", "raw/banked-handoff")):
                    self.assertEqual(regression.extractfile("pre-edit/" + name + ".stdout.txt").read(),
                                     regression.extractfile("verified/" + current + ".stdout.txt").read())
        self.assertEqual(index["core_tests"], 34)
        self.assertEqual(len(index["steps"]), 13)
        for step in index["steps"]:
            self.assertEqual(step["exit_code"], 0)
            self.assertFalse(step["timed_out"])
            self.assertLessEqual(step["memory_limit_gib"], 2)
            self.assertGreaterEqual(step["reserve_gib"], 8)

    def test_running_evidence_cannot_be_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "report.json"
            path.write_text(json.dumps({"status": "RUNNING"}))
            with self.assertRaises(ValueError):
                deliver(path, root / "output", root, root, root)
            self.assertFalse((root / "output").exists())


if __name__ == "__main__":
    unittest.main()
