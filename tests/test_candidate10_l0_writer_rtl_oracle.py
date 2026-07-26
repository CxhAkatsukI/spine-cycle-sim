from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect_candidate10_l0_writer_rtl_oracle.py"
SPEC = importlib.util.spec_from_file_location("candidate10_l0_writer_oracle", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Candidate10L0WriterOracleTest(unittest.TestCase):
    def test_matrix_has_structural_and_backpressure_cases(self) -> None:
        self.assertGreaterEqual(len(MODULE.CASES), 50)
        self.assertTrue(any(case.stall_period for case in MODULE.CASES))
        self.assertEqual({case.pattern for case in MODULE.CASES}, {0, 1, 2, 3, 4})
        for count in (3, 5, 15, 17):
            self.assertTrue(any(
                case.case_id == f"same_source_{count}" for case in MODULE.CASES
            ))

    def test_parse_oracle(self) -> None:
        parsed = MODULE.parse_oracle(
            "noise\nL0_WRITER_RTL inputs=2 cycles=749 result_edges=2\n"
        )
        self.assertEqual(parsed, {"inputs": 2, "cycles": 749, "result_edges": 2})

    def test_parse_requires_one_result(self) -> None:
        with self.assertRaises(RuntimeError):
            MODULE.parse_oracle("no result")

    def test_validate_accepts_consistent_result(self) -> None:
        case = MODULE.OracleCase("unit", 2, 2, 1, 0)
        oracle = {
            "inputs": 2,
            "edges": 2,
            "rows": 1,
            "pattern": 0,
            "source_stride": 1,
            "group_size": 4,
            "stall_period": 0,
            "stall_width": 0,
            "cycles": 749,
            "result_edges": 2,
            "result_rows": 1,
            "result_overflow": 0,
            "result_validation": 0,
            "result_outputs": 2,
            "sorter_ar": 2,
            "sorter_r": 2,
            "sorter_requested_r_beats": 2,
            "graph_requested_w_beats": 10,
            "graph_w": 10,
            "meta_requested_w_beats": 2,
            "meta_w": 2,
            "graph_aw": 7,
            "graph_b": 7,
            "meta_aw": 2,
            "meta_b": 1,
        }
        self.assertEqual(MODULE.validate_oracle(case, oracle), [])

    def test_validate_rejects_wrong_payload_counts(self) -> None:
        case = MODULE.OracleCase("unit", 2, 2, 1, 0)
        failures = MODULE.validate_oracle(case, {})
        self.assertTrue(any("result_edges" in failure for failure in failures))
        self.assertTrue(any("sorter_ar" in failure for failure in failures))

    def test_family_local_contract_violation_is_an_expected_error_path(self) -> None:
        case = MODULE.OracleCase(
            "negative", 4, 2, 2, 3,
            expect_family_local_contract_failure=True,
        )
        oracle = {
            "inputs": 4,
            "edges": 2,
            "rows": 2,
            "pattern": 3,
            "source_stride": 1,
            "group_size": 4,
            "stall_period": 0,
            "stall_width": 0,
            "result_edges": 4,
            "result_rows": 4,
            "result_overflow": 1,
            "result_validation": 1,
            "result_outputs": 4,
            "sorter_ar": 4,
            "sorter_r": 4,
            "sorter_requested_r_beats": 4,
            "graph_requested_w_beats": 12,
            "graph_w": 12,
            "meta_requested_w_beats": 2,
            "meta_w": 2,
            "graph_aw": 9,
            "graph_b": 9,
            "meta_aw": 2,
            "meta_b": 1,
        }
        self.assertEqual(MODULE.validate_oracle(case, oracle), [])

    def test_derived_metrics_keep_protocol_layers_explicit(self) -> None:
        rows = [{
            "case_id": "same_source_16",
            "inputs": 16,
            "cycles": 1085,
            "stall_period": 0,
            "final_source_groups": 16,
            "result_rows": 1,
            "result_pages": 1,
            "sorter_requested_r_beats": 16,
            "graph_requested_w_beats": 24,
            "meta_requested_r_beats": 1,
            "meta_requested_w_beats": 2,
        }, {
            "case_id": "same_source_16_backpressure_5_2",
            "inputs": 16,
            "cycles": 1116,
            "stall_period": 5,
            "final_source_groups": 16,
            "result_rows": 1,
            "result_pages": 1,
            "sorter_requested_r_beats": 16,
            "graph_requested_w_beats": 24,
            "meta_requested_r_beats": 1,
            "meta_requested_w_beats": 2,
        }]
        MODULE.add_derived_metrics(rows)
        self.assertEqual(rows[0]["writer_loop_ii_cycles"], 384)
        self.assertEqual(rows[0]["writer_control_residual_cycles"], 701)
        self.assertEqual(rows[0]["sorter_child_read_bytes"], 256)
        self.assertEqual(rows[0]["graph_child_write_bytes"], 192)
        self.assertEqual(rows[0]["ideal_case_id"], "")
        self.assertEqual(rows[1]["ideal_case_id"], "same_source_16")
        self.assertEqual(rows[1]["backpressure_delta_cycles"], 31)
        self.assertAlmostEqual(rows[1]["backpressure_slowdown"], 1116 / 1085)

    def test_state_dependent_writer_schedule_matches_oracle_boundaries(self) -> None:
        predict = MODULE.writer_rtl_min_cycles
        self.assertEqual(predict(0, 0, 0, 0), 0)
        self.assertEqual(predict(1, 1, 1, 1), 799)
        self.assertEqual(predict(16, 1, 1, 16), 1085)
        self.assertEqual(predict(16, 16, 1, 1), 1156)
        self.assertEqual(predict(17, 17, 1, 1), 1249)
        self.assertEqual(predict(16, 16, 16, 1), 1300)
        self.assertEqual(predict(17, 17, 17, 1), 1462)
        self.assertEqual(predict(8, 4, 1, 2), 962)
        self.assertEqual(predict(8, 4, 4, 2), 893)


if __name__ == "__main__":
    unittest.main()
