import copy
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_resources.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.r_resources.delivery import package


def fixture():
    ports = []
    for role, ids, channels in (
        ("edge", range(1, 9, 2), range(0, 8, 2)),
        ("source", range(2, 10, 2), range(1, 9, 2)),
        ("apply_read", [100], [30]),
        ("write", range(200, 204), range(1, 9, 2)),
    ):
        for index, (initiator, channel) in enumerate(zip(ids, channels)):
            ports.append({"role": role, "index": index, "initiator": initiator,
                          "channel": channel, "parent_credits": 2, "burst_credits": 16,
                          "data_width_bytes": 64, "request_fifo": 8, "response_fifo": 8,
                          "independent_read_write": False})
    a4 = {"distinct_masters": 13, "registered_ids": sorted(p["initiator"] for p in ports),
          "physical_banks": list(range(8)) + [30], "source_banks": [1, 3, 5, 7],
          "clock_period_fs": 6_666_667, "constructor_only": True}
    k4 = [{"arm": arm, "registered_ids": list(range(600, 609)),
           "clock_period_fs": 6_666_667, "constructor_only": True,
           "declared_parent_credits": 16, "declared_burst_credits": 16,
           "declared_apply_window": 16, "declared_source_banks": [23, 24],
           "declared_primary_bank": 30, "declared_graph_bank_budget": 23,
           "declared_shared_capacity": 32,
           "declared_directory_rows": 1024 if arm == "candidate" else 8,
           "declared_bank_fifo_lines": 256 if arm == "candidate" else 0,
           "regions": [{"shard": p, "name": "row", "channel": p, "allocated_bytes": 64}
                       for p in range(4)]}
          for arm in ("cross_row", "candidate")]
    return ports, a4, k4


def records(values):
    ports, a4, k4 = values
    return "\n".join(tag + " " + json.dumps(row) for tag, rows in (
        ("RESOURCE_PORT", ports), ("RESOURCE_A4", [a4]), ("RESOURCE_K4", k4)) for row in rows)


class ResourceAuditTests(unittest.TestCase):
    def test_master_count_is_not_bank_count_or_performance_admission(self):
        result = analyze(records(fixture()))
        self.assertEqual(result["a4_master_count"], 13)
        self.assertEqual(result["a4_physical_bank_count"], 9)
        self.assertEqual(result["k4_master_count"], 9)
        for flag in ("strict_resource_match_admitted", "performance_admitted",
                     "publication_match_admitted", "hardware_timing_admitted"):
            self.assertIs(result[flag], False)
        self.assertIn("not introspected", result["k4_config_visibility"])

    def test_missing_endpoint_rejected(self):
        ports, a4, k4 = fixture()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            analyze(records((ports[:-1], a4, k4)))

    def test_duplicate_master_rejected(self):
        values = fixture()
        values[0][-1]["initiator"] = values[0][0]["initiator"]
        with self.assertRaisesRegex(ValueError, "accounting"):
            analyze(records(values))

    def test_old_nine_master_claim_rejected(self):
        values = fixture()
        values[1]["distinct_masters"] = 9
        with self.assertRaisesRegex(ValueError, "accounting"):
            analyze(records(values))

    def test_changed_credits_or_fifo_rejected(self):
        for key, value in (("parent_credits", 16), ("request_fifo", 16),
                           ("independent_read_write", True)):
            values = fixture()
            values[0][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "port configuration"):
                analyze(records(values))

    def test_duplicate_k4_arm_rejected(self):
        values = fixture()
        values[2][1] = copy.deepcopy(values[2][0])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            analyze(records(values))

    def test_changed_layout_and_budget_rejected(self):
        for key, value in (("declared_source_banks", [1, 3, 5, 7]),
                           ("registered_ids", list(range(600, 608))),
                           ("declared_directory_rows", 8)):
            values = fixture()
            values[2][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analyze(records(values))

    def test_missing_shard_or_out_of_budget_region_rejected(self):
        for regions in ([{"shard": 0, "channel": 0, "allocated_bytes": 64}],
                        [{"shard": p, "channel": 23, "allocated_bytes": 64} for p in range(4)]):
            values = fixture()
            values[2][0]["regions"] = regions
            with self.subTest(regions=regions), self.assertRaisesRegex(ValueError, "placement"):
                analyze(records(values))

    def test_clock_and_event_boundary_rejected(self):
        for key, value in (("clock_period_fs", 5_000_000), ("constructor_only", False)):
            values = fixture()
            values[1][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "clock/boundary"):
                analyze(records(values))

    def test_undeclared_observation_rejected(self):
        with self.assertRaisesRegex(ValueError, "undeclared"):
            analyze(records(fixture()) + "\nPERFORMANCE_PASS {}")


class ResourceCapsuleTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1] / (
        "docs/experiments/comparisons/grasu_regraph_stage_validation/"
        "evaluation_impact/r_resources/evidence")

    def test_committed_files_and_all_raw_members_match_hashes(self):
        index = json.loads((self.root / "index.json").read_text())
        for entry in index["reports"]:
            self.assertEqual(hashlib.sha256((self.root / entry["file"]).read_bytes()).hexdigest(),
                             entry["sha256"])
        with tarfile.open(self.root / "raw_logs.tar.gz") as archive:
            self.assertEqual(set(archive.getnames()), {r["member"] for r in index["raw_members"]})
            for entry in index["raw_members"]:
                payload = archive.extractfile(entry["member"]).read()
                self.assertEqual(len(payload), entry["bytes"])
                self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])
            observed = analyze(archive.extractfile("audit.stdout.txt").read().decode())
        self.assertEqual(observed, index["analysis"])
        self.assertIs(index["production_baseline_admitted"], False)
        self.assertIs(index["new_spine_comparison_executed"], False)
        self.assertIs(index["core_or_sst_numerical_code_changed"], False)

    def test_frozen_sources_agree_with_report_without_machine_local_paths(self):
        report = json.loads((self.root / "report.json").read_text())
        self.assertIs(report["pins_unchanged"], True)
        original_root = Path(report["steps"][0]["cwd"])
        with tarfile.open(self.root / "sources.tar.gz") as archive:
            for member in archive.getmembers():
                self.assertTrue(member.isfile())
                matches = [r for r in report["pins"] if Path(r["path"]) == original_root / member.name]
                self.assertEqual(len(matches), 1, member.name)
                payload = archive.extractfile(member).read()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), matches[0]["sha256"])
        self.assertEqual(report["analysis"], json.loads((self.root / "index.json").read_text())["analysis"])
        self.assertEqual(len(report["steps"]), 5)
        self.assertTrue(all(not s["exit_code"] and not s["timed_out"] for s in report["steps"]))

    def test_running_or_failed_report_cannot_be_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            for status in ("RUNNING", "FAILED_RETAINED"):
                (run / "results.json").write_text(json.dumps({"status": status}))
                with self.subTest(status=status), self.assertRaisesRegex(ValueError, "completed"):
                    package(run, run / "package")
            self.assertFalse((run / "package").exists())

    def test_changed_source_identity_cannot_be_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            source = run / "source.cpp"
            source.write_text("changed")
            (run / "results.json").write_text(json.dumps({
                "status": "RESOURCE_ACCOUNTING_VERIFIED_NOT_PERFORMANCE_ADMISSION",
                "pins_unchanged": True, "pins": [{"path": str(source), "sha256": "old"}]}))
            with self.assertRaisesRegex(ValueError, "identity changed"):
                package(run, run / "package")
            self.assertFalse((run / "package").exists())


if __name__ == "__main__":
    unittest.main()
