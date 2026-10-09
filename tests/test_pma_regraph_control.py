"""Independent admission failures for the finite PMA/A4 matched control."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.pma_adapter.analysis import STATUS, analyze, check_matrix, union_length
from spine_cycle_sim.experiments.pma_adapter.schedules import BurstRemarks
from spine_cycle_sim.experiments.pma_adapter.execution import parallel, step_order
from xml.sax import parseString


class PmaRegraphControlTests(unittest.TestCase):
    def fixture(self, directory):
        files = []
        for replica in range(4):
            path = directory / f"final_replica{replica}.u32le"
            path.write_bytes(b"\0" * 64)
            files.append({"path": path.name, "sha256": sha256_file(path), "bytes": 64})
        old = {"files": files, "result": {"cycles": 100, "checked_sum_words": 65536,
            "checked_replica_words": 64, "degree_read_bytes": 262144, "property_write_bytes": 1048576, "edge_read_bytes": 128}}
        facts = {"logical_edges": 1, "physical_edges": 16, "dummy_edges": 15, "row_word_reads": 12,
                 "source_pma_read_bytes": 64, "pma_segment_reads": [1, 0, 0, 0]}
        item = {"source_counts": facts, "layout": {"summary": {"partitions": 1}}}
        row = {"kind": "schedule_informed_finite_PMA_original_A4_iteration", "passed": True,
            "queues_and_requests_conserved": True, "timing_calibrated_to_FPGA": False,
            "cycles": 1000, "iterations": 1, "argument": 0, "clock_mhz": 210, "little": 4, "big": 0,
            "memory_latency": 64, "state_parent_credits": 16, "input_parent_credits": 16, "outstanding_bursts": 16,
            "checked_sum_words": 65536, "checked_replica_words": 64, "logical_edges": 1, "physical_edges": 16,
            "dummy_edges": 15, "row_word_reads": 12, "row_bus_bytes": 768, "pma_bus_bytes": 64,
            "source_read_bytes": 16384, "degree_read_bytes": 262144, "property_write_bytes": 1048576,
            "read_bytes": 279360, "write_bytes": 1048576, "input_requests": 13, "input_acknowledgements": 13,
            "input_output_stalls": 0, "overlapped_task_starts": 1, "contended_channel_cycles": 0,
            "segment_reads": [1, 0, 0, 0], "publication_finishes": [999], "paths": [
                {"kernel": index, "starts": [0], "reader_finishes": [900], "compute_starts": [100],
                 "frontend_finishes": [500], "completions": [900]} for index in range(4)]}
        timing = {"minimum_read_cycles": 71, "segment_issue_interval": 2, "row_decode_cycles": 2,
                  "source_restart_cycles": 1, "output_latency": 1, "segment_capacity": 38}
        row["timing"] = timing.copy()
        return row, {"latency": 64, "state_parents": 16}, item, old, {"max_cycles": 2000, "timing": timing}

    def evaluate(self, directory, values, stderr=""):
        row, *args = values
        return analyze("PMA_R_EXECUTION " + json.dumps(row) + "\n", stderr, directory, *args)

    def test_complete_state_work_and_nonadditive_windows(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = self.evaluate(directory, self.fixture(directory))
            self.assertEqual(result["status"], STATUS)
            self.assertEqual(result["modeled_overhead_pct"], 900)
            self.assertEqual(result["window_unions_not_additive_stage_costs"],
                             {"reader_cycles": 900, "frontend_cycles": 400, "same_path_overlap_cycles": 400})
            self.assertIsNone(result["FPGA_measured_cycles"])

    def test_reject_counts_scope_and_fabricated_calibration(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            values = self.fixture(directory)
            for key, replacement in (("row_bus_bytes", 96), ("input_acknowledgements", 12),
                    ("input_parent_credits", 2), ("timing_calibrated_to_FPGA", True),
                    ("segment_reads", [True, 0, 0, 0]), ("cycles", True), ("logical_edges", 2)):
                damaged = copy.deepcopy(values)
                damaged[0][key] = replacement
                with self.subTest(key=key), self.assertRaises(ValueError):
                    self.evaluate(directory, damaged)

    def test_reject_missing_windows_reordered_paths_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            values = self.fixture(directory)
            for key, replacement in (("paths", []), ("publication_finishes", []), ("segment_reads", [])):
                damaged = copy.deepcopy(values)
                damaged[0][key] = replacement
                with self.subTest(key=key), self.assertRaises(ValueError):
                    self.evaluate(directory, damaged)
            with self.assertRaises(ValueError):
                self.evaluate(directory, values, "UBSan diagnostic")

    def test_reject_changed_full_state_and_impossible_frontend_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            values = self.fixture(directory)
            bad = copy.deepcopy(values)
            bad[0]["paths"][0]["frontend_finishes"] = [2000]
            with self.assertRaises(ValueError):
                self.evaluate(directory, bad)
            (directory / "final_replica3.u32le").write_bytes(b"\1" * 64)
            with self.assertRaises(ValueError):
                self.evaluate(directory, values)

    def test_union_is_not_sum_and_rejects_reversed_interval(self):
        self.assertEqual(union_length([(0, 10), (5, 20), (30, 35)]), 25)
        with self.assertRaises(ValueError):
            union_length([(5, 1)])

    def test_partial_matrix_is_not_admitted_and_reverse_must_match(self):
        cases = [{"id": "boundary", "status": STATUS, "analysis": {"files": [], "result": {"cycles": 10}}},
                 {"id": "boundary_reverse", "status": "TIMEOUT"}]
        self.assertEqual(check_matrix(cases)["unadmitted_cases"], ["boundary_reverse"])
        cases[1].update(status=STATUS, analysis={"files": [], "result": {"cycles": 11}})
        with self.assertRaises(ValueError):
            check_matrix(cases)

    def test_vitis_unbound_prefix_burst_report_is_parsed_structurally(self):
        handler = BurstRemarks()
        parseString('<VitisHLS:BurstInfo><burst VarName="row_offset" LoopName="source_loop" group="PASSED"/></VitisHLS:BurstInfo>', handler)
        self.assertEqual(handler.rows[0]["VarName"], "row_offset")

    def test_contract_preserves_full_matrix_and_explicit_prediction_boundary(self):
        root = Path(__file__).resolve().parents[1]
        contract = json.loads((root / "configs/experiments/pma_regraph_finite_control_v1.json").read_text())
        self.assertEqual(len(contract["cases"]), 8)
        self.assertEqual(contract["input_outstanding_bursts"], contract["input_parent_credits"])
        self.assertIn("RTL_or_FPGA_timing_calibration", contract["not_claimed"])

    def test_parallel_budget_accounts_for_all_workers_and_keeps_all_cases(self):
        contract = {"parallel_processes": 2, "memory_limit_gib": 4, "reserve_gib": 16}
        with patch("spine_cycle_sim.experiments.pma_adapter.execution.available_memory_bytes", return_value=23 * 1024**3):
            with self.assertRaises(RuntimeError):
                list(parallel([("a", 1), ("b", 2)], lambda value: value, contract))
        with patch("spine_cycle_sim.experiments.pma_adapter.execution.available_memory_bytes", return_value=24 * 1024**3):
            self.assertEqual(dict(parallel([("a", 1), ("b", 2)], lambda value: value + 1, contract)), {"a": 2, "b": 3})
        with self.assertRaises(ValueError):
            list(parallel([("a", 1), ("a", 2)], lambda value: value, contract))

    def test_canonical_step_order_includes_each_matched_and_finite_case(self):
        names = step_order({"cases": [{"id": "a"}, {"id": "b"}]}, [{"id": "a", "status": STATUS}])
        self.assertEqual(names[9:15], ["legacy_a", "matched_a", "legacy_b", "matched_b", "pma_a", "pma_b"])
        self.assertEqual(len(set(names)), len(names))


if __name__ == "__main__":
    unittest.main()
