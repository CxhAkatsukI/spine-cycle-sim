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


class CleanupTests(unittest.TestCase):
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
                    if not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] == "Z":
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
