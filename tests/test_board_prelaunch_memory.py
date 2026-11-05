"""A preparation-to-launch pressure race queues without launching or relaxing gates."""

import subprocess
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import (
    guarded_process, memory_policy as memory, prelaunch_memory as prelaunch,
)


LOW = dict(effective_available_bytes=64 * 2**30, pressure_ok=True)
HIGH = dict(LOW, pressure_ok=False)


def pressure(observation=HIGH):
    return memory.ObservationError("pressure", observation)


class PrelaunchMemoryTests(unittest.TestCase):
    def test_unbounded_or_nonpositive_timeouts_are_rejected(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                prelaunch.admit(value)

    def test_low_pressure_does_not_wait_or_change_the_observation(self):
        with patch.object(memory, "live", return_value=LOW), \
                patch.object(prelaunch.time, "sleep") as sleep:
            observed, receipt = prelaunch.admit(30)
        self.assertIs(observed, LOW)
        self.assertEqual(receipt["checks"], 1)
        self.assertEqual(receipt["waited_seconds"], 0)
        self.assertFalse(receipt["child_started"])
        sleep.assert_not_called()

    def test_settle_profile_waits_then_requires_a_strictly_passing_sample(self):
        with memory.scope(memory.ARC_SETTLE), \
                patch.object(memory, "live", side_effect=[pressure(), LOW]) as live, \
                patch.object(prelaunch.time, "monotonic", side_effect=[100, 101]), \
                patch.object(prelaunch.time, "sleep") as sleep:
            observed, receipt = prelaunch.admit(30)
        self.assertIs(observed, LOW)
        self.assertEqual(receipt["checks"], 2)
        self.assertEqual(receipt["pressure_checks"], 1)
        self.assertEqual(receipt["waited_seconds"], 1)
        self.assertTrue(all(call.kwargs == {} for call in live.call_args_list))
        sleep.assert_called_once_with(1)

    def test_no_child_starts_when_bounded_re_admission_expires(self):
        failure = pressure()
        with memory.scope(memory.ARC_SETTLE), \
                patch.object(memory, "live", side_effect=[pressure(), failure]), \
                patch.object(prelaunch.time, "monotonic", side_effect=[100, 160]), \
                patch.object(prelaunch.time, "sleep"), \
                patch.object(guarded_process.subprocess, "Popen") as child, \
                self.assertRaises(memory.ObservationError) as raised:
            guarded_process.run(["owned"], timeout=1800)
        self.assertIs(raised.exception, failure)
        self.assertEqual(failure.memory_guard["status"], "NOT_STARTED")
        self.assertFalse(failure.memory_guard["child_started"])
        self.assertEqual(failure.memory_guard["prelaunch"]["waited_seconds"], 60)
        child.assert_not_called()

    def test_wait_never_exceeds_the_supplied_process_timeout(self):
        with memory.scope(memory.ARC_SETTLE), \
                patch.object(memory, "live", side_effect=[pressure(), pressure()]), \
                patch.object(prelaunch.time, "monotonic", side_effect=[100, 100.5]), \
                patch.object(prelaunch.time, "sleep") as sleep, \
                self.assertRaises(memory.ObservationError):
            prelaunch.admit(0.5)
        sleep.assert_called_once_with(0.5)

    def test_reserve_breach_and_strict_profiles_still_fail_immediately(self):
        for profile, observation in ((memory.ARC, HIGH), (memory.DEFAULT, HIGH),
                (memory.ARC_SETTLE, dict(HIGH, effective_available_bytes=31 * 2**30))):
            failure = pressure(observation)
            with self.subTest(profile=profile), memory.scope(profile), \
                    patch.object(memory, "live", side_effect=failure), \
                    patch.object(prelaunch.time, "sleep") as sleep, \
                    self.assertRaises(memory.ObservationError) as raised:
                prelaunch.admit(30)
            self.assertIs(raised.exception, failure)
            sleep.assert_not_called()

    def test_a_passing_sample_after_the_deadline_cannot_launch(self):
        with memory.scope(memory.ARC_SETTLE), \
                patch.object(memory, "live", side_effect=[pressure(), LOW]), \
                patch.object(prelaunch.time, "monotonic", side_effect=[100, 102]), \
                patch.object(prelaunch.time, "sleep"), \
                patch.object(guarded_process.subprocess, "Popen") as child, \
                self.assertRaises(subprocess.TimeoutExpired) as raised:
            guarded_process.run(["owned"], timeout=2)
        self.assertFalse(raised.exception.memory_guard["child_started"])
        self.assertEqual(raised.exception.memory_guard["prelaunch"]["status"], "NOT_STARTED")
        child.assert_not_called()

    def test_malformed_observations_are_not_retried(self):
        with memory.scope(memory.ARC_SETTLE), \
                patch.object(memory, "live", side_effect=ValueError("bad counters")), \
                patch.object(prelaunch.time, "sleep") as sleep, \
                self.assertRaisesRegex(ValueError, "bad counters"):
            prelaunch.admit(30)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
