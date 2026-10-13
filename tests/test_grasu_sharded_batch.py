"""Reject omitted work and incomplete batches in the prepared G study."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.delivery import package
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.preparation import CASES, matrix

DELIVERY = Path(__file__).resolve().parents[1] / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/sharded_batch/evidence")


def observations():
    rows = []
    for item in matrix():
        case = CASES[item["case"]]
        physical = case["logical_updates"] * 2
        pma = case["updated_shards"] * 2 * 131072 * 64 + case["ddr_updates"] * 64
        value = {**item, **case, "physical_updates": physical,
            "live_edges": case["vertices"] * case["total_shards"],
            "cache_updates": physical - case["ddr_updates"], "row_reads": physical,
            "binary_probes": 0, "pma_read_bytes": pma, "pma_write_bytes": pma,
            "read_bytes": pma + physical * 16, "write_bytes": pma,
            "full_payload_pass": True, "timing_kind": "declared_prediction", "cycles": 100 if physical else 0}
        rows.append({**item, "observation": value, "state_sha256": "a" * 64})
    return rows


class ShardedBatchTests(unittest.TestCase):
    def test_complete_scope_and_empty_not_a_throughput_point(self):
        result = analyze(observations())
        self.assertEqual(result["prediction_rows"], 24)
        self.assertEqual(len(result["comparisons"]), 8)
        empty = [r for r in result["comparisons"] if r["case"] == "empty"]
        self.assertTrue(all(r["runtime_over_original"] is None for r in empty))
        self.assertFalse(result["production_baseline_admitted"])
        self.assertFalse(result["hardware_timing_admitted"])
        self.assertFalse(result["publication_match_admitted"])

    def test_missing_duplicate_and_undeclared_rows_fail(self):
        rows = observations()
        for candidate in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError): analyze(candidate)
        rows[0]["case"] = "unlisted"
        with self.assertRaises(ValueError): analyze(rows)

    def test_cache_traffic_cannot_be_waived(self):
        rows = observations()
        rows[0]["observation"]["pma_read_bytes"] -= 64
        with self.assertRaises(ValueError): analyze(rows)

    def test_state_work_and_identity_mismatch_fail(self):
        for field, value in (("ddr_updates", 4), ("full_payload_pass", False),
                ("physical_updates", 64), ("arm", "candidate-runtime-23"), ("cycles", 0)):
            rows = observations()
            rows[0]["observation"][field] = value
            with self.assertRaises(ValueError): analyze(rows)
        rows = observations()
        rows[0]["state_sha256"] = "b" * 64
        with self.assertRaises(ValueError): analyze(rows)

    def test_timing_mismatch_is_a_reported_result(self):
        rows = deepcopy(observations())
        rows[1]["observation"]["cycles"] = 200
        result = analyze(rows)
        self.assertFalse(result["four_bank_ten_percent_target_met"])
        self.assertTrue(result["full_payload_and_traffic_pass"])
        self.assertFalse(result["production_baseline_admitted"])


class ShardedBatchDeliveryTests(unittest.TestCase):
    def test_portable_raw_capsule_recomputes_complete_matrix(self):
        index = json.loads((DELIVERY / "index.json").read_text())
        report = json.loads((DELIVERY / "matrix.json").read_text())
        for row in index["reports"]:
            path = DELIVERY / row["file"]
            self.assertEqual(path.stat().st_size, row["bytes"])
            self.assertEqual(sha256_file(path), row["sha256"])
        checked = analyze(report["rows"])
        for key, value in checked.items():
            self.assertEqual(index[key], value)
            self.assertEqual(report[key], value)
        self.assertFalse(index["new_spine_comparison_executed"])
        self.assertEqual(report["errors"], [])
        with tarfile.open(DELIVERY / "raw_runs.tar.gz") as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(r["member"] for r in index["raw_members"]))
            for row in index["raw_members"]:
                content = archive.extractfile(row["member"]).read()
                self.assertEqual(len(content), row["bytes"])
                self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])
            contract = json.loads(archive.extractfile("input_contract.json").read())
            self.assertEqual(contract, report["contract"])
            self.assertEqual(contract["matrix"], matrix())
            for row in report["rows"]:
                label = f"lat{row['latency']}_{row['case']}_{row['arm']}"
                raw = archive.extractfile("raw/" + label + ".stdout.txt").read().decode().strip()
                tag, _, body = raw.partition(" ")
                self.assertEqual(tag, "SHARDED_G_RESULT")
                self.assertEqual(json.loads(body), row["observation"])
            for step in report["steps"]:
                self.assertEqual(step["exit_code"], 0)
                self.assertFalse(step["timed_out"])
                self.assertEqual(step["memory_limit_gib"], 2)
                self.assertGreaterEqual(step["reserve_gib"], 8)
                name = Path(step["stdout"]).name.replace(".stdout.txt", ".resources.json")
                self.assertEqual(json.loads(archive.extractfile("raw/" + name).read()), step)
        self.assertEqual(len(report["steps"]), 28)

    def test_incomplete_result_cannot_be_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "results.json"
            report.write_text(json.dumps({"status": "RUNNING"}))
            with self.assertRaises(ValueError):
                package(root / "evidence", report)
            self.assertFalse((root / "evidence").exists())


if __name__ == "__main__":
    unittest.main()
