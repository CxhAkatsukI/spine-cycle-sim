"""Re-admit the portable A4 control and reject altered raw evidence."""

import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.a4_control.delivery import verify, watchdog
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.a4_control.recheck import recheck

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ("docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/"
                   "adapter_optimization/row_line/a4_control/evidence")
CASE = "warm_update_lat64_reverse0_whole_line"


class PortableEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        with tarfile.open(EVIDENCE / "raw_A4_control.tar.gz", "r:gz") as bundle:
            for member in bundle.getmembers():
                if not member.isfile() or ".." in Path(member.name).parts or Path(member.name).is_absolute():
                    raise ValueError("unsafe test archive")
                path = cls.root / member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(member) as stream:
                    path.write_bytes(stream.read())
        cls.extracted_run = cls.root / "run"

    def reject(self, relative, mutate, pattern):
        path = self.extracted_run / relative
        original = path.read_bytes()
        try:
            path.write_bytes(mutate(original))
            with self.assertRaisesRegex(ValueError, pattern):
                recheck(self.extracted_run)
        finally:
            path.write_bytes(original)

    def test_complete_portable_recheck(self):
        result = verify(EVIDENCE)
        self.assertEqual(len(result["cases"]), 24)
        self.assertTrue(result["admission"]["extracted_harness_exact_replay"])
        self.assertTrue(result["admission"]["all_four_workers_executed"])
        self.assertFalse(result["admission"]["hardware_timing_admitted"])
        self.assertFalse(result["admission"]["strict_resource_match_admitted"])

    def test_complete_state_not_only_counters(self):
        self.reject("states/" + CASE + "/k4_source1.u32le",
                    lambda data: bytes([data[0] ^ 1]) + data[1:], "complete candidate state")

    def test_full_input_identity(self):
        self.reject("inputs/warm_update/sssp_weights.u32le",
                    lambda data: data + b"changed", "complete input")

    def test_executed_source_identity(self):
        self.reject("sources/cpp/tests/routed_regraph/round_execution.hpp",
                    lambda data: data + b"changed", "executed source")

    def test_compiled_binary_identity(self):
        self.reject("build/routed_regraph_row_line_round",
                    lambda data: data + b"changed", "compiled executable")

    def test_directory_traffic_cannot_be_replaced_by_pass_flag(self):
        def mutate(data):
            lines = data.decode().splitlines()
            for index, line in enumerate(lines):
                if line.startswith("REAL_ROUND "):
                    row = json.loads(line.removeprefix("REAL_ROUND "))
                    row["row_reads"] += 1
                    lines[index] = "REAL_ROUND " + json.dumps(row)
            return ("\n".join(lines) + "\n").encode()
        self.reject("raw/" + CASE + ".stdout.txt", mutate, "expected traffic")

    def test_missing_worker_rejected(self):
        def mutate(data):
            lines = data.decode().splitlines()
            index = next(i for i, line in enumerate(lines) if line.startswith("INVOCATION "))
            del lines[index]
            return ("\n".join(lines) + "\n").encode()
        self.reject("raw/" + CASE + ".stdout.txt", mutate, "partition execution")

    def test_raw_budget_and_cleanup_rechecked(self):
        def mutate(data):
            row = json.loads(data)
            row["cleanup_snapshot_error"] = "missing process snapshot"
            return json.dumps(row).encode()
        self.reject("raw/" + CASE + ".resources.json", mutate, "process-tree contract")

    def test_aggregate_watchdog_cannot_report_timeout_as_success(self):
        path = self.root / "watchdog/resources.json"
        original = path.read_bytes()
        try:
            row = json.loads(original)
            row["stop_reason"] = "timeout"
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(ValueError, "watchdog contract"):
                watchdog(self.extracted_run, path)
        finally:
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
