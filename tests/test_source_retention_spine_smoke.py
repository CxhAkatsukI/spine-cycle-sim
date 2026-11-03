"""A partial CC fixture is not a repeated full-performance comparison."""

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import spine_smoke

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

    def test_failed_memory_admission_never_requests_the_board(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group = root / "group"
            group.mkdir()
            for name, value in {"memory.max": str(24 * 2**30), "memory.high": str(22 * 2**30),
                                "memory.swap.max": "0", "memory.oom.group": "1", "memory.peak": "0",
                                "memory.events": "high 0\nmax 0\noom 0\noom_kill 0\noom_group_kill 0\n"}.items():
                (group / name).write_text(value)
            args = argparse.Namespace(output=root / "output", host=root / "host", image=root / "image")
            with mock.patch.object(spine_smoke.containment, "current", return_value=group), \
                    mock.patch.object(spine_smoke.containment, "other_builds", return_value=[]), \
                    mock.patch.object(spine_smoke, "available_memory_bytes", return_value=100 * 2**30), \
                    mock.patch.object(spine_smoke, "identity", return_value={"sha256": "a" * 64}), \
                    mock.patch.object(spine_smoke, "Lease") as reservation, \
                    mock.patch.object(spine_smoke, "lease") as board:
                reservation.return_value.sample.return_value = {"admitted": False}
                with self.assertRaises(MemoryError):
                    spine_smoke.run(args)
                board.assert_not_called()
                reservation.return_value.release.assert_called_once()
            report = json.loads((args.output / "results.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertFalse(report["performance_admission"])


if __name__ == "__main__":
    unittest.main()
