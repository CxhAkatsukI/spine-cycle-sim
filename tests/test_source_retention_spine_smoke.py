"""A partial CC fixture is not a repeated full-performance comparison."""

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    spine_cc_input, spine_smoke,
)

validate = spine_smoke.validate


def fixture():
    return "\n".join(["CC_BOOTSTRAP_PASS valid=1", *[
        f"CC_UPDATE_PASS sample=0 order=0 hot=0 full=0 batch={batch} valid=1 update_until_converged_ms=1.5"
        for batch in range(11)], "CC_REPAIR_PASS vertices=12 updates=11 "
        "all_raw_labels_checked=1 all_raw_graphs_checked=1 all_round_work_checked=1"])


class SpineSmokeTest(unittest.TestCase):
    def test_all_distinct_batches_are_required(self):
        self.assertEqual(len(validate(fixture())), 11)
        for old, new in (("batch=5", "batch=4"), ("valid=1", "valid=0"),
                         ("hot=0", "hot=1"), ("sample=0", "sample=1"),
                         ("full=0", "full=1"), ("ms=1.5", "ms=0"),
                         ("ms=1.5", "ms=nan"), ("ms=1.5", "ms=inf"),
                         ("all_round_work_checked=1", "all_round_work_checked=0")):
            with self.subTest(change=(old, new)), self.assertRaises(ValueError):
                validate(fixture().replace(old, new))

    def test_final_marker_cannot_hide_missing_or_duplicate_updates(self):
        lines = fixture().splitlines()
        for text in ("\n".join(lines[:5] + lines[6:]), fixture() + "\n" + lines[1],
                     fixture() + "\n" + lines[-1], fixture() + "\nCC_BOOTSTRAP_PASS valid=1"):
            with self.assertRaises(ValueError):
                validate(text)

    def test_resident_requires_exact_domain_batch_and_physical_work(self):
        bootstrap, first, *_, final = fixture().splitlines()
        text = "\n".join((bootstrap, first + " physical_records=16",
                          final.replace("vertices=12 updates=11", "vertices=515281 updates=1")))
        expected = dict(vertices=515281, batches=1, physical_updates=16)
        self.assertEqual(len(validate(text, **expected)), 1)
        for old, new in (("records=16", "records=8"), ("vertices=515281", "vertices=515280"),
                         ("batch=0", "batch=1")):
            with self.assertRaises(ValueError):
                validate(text.replace(old, new), **expected)

    def test_native_input_preserves_domain_order_direction_weight_and_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.graph"
            source.write_text("4 2 2\n2 1 3\n1 2 9\n2 1 3 -1\n1 2 9 -1\n")
            result = spine_cc_input.prepare(source, root / "parts")
            self.assertEqual((result["vertices"], result["edges"], result["updates"]), (4, 2, 2))
            self.assertEqual(Path(result["graph"]["path"]).read_text(), "# vertices=4\n2 1 3 1\n1 2 9 1\n")
            self.assertEqual(Path(result["update"]["path"]).read_text(), "# vertices=4\n2 1 3 -1\n1 2 9 -1\n")
            self.assertEqual(result, json.loads((root / "parts" / "inputs.json").read_text()))

    def test_native_input_rejects_truncated_or_trailing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.graph"
            for index, suffix in enumerate(("", "1 2 9 1\n1 2 9 1\n")):
                source.write_text("4 1 1\n2 1 3\n" + suffix)
                output = root / f"parts-{index}"
                with self.assertRaises(ValueError):
                    spine_cc_input.prepare(source, output)
                self.assertFalse((output / "inputs.json").exists())

    def check_memory_failure(self, *, wait=0, decisions=None, times=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group = root / "group"
            group.mkdir()
            for name, value in {"memory.max": str(24 * 2**30), "memory.high": str(22 * 2**30),
                                "memory.swap.max": "0", "memory.oom.group": "1", "memory.peak": "0",
                                "memory.events": "high 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n"}.items():
                (group / name).write_text(value)
            args = argparse.Namespace(output=root / "output", host=root / "host", image=root / "image",
                                      admission_wait_seconds=wait)
            with mock.patch.object(spine_smoke.containment, "current", return_value=group), \
                    mock.patch.object(spine_smoke.containment, "other_builds", return_value=[]), \
                    mock.patch.object(spine_smoke, "available_memory_bytes", return_value=100 * 2**30), \
                    mock.patch.object(spine_smoke, "identity", side_effect=lambda path: {
                        "path": str(path), "sha256": "a" * 64}), \
                    mock.patch.object(spine_smoke, "Lease") as reservation, \
                    mock.patch.object(spine_smoke, "lease") as board, \
                    mock.patch.object(spine_smoke.time, "monotonic", side_effect=times or [0, 0]), \
                    mock.patch.object(spine_smoke.time, "sleep") as sleep:
                reservation.return_value.sample.side_effect = decisions or [{"admitted": False}]
                if decisions and decisions[-1]["admitted"]:
                    board.side_effect = RuntimeError("board test sentinel after admission")
                with self.assertRaises((MemoryError, RuntimeError)):
                    spine_smoke.run(args)
                if decisions and decisions[-1]["admitted"]:
                    board.assert_called_once()
                else:
                    board.assert_not_called()
                reservation.return_value.release.assert_called_once()
            report = json.loads((args.output / "results.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertFalse(report["performance_admission"])
            return report, sleep.call_args_list

    def test_failed_memory_admission_never_requests_the_board(self):
        report, sleeps = self.check_memory_failure()
        self.assertEqual(report["admission_attempts"], 1)
        self.assertEqual(sleeps, [])

    def test_bounded_wait_rechecks_full_budget_before_board(self):
        report, sleeps = self.check_memory_failure(wait=60, times=[0, 0, 30],
                                                   decisions=[{"admitted": False}, {"admitted": True}])
        self.assertEqual(report["admission_attempts"], 2)
        self.assertEqual(sleeps, [mock.call(30)])

    def test_expired_wait_never_requests_board(self):
        report, sleeps = self.check_memory_failure(wait=10, times=[0, 0, 10],
                                                   decisions=[{"admitted": False}, {"admitted": False}])
        self.assertEqual(report["admission_attempts"], 2)
        self.assertEqual(sleeps, [mock.call(10)])

    def test_unbounded_wait_rejected_before_output_creation(self):
        for value in (-1, 21601, 1.0, True):
            with self.subTest(wait=value), self.assertRaises(ValueError):
                spine_smoke.run(argparse.Namespace(admission_wait_seconds=value))


if __name__ == "__main__":
    unittest.main()
