"""Readiness must not confuse upstream running/failed rows with FPGA samples."""

import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import correction_matrix


class CorrectionMatrixTests(unittest.TestCase):
    def test_only_pending_measured_rows_are_ready(self):
        pin = dict(path="frozen", sha256="digest", bytes=1)
        upstream = dict(cases=dict(
            AU=dict(status="MEASURED_RESIDENT_PAIR", result=pin),
            SU=dict(status="RUNNING", result=pin),
            WK=dict(status="FAILED_RETAINED", result=pin),
            PK=dict(status="MEASURED_RESIDENT_PAIR", result=pin)))
        self.assertEqual(correction_matrix.ready_cases(upstream, {"AU", "SU", "WK"}), [("AU", pin)])

    def test_no_empty_queue_is_called_measured(self):
        self.assertEqual(correction_matrix.ready_cases(dict(cases={}), {"LJ"}), [])

    def test_zero_round_scope_is_not_called_propagation(self):
        pair = dict(gr_rounds=0, spine_rounds=0)
        admitted = correction_matrix.pair_with_scope(pair, dict(requires_propagation=False))
        self.assertFalse(admitted["positive_propagation_on_both"])
        self.assertTrue(admitted["meets_propagation_screen"])
        required = correction_matrix.pair_with_scope(pair, dict(requires_propagation=True))
        self.assertFalse(required["meets_propagation_screen"])
        self.assertEqual(pair, dict(gr_rounds=0, spine_rounds=0))


if __name__ == "__main__":
    unittest.main()
