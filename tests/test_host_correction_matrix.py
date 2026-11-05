"""Readiness must not confuse upstream running/failed rows with FPGA samples."""

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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

    def test_missing_producer_file_is_waiting_not_a_failed_sample(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(correction_matrix.upstream_state(
                Path(temporary) / "not-created.json", {"LJ08"}), ([], {}, None))

    def test_live_producer_failure_is_not_assumed_terminal(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "matrix.json"
            path.write_text(json.dumps(dict(status="RUNNING", cases=dict(
                LJ08=dict(status="FAILED_RETAINED")))))
            self.assertEqual(correction_matrix.upstream_state(path, {"LJ08"}), ([], {}, None))

    def test_terminal_producer_keeps_ready_rows_and_pins_unavailable_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "matrix.json"
            measured = dict(path="result", sha256="digest", bytes=1)
            failed = dict(status="FAILED_RETAINED", result=dict(path="failed-result"))
            path.write_text(json.dumps(dict(status="RETAINED_INCOMPLETE_MATRIX", cases=dict(
                LJ=dict(status="MEASURED_RESIDENT_PAIR", result=measured), LJ08=failed))))
            ready, unavailable, pin = correction_matrix.upstream_state(path, {"LJ", "LJ08", "R19"})
            self.assertEqual(ready, [("LJ", measured)])
            self.assertEqual(set(unavailable), {"LJ08", "R19"})
            self.assertEqual(pin, correction_matrix.identity(path))
            self.assertEqual(unavailable["LJ08"], dict(status="UPSTREAM_UNAVAILABLE_RETAINED",
                upstream_matrix=pin, upstream_status="RETAINED_INCOMPLETE_MATRIX",
                upstream_case=failed))
            self.assertIsNone(unavailable["R19"]["upstream_case"])

    def test_malformed_producer_is_not_silently_waited_on(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "matrix.json"
            path.write_text("{not valid JSON")
            with self.assertRaises(json.JSONDecodeError):
                correction_matrix.upstream_state(path, {"LJ08"})

    def test_terminal_failure_finishes_without_sleep_or_board_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream = root / "upstream.json"
            upstream.write_text(json.dumps(dict(status="RETAINED_INCOMPLETE_MATRIX", cases=dict(
                LJ08=dict(status="FAILED_RETAINED")))))
            args = argparse.Namespace(matrix=upstream, output=root / "output", reuse_pk=None,
                datasets=["LJ08"], wait_seconds=30, child_prefix="unused")
            for name in correction_matrix.INPUTS:
                setattr(args, name, root / name)
                getattr(args, name).write_text(name)
            with patch.object(correction_matrix, "check_memory"), \
                    patch.object(correction_matrix.host_correction, "admit", return_value=[]), \
                    patch.object(correction_matrix.time, "sleep") as sleep, \
                    patch.object(correction_matrix.subprocess, "run") as board:
                report = correction_matrix.run(args)
            sleep.assert_not_called()
            board.assert_not_called()
            self.assertEqual(report["status"], "RETAINED_INCOMPLETE_MATRIX")
            self.assertEqual(report["cases"]["LJ08"]["status"], "UPSTREAM_UNAVAILABLE_RETAINED")
            self.assertIn(correction_matrix.identity(upstream), report["pins"])
            self.assertEqual(json.loads((args.output / "matrix.json").read_text()), report)

    def test_missing_producer_can_appear_as_terminal_failure_during_wait(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upstream = root / "upstream.json"
            args = argparse.Namespace(matrix=upstream, output=root / "output", reuse_pk=None,
                datasets=["LJ08"], wait_seconds=30, child_prefix="unused")
            for name in correction_matrix.INPUTS:
                setattr(args, name, root / name)
                getattr(args, name).write_text(name)

            def publish(seconds):
                self.assertEqual(seconds, 30)
                upstream.write_text(json.dumps(dict(status="FAILED_RETAINED", cases={})))

            with patch.object(correction_matrix, "check_memory"), \
                    patch.object(correction_matrix.host_correction, "admit", return_value=[]), \
                    patch.object(correction_matrix.time, "monotonic", side_effect=[0, 0, 1]), \
                    patch.object(correction_matrix.time, "sleep", side_effect=publish) as sleep, \
                    patch.object(correction_matrix.subprocess, "run") as board:
                report = correction_matrix.run(args)
            sleep.assert_called_once_with(30)
            board.assert_not_called()
            self.assertEqual(report["status"], "RETAINED_INCOMPLETE_MATRIX")
            self.assertEqual(report["cases"]["LJ08"]["status"], "UPSTREAM_UNAVAILABLE_RETAINED")
            self.assertIn(correction_matrix.identity(upstream), report["pins"])

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
