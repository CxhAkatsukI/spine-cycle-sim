import tempfile
from pathlib import Path
import unittest

from scripts.analyze_current_fpga_components import (
    memory_ledger_row,
    parse_key_value_line,
    prefixed_records,
    spine_structural_work_row,
    unique_prefixed_record,
)


class CurrentFPGAComponentEvidenceTests(unittest.TestCase):
    def test_parse_key_value_timing_line(self):
        parsed = parse_key_value_line(
            "SPINE_HW_TIMING algorithm=weighted_sssp reader_ms=1.25 iterations=2",
            "SPINE_HW_TIMING",
        )
        self.assertEqual(parsed["algorithm"], "weighted_sssp")
        self.assertEqual(parsed["reader_ms"], "1.25")

    def test_duplicate_identical_records_are_one_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.log"
            line = "X a=1 b=2\n"
            path.write_text(line + line, encoding="utf-8")
            self.assertEqual(unique_prefixed_record(path, "X"), {"a": "1", "b": "2"})

    def test_conflicting_records_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.log"
            path.write_text("X a=1\nX a=2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "one unique"):
                unique_prefixed_record(path, "X")

    def test_prefixed_records_preserve_iteration_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.log"
            path.write_text(
                "KERNEL_PAIR_RESULT iteration=0 task_count=3 processed_edges=7\n"
                "KERNEL_PAIR_RESULT iteration=1 task_count=1 processed_edges=1\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [int(row["task_count"]) for row in prefixed_records(path, "KERNEL_PAIR_RESULT")],
                [3, 1],
            )

    def test_spine_structural_work_matches_three_hardware_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "result.json"
            result_path.write_text("{}\n", encoding="utf-8")
            logs = []
            for index in range(3):
                path = root / f"run{index}.log"
                path.write_text(
                    "KERNEL_PAIR_RESULT iteration=0 task_count=3 processed_edges=7\n"
                    "KERNEL_PAIR_RESULT iteration=1 task_count=1 processed_edges=1\n",
                    encoding="utf-8",
                )
                logs.append(path)
            row = spine_structural_work_row(
                "weighted_sssp",
                "x",
                "holdout",
                {
                    "rounds": 2,
                    "reader_range_tasks_per_round": [3, 1],
                    "processed_edges_per_round": [7, 1],
                },
                result_path,
                logs,
                [{"iterations": "2"}] * 3,
            )
            self.assertEqual(row["status"], "PASS")

    def test_explicit_spine_cc_ledgers_pass(self):
        result = {
            "backend_requests": 5,
            "backend_traffic": {"combined": {"requests": 5, "bytes": 320}},
            "memory_locality_ledger_match": True,
            "active_edge_execution_ledger_match": True,
            "component_request_ledger_match": True,
            "fifo_ledger_match": True,
            "owner_ledger_closed": True,
        }
        row = memory_ledger_row(
            "spine", "connected_components", "au", "calibration", result, Path(__file__)
        )
        self.assertEqual(row["status"], "PASS")
        self.assertTrue(row["requests_issued_equal_completed"])

    def test_backend_request_mismatch_fails(self):
        result = {
            "backend_requests": 6,
            "backend_traffic": {"combined": {"requests": 5, "bytes": 320}},
            "memory_locality_ledger_match": True,
            "active_edge_execution_ledger_match": True,
            "component_request_ledger_match": True,
            "fifo_ledger_match": True,
            "owner_ledger_closed": True,
        }
        row = memory_ledger_row(
            "spine", "connected_components", "au", "calibration", result, Path(__file__)
        )
        self.assertEqual(row["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
