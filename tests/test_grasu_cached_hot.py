import copy
import json
from pathlib import Path
import tempfile
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.cached_hot.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.cached_hot.delivery import package
from spine_cycle_sim.experiments.evaluation_impact.common_g.cached_hot.preparation import (
    HOT_TRANSFER_BYTES, PREVIOUS_ARMS, matrix,
)


class CachedHotMatrixTests(unittest.TestCase):
    def fixture(self):
        rows = []
        for latency, name, count, arm in matrix():
            cached = arm in ("original", "cached_hot")
            rows.append({"latency": latency, "case": name, "updates": count, "arm": arm,
                "state_sha256": "a" * 64, "observation": {"arm": arm,
                    "timing_kind": "declared_prediction", "state_pass": True, "cycles": 100,
                    "cache_updates": count, "ddr_updates": 0, "row_reads": count,
                    "binary_probes": count, "read_bytes": count * 24 +
                        (HOT_TRANSFER_BYTES if cached else count * 64),
                    "write_bytes": HOT_TRANSFER_BYTES if cached else count * 64}})
        report = {"rows": rows, "matrix": matrix(), "errors": [],
            "hardware_timing_admitted": False, "publication_match_admitted": False,
            "production_baseline_admitted": False, "reference_cache_timing_admitted": False}
        previous = {"rows": copy.deepcopy([r for r in rows if r["arm"] in PREVIOUS_ARMS])}
        return report, previous

    def test_complete_scope_exact_replay_and_prediction(self):
        report, previous = self.fixture()
        result = analyze(report, previous)
        self.assertEqual(len(report["rows"]), 190)
        self.assertEqual(result["old_checkpoint_exact_rows"], 152)
        self.assertEqual(len(result["comparisons"]), 38)
        self.assertTrue(result["legacy_reference_within_ten_percent_both_directions"])

    def test_empty_cache_transfer_cannot_be_free(self):
        report, previous = self.fixture()
        row = next(r for r in report["rows"] if r["case"] == "empty" and r["arm"] == "cached_hot")
        row["observation"]["write_bytes"] = 0
        with self.assertRaisesRegex(ValueError, "transfer"):
            analyze(report, previous)

    def test_empty_direct_paths_are_not_charged_an_implicit_cache(self):
        report, previous = self.fixture()
        for rows in (report["rows"], previous["rows"]):
            for row in rows:
                if row["case"] == "empty" and row["arm"] not in ("original", "cached_hot"):
                    row["observation"]["cycles"] = 0
        self.assertEqual(analyze(report, previous)["old_checkpoint_exact_rows"], 152)
        for arm in ("original", "cached_hot"):
            bad = copy.deepcopy(report)
            old = copy.deepcopy(previous)
            for rows in (bad["rows"], old["rows"]):
                for row in rows:
                    if row["case"] == "empty" and row["arm"] == arm:
                        row["observation"]["cycles"] = 0
            with self.assertRaisesRegex(ValueError, "zero time"):
                analyze(bad, old)

    def test_missing_duplicate_old_drift_and_failed_rows_rejected(self):
        for fault in ("missing", "duplicate", "scope", "previous", "old", "failure"):
            report, previous = self.fixture()
            if fault == "missing": report["rows"].pop()
            if fault == "duplicate": report["rows"].append(report["rows"][0])
            if fault == "scope": report["matrix"].pop()
            if fault == "previous": previous["rows"].pop()
            if fault == "old": previous["rows"][0]["observation"]["cycles"] += 1
            if fault == "failure": report["errors"].append({"error": "failed"})
            with self.assertRaises(ValueError): analyze(report, previous)

    def test_work_state_traffic_and_promotion_rejected(self):
        for fault in ("work", "state", "traffic", "promotion", "reference", "negative", "free_time"):
            report, previous = self.fixture()
            row = report["rows"][-1]
            if fault == "work": row["observation"]["cache_updates"] += 1
            if fault == "state": row["state_sha256"] = "b" * 64
            if fault == "traffic": row["observation"]["read_bytes"] -= 64
            if fault == "promotion": report["hardware_timing_admitted"] = True
            if fault == "reference": report["reference_cache_timing_admitted"] = True
            if fault == "negative": row["observation"]["cycles"] = -1
            if fault == "free_time": row["observation"]["cycles"] = 0
            with self.assertRaises(ValueError): analyze(report, previous)

    def test_one_large_conflict_failure_is_not_averaged_away(self):
        report, previous = self.fixture()
        row = next(r for r in report["rows"] if r["case"] == "same_key_amortized" and r["arm"] == "cached_hot")
        row["observation"]["cycles"] = 111
        result = analyze(report, previous)
        self.assertFalse(result["legacy_reference_no_more_than_ten_percent_slower"])

    def test_delivery_rechecks_pins_summary_and_complete_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pin = root / "source"
            pin.write_text("fixed source")
            report, previous = self.fixture()
            digest = sha256_file(pin)
            for rows in (report["rows"], previous["rows"]):
                for row in rows:
                    row["state_sha256"] = digest
            for row in report["rows"]:
                state = root / f'lat{row["latency"]}_{row["case"]}_{row["arm"]}.u32le'
                state.write_bytes(pin.read_bytes())
            report.update(analyze(report, previous))
            report.update(status="CACHED_G_PREDICTION_VALIDATED_REFERENCE_TIMING_OPEN",
                          pins=[{"path": str(pin), "sha256": digest}], steps=[])
            stdout, stderr, resources = (root / ("run" + suffix) for suffix in
                (".stdout.txt", ".stderr.txt", ".resources.json"))
            stdout.write_text("complete result")
            stderr.write_text("")
            resources.write_text('{"exit_code": 0}')
            report["steps"] = [{"stdout": str(stdout), "stderr": str(stderr)}]
            current, old = root / "results.json", root / "previous.json"
            old.write_text(json.dumps(previous))
            current.write_text(json.dumps(report))
            result = package(root / "evidence", current, old)
            self.assertEqual(result["prediction_rows"], 190)
            self.assertFalse(result["baseline_admitted"])
            self.assertEqual(len(result["raw_members"]), 3)
            with tarfile.open(root / "evidence/raw_runs.tar.gz") as archive:
                self.assertEqual(archive.getnames(), [stdout.name, stderr.name, resources.name])
                self.assertEqual(archive.extractfile(stdout.name).read(), stdout.read_bytes())
            for fault in ("status", "summary", "pin", "state"):
                bad = copy.deepcopy(report)
                if fault == "status": bad["status"] = "RUNNING"
                if fault == "summary": bad["old_checkpoint_exact_rows"] -= 1
                if fault == "pin": bad["pins"][0]["sha256"] = "0" * 64
                if fault == "state": state.write_text("changed state")
                current.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    package(root / ("rejected-" + fault), current, old)


if __name__ == "__main__":
    unittest.main()
