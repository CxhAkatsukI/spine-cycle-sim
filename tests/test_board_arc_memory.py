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

    def test_guarded_process_records_live_observations(self):
        snapshot = memory.estimate(*observed())
        with memory.scope(memory.ARC), patch.object(memory, "live", return_value=snapshot):
            code, guard = guarded_process.run([sys.executable, "-c", "pass"], timeout=5,
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertEqual(code, 0)
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
                    self.assertRaises(type(error)):
                guarded_process.run(["owned"], timeout=1)
            self.assertEqual(kill.call_args_list[0].args, (123456, signal.SIGTERM))
            self.assertEqual(kill.call_args_list[-1].args, (123456, signal.SIGKILL))

    def test_resident_and_host_retime_opt_in_without_changing_defaults(self):
        args = Mock(memory_profile=memory.ARC)
        for module in (dual_clock_resident, correction_retime):
            with self.subTest(module=module), patch.object(module, "_run", side_effect=lambda _: memory.selected()):
                self.assertEqual(module.run(args), memory.ARC)
                self.assertEqual(memory.selected(), memory.DEFAULT)


if __name__ == "__main__":
    unittest.main()
