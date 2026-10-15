"""A watchdog timeout must also stop an observed new-session worker."""

import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import subprocess

from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link, tree_rss_kib
from spine_cycle_sim.experiments.sharded_k4_stages.process_cleanup import ObservedProcesses


class CleanupTests(unittest.TestCase):
    def test_exited_workers_do_not_accumulate_descriptors(self):
        before = len(os.listdir("/proc/self/fd"))
        read_end, write_end = os.pipe()
        os.close(write_end)
        workers = ObservedProcesses()
        try:
            with patch("os.pidfd_open", side_effect=lambda pid: os.dup(read_end)):
                for pid in range(1, 2049):
                    workers.observe([pid])
                    self.assertEqual(workers.live_pids(), [])
                    self.assertEqual(workers.handles, {})
            self.assertEqual(len(workers.observed_pids), 2048)
            self.assertEqual(len(os.listdir("/proc/self/fd")), before + 1)
        finally:
            workers.close()
            os.close(read_end)
        self.assertEqual(len(os.listdir("/proc/self/fd")), before)

    def test_exited_handle_is_closed_before_observing_reused_pid(self):
        first_read, first_write = os.pipe()
        second_read, second_write = os.pipe()
        workers = ObservedProcesses()
        try:
            with patch("os.pidfd_open", side_effect=[os.dup(first_read), os.dup(second_read)]):
                workers.observe([123])
                old_handle = workers.handles[123]
                os.close(first_write)
                first_write = None
                self.assertEqual(workers.live_pids(), [])
                with self.assertRaises(OSError):
                    os.fstat(old_handle)
                workers.observe([123])
                new_handle = workers.handles[123]
                self.assertEqual(workers.live_pids(), [123])
                with patch("signal.pidfd_send_signal") as send:
                    self.assertEqual(workers.kill(999), [123])
                    send.assert_called_once_with(new_handle, signal.SIGKILL)
                self.assertEqual(workers.observed_pids, {123})
        finally:
            workers.close()
            for descriptor in (first_read, first_write, second_read, second_write):
                if descriptor is not None:
                    os.close(descriptor)

    def test_final_snapshot_failure_still_saves_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("spine_cycle_sim.experiments.sharded_k4_stages.link_runtime.subprocess.check_output",
                       side_effect=subprocess.TimeoutExpired("ps", 10)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    run_link([sys.executable, "-c", "import time; time.sleep(60)"], root, root / "error",
                             timeout=2, tree_memory_gib=1, reserve_gib=0, poll_seconds=0.02)
            record = json.loads((root / "error.resources.json").read_text())
            self.assertEqual(record["stop_reason"], "cleanup_snapshot_failed")
            self.assertIsNotNone(record["cleanup_snapshot_error"])
            self.assertLess(record["exit_code"], 0)

    def test_tracked_worker_stays_in_memory_scope_after_reparenting(self):
        self.assertEqual(tree_rss_kib("11 1 11 200\n12 11 12 300\n20 1 20 9000", 10, [11]),
                         (500, [11, 12]))

    def test_timeout_kills_nested_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pid_path = root / "worker.pid"
            child = "import time; time.sleep(60)"
            parent = ("import subprocess, sys, time; from pathlib import Path; "
                      f"p = subprocess.Popen([sys.executable, '-c', {child!r}], start_new_session=True); "
                      f"Path({str(pid_path)!r}).write_text(str(p.pid)); time.sleep(60)")
            try:
                record = run_link([sys.executable, "-c", parent], root, root / "nested",
                                  timeout=1, tree_memory_gib=1, reserve_gib=0, poll_seconds=0.02)
                pid = int(pid_path.read_text())
                self.assertEqual(record["stop_reason"], "timeout")
                self.assertIn(pid, record["observed_pids"])
                self.assertIn(pid, record["cleanup_signaled_pids"])
                for _ in range(100):
                    stat = Path(f"/proc/{pid}/stat")
                    try:
                        state = stat.read_text().rsplit(")", 1)[1].split()[0]
                    except (FileNotFoundError, ProcessLookupError):
                        break
                    if state == "Z":
                        break
                    time.sleep(0.01)
                else:
                    self.fail("nested-session worker survived watchdog timeout")
                self.assertEqual(json.loads((root / "nested.resources.json").read_text()), record)
            finally:
                if pid_path.exists():
                    try:
                        os.kill(int(pid_path.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass


if __name__ == "__main__":
    unittest.main()
