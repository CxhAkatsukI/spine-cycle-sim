"""The convergence study cannot bypass its full-budget remote admission."""

from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import runtime


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        self.selected = runtime.settings(runtime.memory_profiles.SEELE, 4)
        self.group = Path("/owned/cgroup")
        self.guard = {"limits": {"memory.max": str(40 * 1024**3),
                                 "memory.high": str(36 * 1024**3)}}
        self.lease = Mock()
        self.lease.sample.return_value = {"admitted": True}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in (("current", self.group), ("verify", self.guard),
                            ("available_memory_bytes", 400 * 1024**3), ("other_builds", [])):
            self.stack.enter_context(patch.object(runtime, name, return_value=value))
        self.factory = self.stack.enter_context(patch.object(runtime.high_memory, "lease", return_value=self.lease))
        self.thread = self.stack.enter_context(patch.object(runtime.threading, "Thread"))
        self.sleep = self.stack.enter_context(patch.object(runtime.time, "sleep"))

    def test_named_full_budget_is_committed_and_released(self):
        with runtime.reservation(self.output, self.selected) as safety:
            policy = safety["policy"]
            self.assertEqual((policy["tree_memory_gib"], policy["reserve_gib"],
                              policy["background_memory_gib"]), (40, 128, 8))
            self.assertEqual(policy[runtime.memory_profiles.KEY], runtime.memory_profiles.SEELE)
            self.factory.assert_called_once_with(
                Path.home() / ".cache/spine-cycle-sim/compiler-reservations", self.group, policy)
            self.lease.sample.assert_called_once_with(400 * 1024**3, [], policy, commit=True)
            self.thread.return_value.start.assert_called_once()
        self.lease.release.assert_called_once()

    def test_bad_max_or_high_rejected_before_lease(self):
        for key in ("memory.max", "memory.high"):
            with self.subTest(key=key):
                original = self.guard["limits"][key]
                self.guard["limits"][key] = "1"
                with self.assertRaisesRegex(ValueError, "exact max/high"):
                    with runtime.reservation(self.output, self.selected):
                        self.fail("invalid containment yielded")
                self.guard["limits"][key] = original
        self.factory.assert_not_called()

    def test_denial_waits_without_starting_work(self):
        self.lease.sample.side_effect = [{"admitted": False}, {"admitted": True}]
        with runtime.reservation(self.output, self.selected):
            self.assertEqual(self.lease.sample.call_count, 2)
            self.sleep.assert_called_once_with(5)
        self.lease.release.assert_called_once()

    def test_timeout_releases_without_watchdog_or_yield(self):
        self.lease.sample.return_value = {"admitted": False}
        with patch.object(runtime.time, "monotonic", side_effect=[0, 601]), \
                self.assertRaisesRegex(TimeoutError, "admission timeout"):
            with runtime.reservation(self.output, self.selected):
                self.fail("denied study yielded")
        self.thread.assert_not_called()
        self.lease.release.assert_called_once()

    def test_failed_sampling_and_failed_work_both_release(self):
        self.lease.sample.side_effect = ValueError("peer evidence missing")
        with self.assertRaisesRegex(ValueError, "peer evidence missing"):
            with runtime.reservation(self.output, self.selected):
                self.fail("invalid peers yielded")
        self.lease.release.assert_called_once()
        self.lease.reset_mock(side_effect=True)
        self.lease.sample.return_value = {"admitted": True}
        with self.assertRaisesRegex(RuntimeError, "numerical failure"):
            with runtime.reservation(self.output, self.selected):
                raise RuntimeError("numerical failure")
        self.lease.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
