"""Portable model evidence must reject changed state, traffic and provenance."""

import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_delivery import verify
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_recheck import recheck_smoke

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ("docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/"
                   "adapter_optimization/row_line/model/evidence")


class RowLineModelDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.evidence_root = Path(cls.temporary.name)
        with tarfile.open(EVIDENCE / "raw_model.tar.gz", "r:gz") as bundle:
            for member in bundle.getmembers():
                if not member.name.startswith(("sst/", "plugin/")):
                    continue
                if not member.isfile() or ".." in Path(member.name).parts or Path(member.name).is_absolute():
                    raise ValueError("unsafe test evidence")
                path = cls.evidence_root / member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as stream:
                    path.write_bytes(stream.read())

    def smoke(self):
        return recheck_smoke(self.evidence_root / "sst", self.evidence_root / "plugin/libspine_cycle.so")

    def reject_mutation(self, relative, mutate, pattern):
        path = self.evidence_root / relative
        original = path.read_bytes()
        try:
            path.write_bytes(mutate(original))
            with self.assertRaisesRegex(ValueError, pattern):
                self.smoke()
        finally:
            path.write_bytes(original)

    def reject_field(self, relative, field, value, pattern):
        def mutate(data):
            payload = json.loads(data)
            payload[field] = value
            return json.dumps(payload).encode()
        self.reject_mutation(relative, mutate, pattern)

    def test_complete_archive_rechecks_without_original_paths(self):
        report = verify(EVIDENCE)
        self.assertEqual(report["core_executables_passed"], 27)
        self.assertEqual(len(report["legacy_cases"]), 5)
        self.assertTrue(all(row["result_hashes"][0] == row["result_hashes"][1]
                            for row in report["legacy_cases"]))
        self.assertFalse(report["hardware_timing_admitted"])
        self.assertFalse(report["original_A4_comparison_complete"])

    def test_model_smoke_independent_traffic_recomputation(self):
        report = self.smoke()
        self.assertEqual([row["arms"]["candidate"]["directory_requests"] for row in report["rows"]], [4, 4])

    def test_complete_state_or_fixture_change_rejected(self):
        for name in ("sst/case1/candidate/result.json.values.txt", "sst/case1/resident.bin"):
            with self.subTest(name=name):
                self.reject_mutation(name, lambda data: data[:-1] + bytes([data[-1] ^ 1]), "differs")

    def test_plugin_and_source_archive_changes_rejected(self):
        for name in ("plugin/libspine_cycle.so", "sst/source.tar.gz"):
            with self.subTest(name=name):
                self.reject_mutation(name, lambda data: data + b"changed", "differs")

    def test_executed_arm_and_watchdog_changes_rejected(self):
        self.reject_field("sst/case1/candidate/run_config.json", "arm", "original", "configuration")
        for key, value in (("exit_code", 1), ("stop_reason", "timeout"), ("reserve_gib", 8),
                           ("minimum_available_bytes", 0), ("cleanup_snapshot_error", "missing")):
            with self.subTest(key=key):
                self.reject_field("sst/case1/candidate/sst.resources.json", key, value, "bounded")

    def test_raw_traffic_and_summary_changes_rejected(self):
        self.reject_field("sst/case1/candidate/result.json", "backend_reads", 0, "traffic conservation")
        self.reject_field("sst/results.json", "hardware_timing_admitted", True, "summary")

    def test_nominal_pass_cannot_hide_failed_correctness(self):
        self.reject_field("sst/case1/candidate/result.json", "success", False, "correctness")


if __name__ == "__main__":
    unittest.main()
