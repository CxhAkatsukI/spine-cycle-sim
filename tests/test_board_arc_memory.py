"""ARC can relax board admission, not containment or experiment semantics."""

from pathlib import Path
import signal
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import (
    guarded_process, memory_policy as memory,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    correction_retime, dual_clock_resident,
)


GIB = 2**30


def observed(*, available=37, free=16, size=124, minimum=8, mru=51, mfu=51, pressure=0):
    meminfo = "\n".join(f"{key}: {value * 2**20} kB" for key, value in
                        (("MemTotal", 251), ("MemAvailable", available), ("MemFree", free)))
    arc = "\n".join(f"{key} 4 {value * GIB}" for key, value in
                    (("size", size), ("c_min", minimum),
                     ("mru_evictable_data", mru), ("mfu_evictable_data", mfu)))
    psi = f"some avg10={pressure} avg60=0 avg300=0 total=0\nfull avg10=0 avg60=0 avg300=0 total=0\n"
    return meminfo, arc, psi


class BoardArcMemoryTests(unittest.TestCase):
    def test_default_does_not_read_arc_and_scope_always_resets(self):
        with patch.object(memory, "available_memory_bytes", return_value=37 * GIB), \
                patch.object(Path, "read_text", side_effect=AssertionError("no ARC read")):
            self.assertEqual(memory.sample()["effective_available_bytes"], 37 * GIB)
        with self.assertRaisesRegex(RuntimeError, "reset"):
            with memory.scope(memory.ARC):
                self.assertEqual(memory.selected(), memory.ARC)
                raise RuntimeError("reset")
        self.assertEqual(memory.selected(), memory.DEFAULT)
        with self.assertRaises(ValueError):
            with memory.scope("unbounded"):
                self.fail("unknown profile admitted")

    def test_discount_avoids_double_counting_available_memory(self):
        row = memory.estimate(*observed())
        self.assertEqual(row["clean_evictable_bytes"], 102 * GIB)
        self.assertEqual(row["effective_available_bytes"], 67 * GIB)
        self.assertNotEqual(row["effective_available_bytes"], (37 + 51) * GIB)
        self.assertEqual(memory.estimate(*observed(available=90))["effective_available_bytes"], 90 * GIB)

    def test_arc_minimum_bounds_credit_and_metadata_is_not_counted(self):
        meminfo, arc, psi = observed(size=20, minimum=8)
        arc += f"\nmru_evictable_metadata 4 {99 * GIB}"
        row = memory.estimate(meminfo, arc, psi)
        self.assertEqual(row["clean_evictable_bytes"], 12 * GIB)
        self.assertEqual(row["effective_available_bytes"], 37 * GIB)
        self.assertEqual(memory.estimate(*observed(size=4))["clean_evictable_bytes"], 0)

    def test_missing_negative_duplicate_and_nonfinite_observations_fail_closed(self):
        meminfo, arc, psi = observed()
        cases = ((meminfo, "", psi), (meminfo, arc.replace(f"{124 * GIB}", "-1"), psi),
                 (meminfo, arc + f"\nsize 4 {124 * GIB}", psi),
                 (meminfo, arc, psi.replace("avg10=0", "avg10=nan")),
                 (meminfo, arc, ""))
        for case in cases:
            with self.subTest(case=case), self.assertRaises((ValueError, KeyError)):
                memory.estimate(*case)

    def test_pressure_blocks_even_when_arc_credit_is_large(self):
        self.assertFalse(memory.estimate(*observed(pressure=10))["pressure_ok"])
        for row in (dict(effective_available_bytes=31 * GIB, pressure_ok=True),
                    dict(effective_available_bytes=100 * GIB, pressure_ok=False)):
            with patch.object(memory, "sample", return_value=row), self.assertRaises(MemoryError):
                memory.live()

    def test_background_profile_has_explicit_limits_without_changing_strict_profiles(self):
        for profile in (memory.ARC, memory.ARC_SETTLE, memory.ARC_BACKGROUND):
            for full in (0.99, 1.0, 2.0, 4.99, 5.0):
                meminfo, arc, psi = observed()
                psi = psi.replace("full avg10=0", f"full avg10={full}")
                contents = iter((meminfo, arc, psi))
                with self.subTest(profile=profile, full=full), memory.scope(profile), \
                        patch.object(Path, "read_text", side_effect=lambda: next(contents)):
                    row = memory.sample()
                limit = 5 if profile == memory.ARC_BACKGROUND else 1
                self.assertEqual(row["pressure_ok"], full < limit)
                self.assertEqual(row["effective_available_bytes"], 67 * GIB)
                if profile == memory.ARC_BACKGROUND:
                    self.assertEqual(row["pressure_limits_avg10"], dict(some=10, full=5))
                else:
                    self.assertNotIn("pressure_limits_avg10", row)

    def test_background_does_not_relax_partial_pressure_or_physical_reserve(self):
        for some, full in ((10, 2), (2, 5)):
            meminfo, arc, psi = observed(pressure=some)
            psi = psi.replace("full avg10=0", f"full avg10={full}")
            contents = iter((meminfo, arc, psi))
            with self.subTest(some=some, full=full), memory.scope(memory.ARC_BACKGROUND), \
                    patch.object(Path, "read_text", side_effect=lambda: next(contents)), \
                    self.assertRaises(memory.ObservationError):
                memory.live()
        with memory.scope(memory.ARC_BACKGROUND), \
                patch.object(memory, "sample", return_value=dict(
                    effective_available_bytes=31 * GIB, pressure_ok=True)), \
                self.assertRaises(memory.ObservationError):
            memory.live(allow_transient_pressure=True)

    def test_guarded_process_records_live_observations(self):
        snapshot = memory.estimate(*observed())
        with memory.scope(memory.ARC), patch.object(memory, "live", return_value=snapshot):
            code, guard = guarded_process.run([sys.executable, "-c", "pass"], timeout=5,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertEqual(code, 0)
        self.assertEqual(guard["status"], "COMPLETED")
        self.assertEqual(guard["minimum_effective_available_bytes"], 67 * GIB)
        self.assertGreaterEqual(guard["checks"], 2)

    def test_pressure_failure_and_timeout_stop_only_the_owned_group(self):
        snapshot = memory.estimate(*observed())
        for error in (MemoryError("pressure"), subprocess.TimeoutExpired("child", 1)):
            process = Mock(pid=123456)
            process.__enter__ = Mock(return_value=process)
            process.__exit__ = Mock(return_value=False)
            with self.subTest(error=error), \
                    patch.object(memory, "live", side_effect=[snapshot, error]), \
                    patch.object(guarded_process.subprocess, "Popen", return_value=process), \
                    patch.object(guarded_process.os, "killpg") as kill, \
                    self.assertRaises(type(error)) as raised:
                guarded_process.run(["owned"], timeout=1)
            self.assertIs(raised.exception, error)
            self.assertEqual(error.memory_guard["status"], "ABORTED")
            self.assertEqual(error.memory_guard["last_observation"], snapshot)
            self.assertEqual(kill.call_args_list[0].args, (123456, signal.SIGTERM))
            self.assertEqual(kill.call_args_list[-1].args, (123456, signal.SIGKILL))

    def test_resident_and_host_retime_opt_in_without_changing_defaults(self):
        args = Mock(memory_profile=memory.ARC)
        for module in (dual_clock_resident, correction_retime):
            with self.subTest(module=module), patch.object(module, "_run", side_effect=lambda _: memory.selected()):
                self.assertEqual(module.run(args), memory.ARC)
                self.assertEqual(memory.selected(), memory.DEFAULT)

    def test_settle_profile_still_rejects_pressure_at_admission_and_reserve_loss(self):
        pressured = memory.estimate(*observed(pressure=11))
        with memory.scope(memory.ARC_SETTLE), patch.object(memory, "sample", return_value=pressured):
            with self.assertRaises(MemoryError):
                memory.live()
            self.assertEqual(memory.live(allow_transient_pressure=True), pressured)
        with memory.scope(memory.ARC), self.assertRaises(ValueError):
            memory.live(allow_transient_pressure=True)
        with memory.scope(memory.ARC_SETTLE), \
                patch.object(memory, "sample", return_value=dict(pressured, effective_available_bytes=31 * GIB)), \
                self.assertRaises(MemoryError):
            memory.live(allow_transient_pressure=True)

    def test_pressure_window_recovers_and_rejects_ten_seconds_of_continuous_pressure(self):
        high, low = dict(pressure_ok=False), dict(pressure_ok=True)
        window = memory.PressureWindow()
        window.check(high, 100)
        window.check(high, 109)
        window.check(low, 110)
        self.assertEqual(window.maximum_seconds, 10)
        self.assertEqual(window.pressured_checks, 2)
        window.check(high, 120)
        window.check(high, 129)
        with self.assertRaisesRegex(MemoryError, "ten seconds"):
            window.check(high, 130)
        self.assertEqual(window.maximum_seconds, 10)

    def test_settle_guard_records_recovered_pressure_without_changing_timeout(self):
        low = memory.estimate(*observed())
        high = dict(low, pressure_ok=False, pressure_avg10=dict(some=1.2, full=1.2))
        process = Mock(pid=123456)
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        process.wait.side_effect = [subprocess.TimeoutExpired("owned", 1), 0]
        with memory.scope(memory.ARC_SETTLE), \
                patch.object(memory, "live", side_effect=[low, high, low]) as live, \
                patch.object(guarded_process.subprocess, "Popen", return_value=process), \
                patch.object(guarded_process.time, "monotonic", side_effect=[0, 1, 1, 3, 3]):
            code, receipt = guarded_process.run(["owned"], timeout=5)
        self.assertEqual(code, 0)
        self.assertEqual(live.call_args_list[0].kwargs, {})
        self.assertEqual(live.call_args_list[1].kwargs, dict(allow_transient_pressure=True))
        self.assertEqual(receipt["maximum_consecutive_pressure_seconds"], 2)
        self.assertEqual(receipt["pressured_checks"], 1)
        self.assertEqual(receipt["pressure_grace_seconds"], 10)
        self.assertEqual(receipt["maximum_pressure_avg10"]["full"], 1.2)

    def test_settle_guard_kills_only_owned_group_on_sustained_pressure(self):
        low = memory.estimate(*observed())
        high = dict(low, pressure_ok=False)
        process = Mock(pid=123456)
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        process.wait.side_effect = [subprocess.TimeoutExpired("owned", 1), 0, 0, 0]
        with memory.scope(memory.ARC_SETTLE), \
                patch.object(memory, "live", side_effect=[low, high, high]), \
                patch.object(guarded_process.subprocess, "Popen", return_value=process), \
                patch.object(guarded_process.os, "killpg") as kill, \
                patch.object(guarded_process.time, "monotonic", side_effect=[0, 1, 1, 11]), \
                self.assertRaisesRegex(MemoryError, "ten seconds") as raised:
            guarded_process.run(["owned"], timeout=30)
        receipt = raised.exception.memory_guard
        self.assertEqual(receipt["last_observation"], high)
        self.assertEqual(receipt["checks"], 3)
        self.assertEqual(receipt["maximum_consecutive_pressure_seconds"], 10)
        self.assertEqual(receipt["pressured_checks"], 2)
        self.assertEqual(kill.call_args_list[0].args, (123456, signal.SIGTERM))
        self.assertEqual(kill.call_args_list[-1].args, (123456, signal.SIGKILL))

    def test_strict_stop_retains_the_failing_observation_and_peak(self):
        low = memory.estimate(*observed())
        high = dict(low, pressure_ok=False, effective_available_bytes=31 * GIB,
                    pressure_avg10=dict(some=2.0, full=2.0))
        error = memory.ObservationError("pressure", high)
        process = Mock(pid=123456)
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        with memory.scope(memory.ARC), \
                patch.object(memory, "live", side_effect=[low, error]), \
                patch.object(guarded_process.subprocess, "Popen", return_value=process), \
                patch.object(guarded_process.os, "killpg"), \
                self.assertRaises(MemoryError) as raised:
            guarded_process.run(["owned"], timeout=30)
        self.assertIs(raised.exception, error)
        receipt = error.memory_guard
        self.assertEqual(receipt["checks"], 2)
        self.assertEqual(receipt["last_observation"], high)
        self.assertEqual(receipt["minimum_effective_available_bytes"], 31 * GIB)
        self.assertEqual(receipt["maximum_pressure_avg10"], high["pressure_avg10"])


if __name__ == "__main__":
    unittest.main()
