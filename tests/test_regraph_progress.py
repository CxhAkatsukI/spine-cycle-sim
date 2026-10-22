"""Completion offsets must conserve the frozen rounds, not imply exclusive costs."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import progress


def fixture():
    rounds, invocations = [], []
    for i in range(2):
        start = i * 100
        rounds.append(dict(round=i, start=start, apply_done=start + 90,
            writeback_done=start + 95, status_done=start + 100, end=start + 100, active=1 - i))
        for partition in range(4):
            for adapter in (0, 1):
                invocations.append(dict(round=i, partition=partition, worker=partition, adapter=adapter,
                    start=start, end=start + 80 - adapter * 10 - partition))
    observations = {"result": {"cycles": 200}, "trajectory": [
        {"round": i, "cycles": 100, "active": 1 - i} for i in range(2)]}
    return rounds, invocations, observations, 4


class ProgressTests(unittest.TestCase):
    def test_committed_completion_capsule_retains_reference_and_failed_gate(self):
        evidence = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/r_bank_stream/evidence")
        report = json.loads((evidence / "progress_20261022_v2.json").read_text())
        reference = json.loads((evidence / report["reference"]).read_text())
        self.assertEqual(report["matrix_executions"], 4)
        self.assertTrue(report["reference_observations_and_state_replayed_exactly"])
        for latency, offsets in report["completion_offset_cycles_by_latency"].items():
            self.assertEqual(offsets["end"], reference["cycles_by_latency"][latency]["bank_stream"])
            self.assertEqual(offsets["tail_after_frontends"], offsets["end"] - offsets["compute_last"])
            self.assertLess(offsets["tail_after_frontends"] / offsets["end"], 0.001)
        for claim in ("exclusive_stage_attribution", "retention_gate_passed",
                      "timing_model_changed", "hardware_timing_admitted", "new_spine_comparison_executed"):
            self.assertFalse(report[claim])
        self.assertLess(report["own_peak_bytes"], report["own_hard_limit_bytes"])
        self.assertEqual(report["own_swap_bytes"], 0)

    def test_offsets_are_overlapping_and_tail_is_not_total_compute_cost(self):
        report = progress.analyze(*fixture())
        self.assertEqual(report["completion_offset_cycles"], dict(adapter_last=140, compute_last=160,
            apply_done=180, writeback_done=190, status_done=200, end=200, tail_after_frontends=40))
        self.assertEqual(report["completion_offset_fraction"]["compute_last"], 0.8)
        self.assertEqual(report["worker_completion_offset_cycles"]["3"]["adapter_last"], 134)
        self.assertIn("not exclusive", report["interpretation"])

    def test_missing_duplicate_or_wrong_round_invocations_rejected(self):
        for kind in ("missing", "duplicate", "out_of_range", "non_boolean_adapter"):
            rounds, invocations, observations, partitions = fixture()
            if kind == "missing":
                invocations.pop()
            elif kind == "duplicate":
                invocations[-1] = copy.deepcopy(invocations[0])
            elif kind == "out_of_range":
                invocations[0]["round"] = 2
            else:
                invocations[0]["adapter"] = 2
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "invocation"):
                progress.analyze(rounds, invocations, observations, partitions)

    def test_completion_order_and_frozen_cycles_and_active_are_checked(self):
        for field, value in (("start", 99), ("end", 205), ("active", 4),
                             ("status_done", 189), ("apply_done", 99)):
            rounds, invocations, observations, partitions = fixture()
            rounds[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                progress.analyze(rounds, invocations, observations, partitions)

    def test_wrong_worker_or_window_rejected(self):
        for field, value in (("worker", 1), ("start", 90), ("end", 101)):
            rounds, invocations, observations, partitions = fixture()
            invocations[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "assignment|window"):
                progress.analyze(rounds, invocations, observations, partitions)

    def test_csv_rejects_malformed_schema_noninteger_and_partial_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.csv"
            for text in ("value\n1\n", "round,start\n0,-1\n", "round,start\n0,1.5\n",
                         "round,start\n0\n", "round,start\n0,1,2\n"):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    progress.read(path, ("round", "start"))
            path.write_text("round,start\n0,12\n")
            self.assertEqual(progress.read(path, ("round", "start")), [{"round": 0, "start": 12}])


if __name__ == "__main__":
    unittest.main()
