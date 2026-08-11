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


def traffic(requests: int, bytes_accepted: int) -> dict[str, object]:
    reads = {
        "requests": requests,
        "bytes": bytes_accepted,
        "first_requests": requests,
        "first_bytes": bytes_accepted,
        "contiguous_requests": 0,
        "contiguous_bytes": 0,
        "repeated_requests": 0,
        "repeated_bytes": 0,
        "discontinuous_requests": 0,
        "discontinuous_bytes": 0,
    }
    writes = {key: 0 for key in reads}
    return {
        "classification": "per_initiator_and_operation_accepted_backend_request",
        "address_basis": "logical_channel_and_byte_address",
        "reads": reads,
        "writes": writes,
        "combined": dict(reads),
    }


def owner_round_evidence() -> dict[str, object]:
    return {
        "owner_scheduler_enabled": True,
        "owner_round_evidence_count": 1,
        "owner_round_ledger_match": True,
        "owner_hbm_request_ledger_match": True,
        "owner_hbm_byte_ledger_match": True,
        "reader_source_completion_markers_per_round": [1],
        "compute_source_completion_markers_per_round": [1],
        "owner_round_begins_per_round": [1],
        "owner_source_dispatches_per_round": [1],
        "owner_source_completions_per_round": [1],
        "owner_activation_words_per_round": [0],
        "owner_round_finalizes_per_round": [1],
        "owner_hbm_requests_expected_per_round": [24],
        "owner_hbm_requests_generated_per_round": [24],
        "owner_hbm_requests_completed_per_round": [24],
        "owner_hbm_read_requests_per_round": [10],
        "owner_hbm_write_requests_per_round": [14],
        "owner_hbm_read_bytes_per_round": [80],
        "owner_hbm_write_bytes_per_round": [112],
        "owner_round_ledger_match_per_round": [1],
        "owner_hbm_request_ledger_match_per_round": [1],
        "owner_hbm_byte_ledger_match_per_round": [1],
    }


def grasu_fifo_evidence() -> tuple[dict[str, int], dict[str, int]]:
    result = {
        "source_cache_request_fifo_max_occupancy": 1,
        "source_cache_response_fifo_max_occupancy": 2,
        "gather_merger_fifo_max_occupancy": 3,
        "merger_apply_fifo_max_occupancy": 4,
        "apply_wrapper_fifo_max_occupancy": 5,
        "axis_push_stalls": 0,
    }
    profile = {
        "regraph_source_cache_request_fifo_depth": 8,
        "regraph_source_cache_response_fifo_depth": 8,
        "regraph_gather_merger_fifo_depth": 16,
        "regraph_merger_apply_fifo_depth": 16,
        "regraph_apply_wrapper_fifo_depth": 16,
        "regraph_pma_adapter_axis_fifo_depth": 32,
    }
    return result, profile


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

    def test_residual_pagerank_structural_work_includes_range_tasks_and_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "result.json"
            result_path.write_text("{}\n", encoding="utf-8")
            logs = []
            for index in range(3):
                path = root / f"run{index}.log"
                path.write_text(
                    "KERNEL_PAIR_RESULT iteration=0 task_count=27 processed_edges=311\n"
                    "KERNEL_PAIR_RESULT iteration=1 task_count=7 processed_edges=275\n",
                    encoding="utf-8",
                )
                logs.append(path)
            row = spine_structural_work_row(
                "thresholded_residual_pagerank",
                "ask540",
                "holdout",
                {
                    "iterations": 2,
                    "reader_range_tasks_per_iteration": [27, 7],
                    "reader_edges_per_iteration": [311, 275],
                },
                result_path,
                logs,
                [{"iterations": "2"}] * 3,
            )
            self.assertEqual(row["status"], "PASS")

    def test_explicit_spine_cc_ledgers_pass(self):
        result = {
            **owner_round_evidence(),
            "backend_requests": 5,
            "backend_traffic": traffic(5, 320),
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
            **owner_round_evidence(),
            "backend_requests": 6,
            "backend_traffic": traffic(5, 320),
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

    def test_owner_round_formula_is_recomputed(self):
        result = {
            **owner_round_evidence(),
            "backend_requests": 5,
            "backend_traffic": traffic(5, 320),
            "memory_locality_ledger_match": True,
            "active_edge_execution_ledger_match": True,
            "component_request_ledger_match": True,
            "fifo_ledger_match": True,
            "owner_ledger_closed": True,
        }
        result["owner_hbm_requests_generated_per_round"] = [23]
        row = memory_ledger_row(
            "spine", "connected_components", "au", "calibration", result, Path(__file__)
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertFalse(row["checks"]["owner_round_formula_recomputed"])

    def test_grasu_phase_request_and_byte_ledgers_pass(self):
        fifo_result, profile = grasu_fifo_evidence()
        result = {
            **fifo_result,
            "backend_requests": 7,
            "update_backend_requests": 2,
            "compute_backend_requests": 5,
            "expected_backend_requests": 7,
            "backend_traffic": traffic(7, 448),
            "update_backend_traffic": traffic(2, 128),
            "compute_backend_traffic": traffic(5, 320),
            "memory_locality_ledger_match": True,
            "active_edge_execution_ledger_match": True,
            "pipeline_busy_cycles": 1,
        }
        row = memory_ledger_row(
            "grasu_regraph",
            "weighted_sssp",
            "au",
            "calibration",
            result,
            Path(__file__),
            profile,
        )
        self.assertEqual(row["status"], "PASS")
        self.assertTrue(
            row["checks"]["update_compute_traffic_decomposition_closes"]
        )

    def test_grasu_phase_byte_nonclosure_fails(self):
        fifo_result, profile = grasu_fifo_evidence()
        result = {
            **fifo_result,
            "backend_requests": 7,
            "update_backend_requests": 2,
            "compute_backend_requests": 5,
            "expected_backend_requests": 7,
            "backend_traffic": traffic(7, 449),
            "update_backend_traffic": traffic(2, 128),
            "compute_backend_traffic": traffic(5, 320),
            "memory_locality_ledger_match": True,
            "active_edge_execution_ledger_match": True,
            "pipeline_busy_cycles": 1,
        }
        row = memory_ledger_row(
            "grasu_regraph",
            "weighted_sssp",
            "au",
            "calibration",
            result,
            Path(__file__),
            profile,
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertFalse(
            row["checks"]["update_compute_traffic_decomposition_closes"]
        )

    def test_grasu_fifo_occupancy_above_profile_depth_fails(self):
        fifo_result, profile = grasu_fifo_evidence()
        fifo_result["gather_merger_fifo_max_occupancy"] = 17
        result = {
            **fifo_result,
            "backend_requests": 7,
            "update_backend_requests": 2,
            "compute_backend_requests": 5,
            "expected_backend_requests": 7,
            "backend_traffic": traffic(7, 448),
            "update_backend_traffic": traffic(2, 128),
            "compute_backend_traffic": traffic(5, 320),
            "memory_locality_ledger_match": True,
            "active_edge_execution_ledger_match": True,
        }
        row = memory_ledger_row(
            "grasu_regraph",
            "weighted_sssp",
            "au",
            "calibration",
            result,
            Path(__file__),
            profile,
        )
        self.assertEqual(row["status"], "FAIL")
        self.assertFalse(
            row["checks"]["observable_fifo_occupancies_within_frozen_depths"]
        )


if __name__ == "__main__":
    unittest.main()
