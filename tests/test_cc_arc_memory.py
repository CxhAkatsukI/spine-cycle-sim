"""CC ARC admission changes observation, not resource budgets or board semantics."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import (
    memory_policy as memory, tree_memory,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    active_min_resident as resident, cc_au_collect, cc_warm_matrix, resident_matrix, spine_smoke,
)
from spine_cycle_sim.experiments.sharded_k4_stages import link_runtime


GIB = 2**30


def observation(*, available=67, pressured=False):
    return dict(profile=memory.ARC, effective_available_bytes=available * GIB,
                mem_available_bytes=17 * GIB, mem_free_bytes=16 * GIB,
                clean_evictable_bytes=102 * GIB,
                pressure_avg10=dict(some=2.0 if pressured else 0, full=2.0 if pressured else 0),
                pressure_ok=not pressured)


class CcArcMemoryTests(unittest.TestCase):
    def test_opt_in_scope_is_explicit_and_resets(self):
        for module in (resident, spine_smoke, cc_au_collect, cc_warm_matrix):
            with self.subTest(module=module), patch.object(module, "_run", side_effect=lambda _: memory.selected()):
                self.assertEqual(module.run(argparse.Namespace(memory_profile=memory.ARC)), memory.ARC)
                self.assertEqual(module.run(argparse.Namespace()), memory.DEFAULT)
                self.assertEqual(memory.selected(), memory.DEFAULT)
        with self.assertRaises(ValueError):
            tree_memory.Observer(5)

    def test_tree_watchdog_uses_discounted_observation_without_changing_cleanup(self):
        with tempfile.TemporaryDirectory() as directory, memory.scope(memory.ARC), \
                patch.object(memory, "live", return_value=observation()), \
                patch.object(link_runtime, "available_memory_bytes", side_effect=AssertionError("raw-only check")):
            root = Path(directory)
            observer = tree_memory.Observer(5)
            row = link_runtime.run_link([sys.executable, "-c", "print('done')"], root, root / "child",
                                        timeout=5, tree_memory_gib=1, reserve_gib=32,
                                        poll_seconds=0.01, memory_observer=observer)
            self.assertEqual(row["exit_code"], 0)
            self.assertEqual(row["available_before_bytes"], 67 * GIB)
            self.assertEqual(row["available_memory_basis"], "explicit_memory_observer")
            self.assertEqual(row["cleanup_signaled_pids"], [])
            self.assertIsNone(row["cleanup_snapshot_error"])
            self.assertEqual(observer.receipt["admission"]["mem_available_bytes"], 17 * GIB)
            self.assertGreaterEqual(observer.receipt["checks"], 1)

    def test_tree_pressure_failure_keeps_real_cleanup_and_observation(self):
        high = observation(pressured=True)
        failure = memory.ObservationError("pressure", high)
        with tempfile.TemporaryDirectory() as directory, memory.scope(memory.ARC), \
                patch.object(memory, "live", side_effect=[observation(), failure]):
            root = Path(directory)
            observer = tree_memory.Observer(5)
            with self.assertRaises(memory.ObservationError) as raised:
                link_runtime.run_link([sys.executable, "-c", "import time; time.sleep(60)"],
                                      root, root / "child", timeout=5, tree_memory_gib=1,
                                      reserve_gib=32, poll_seconds=0.01, memory_observer=observer)
            self.assertIs(raised.exception, failure)
            saved = json.loads((root / "child.resources.json").read_text())
            self.assertEqual(saved["stop_reason"], "watchdog_error_or_interruption")
            self.assertLess(saved["exit_code"], 0)
            self.assertTrue(saved["cleanup_signaled_pids"])
            self.assertEqual(observer.receipt["last_observation"], high)
            self.assertEqual(observer.receipt["status"], "ABORTED")

    def test_missing_headroom_and_pressure_do_not_start_a_tree(self):
        cases = (observation(available=40), memory.ObservationError("pressure", observation(pressured=True)))
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory, memory.scope(memory.ARC), \
                    patch.object(memory, "live", **({"side_effect": case} if isinstance(case, Exception)
                                                   else {"return_value": case})), \
                    patch.object(link_runtime.subprocess, "Popen") as child:
                root = Path(directory)
                expected = MemoryError if isinstance(case, Exception) else RuntimeError
                with self.assertRaises(expected):
                    link_runtime.run_link(["never"], root, root / "child", tree_memory_gib=24,
                                          reserve_gib=32, memory_observer=tree_memory.Observer(5))
                child.assert_not_called()

    def test_settling_still_stops_sustained_pressure_and_records_peak(self):
        low, high = observation(), observation(pressured=True)
        with memory.scope(memory.ARC_SETTLE), patch.object(memory, "live", side_effect=[low, high, high]), \
                patch.object(tree_memory.time, "monotonic", side_effect=[100, 110]):
            observer = tree_memory.Observer(30)
            self.assertEqual(observer(initial=True), 67 * GIB)
            observer(initial=False)
            with self.assertRaisesRegex(MemoryError, "ten seconds"):
                observer(initial=False)
        self.assertEqual(observer.receipt["maximum_consecutive_pressure_seconds"], 10)
        self.assertEqual(observer.receipt["pressured_checks"], 2)
        self.assertEqual(observer.receipt["maximum_pressure_avg10"]["full"], 2)

    def test_background_profile_keeps_ten_second_tree_stop(self):
        low = observation()
        high = dict(observation(pressured=True), pressure_avg10=dict(some=6, full=6))
        with memory.scope(memory.ARC_BACKGROUND), \
                patch.object(memory, "live", side_effect=[low, high, high]), \
                patch.object(tree_memory.time, "monotonic", side_effect=[100, 110]):
            observer = tree_memory.Observer(30)
            observer(initial=True)
            observer(initial=False)
            with self.assertRaisesRegex(memory.ObservationError, "ten seconds"):
                observer(initial=False)
        self.assertEqual(observer.receipt["pressure_grace_seconds"], 10)
        self.assertEqual(observer.receipt["maximum_consecutive_pressure_seconds"], 10)

    def test_matrix_forwards_profile_and_keeps_32_gib_budget_and_zero_swap(self):
        args = argparse.Namespace(**{key: Path(key) for key in resident_matrix.INPUTS},
                                  algorithm="cc", child_prefix="test-cc", wait_seconds=60,
                                  memory_profile=memory.ARC_SETTLE)
        command = resident_matrix.child_command(args, "LJ08", 32, Path("output"), packet=Path("packet"))
        self.assertIn("--property=MemoryMax=32G", command)
        self.assertIn("--property=MemoryHigh=30G", command)
        self.assertIn("--property=MemorySwapMax=0", command)
        self.assertEqual(command[-2:], ["--memory-profile", memory.ARC_SETTLE])

    def test_resident_arm_retains_guard_and_custom_host_environment(self):
        with tempfile.TemporaryDirectory() as directory, memory.scope(memory.ARC):
            root = Path(directory)
            expected = dict(binary=dict(sha256="a" * 64))
            evidence = dict(bdf=resident.BDF, **expected)
            with patch.object(resident.containment, "current", return_value=root), \
                    patch.object(resident.guarded_process, "run", return_value=(0, dict(status="COMPLETED"))) as run, \
                    patch.object(resident.clocks, "capture", return_value=evidence), \
                    patch.object(resident.clocks, "replay", return_value=evidence):
                row = resident.arm("gr", ["owned"], expected, root, cc_wall=True)
            self.assertEqual(row["memory_guard"]["status"], "COMPLETED")
            self.assertEqual(run.call_args.kwargs["env"]["GRASU_SHARDED_RESIDENT_BATCH_WALL"], "1")
            self.assertEqual(run.call_args.kwargs["timeout"], 1800)

    def test_failed_resident_arm_preserves_original_error_and_log_hashes(self):
        failure = MemoryError("pressure")
        failure.memory_guard = dict(status="ABORTED", checks=2)
        with tempfile.TemporaryDirectory() as directory, memory.scope(memory.ARC):
            root = Path(directory)
            with patch.object(resident.containment, "current", return_value=root), \
                    patch.object(resident.guarded_process, "run", side_effect=failure), \
                    self.assertRaises(MemoryError) as raised:
                resident.arm("spine", ["owned"], {}, root)
            self.assertIs(raised.exception, failure)
            self.assertEqual(resident.identity(failure.memory_guard_receipt["path"]), failure.memory_guard_receipt)
            saved = json.loads(Path(failure.memory_guard_receipt["path"]).read_text())
            self.assertEqual(saved["memory_guard"], failure.memory_guard)
            self.assertEqual(resident.identity(saved["stdout"]["path"]), saved["stdout"])


if __name__ == "__main__":
    unittest.main()
