"""Pending build reservations close the tool-start race without lifetime locks."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import concurrent


class MemoryLeaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root, self.proc = self.base / "groups", self.base / "proc"
        self.directory = self.base / "leases"
        self.policy = {"tree_memory_gib": 40, "reserve_gib": 24,
                       "allow_bounded_builds": True, "background_memory_gib": 8}
        self.first, self.second = self.group("first"), self.group("second")
        process = self.proc / str(os.getpid())
        process.mkdir(parents=True)
        (process / "stat").write_text(f"{os.getpid()} (worker with spaces) " + " ".join(["1"] * 22))

    def group(self, name):
        path = self.root / name
        path.mkdir(parents=True)
        for key, value in {"memory.max": str(40 * concurrent.GIB),
                "memory.high": str(36 * concurrent.GIB), "memory.swap.max": "0",
                "memory.oom.group": "1", "cgroup.events": "populated 1\n"}.items():
            (path / key).write_text(value)
        return path

    def lease(self, group):
        return concurrent.Lease(self.directory, group, proc=self.proc, root=self.root)

    def test_pending_build_counts_before_a_vendor_process_exists(self):
        first, second = self.lease(self.first), self.lease(self.second)
        self.assertTrue(first.sample(120 * concurrent.GIB, [], self.policy, commit=True)["admitted"])
        state = second.sample(111 * concurrent.GIB, [], self.policy, commit=True)
        self.assertFalse(state["admitted"])
        self.assertEqual(state["required_bytes"], 112 * concurrent.GIB)
        self.assertFalse(second.held)
        self.assertTrue(second.sample(112 * concurrent.GIB, [], self.policy, commit=True)["admitted"])
        second.release()
        first.release()
        self.assertEqual(list(self.directory.glob("*.json")), [])

    def test_running_tool_and_pending_lease_are_not_double_counted(self):
        first, second = self.lease(self.first), self.lease(self.second)
        first.sample(120 * concurrent.GIB, [], self.policy, commit=True)
        rows = [{"cgroup": str(self.first), "bounded": True, "memory_max_bytes": 40 * concurrent.GIB}]
        with patch.object(concurrent, "reservations", return_value=rows):
            state = second.sample(112 * concurrent.GIB, ["123 vivado"], self.policy)
        self.assertEqual(len(state["reservations"]), 1)
        self.assertEqual(state["required_bytes"], 112 * concurrent.GIB)
        first.release()

    def test_crashed_owner_keeps_budget_while_children_remain(self):
        first, second = self.lease(self.first), self.lease(self.second)
        first.sample(120 * concurrent.GIB, [], self.policy, commit=True)
        row = json.loads(first.path.read_text())
        row["pid"] = 999999
        first.path.write_text(json.dumps(row))
        self.assertFalse(second.sample(100 * concurrent.GIB, [], self.policy)["admitted"])
        (self.first / "cgroup.events").write_text("populated 0\n")
        self.assertTrue(second.sample(100 * concurrent.GIB, [], self.policy)["admitted"])
        self.assertFalse(first.path.exists())

    def test_same_cgroup_and_changed_limits_fail_closed(self):
        first, second = self.lease(self.first), self.lease(self.second)
        first.sample(120 * concurrent.GIB, [], self.policy, commit=True)
        with self.assertRaisesRegex(ValueError, "already reserved"):
            self.lease(self.first).sample(200 * concurrent.GIB, [], self.policy)
        (self.first / "memory.max").write_text(str(39 * concurrent.GIB))
        with self.assertRaisesRegex(ValueError, "limit changed"):
            second.sample(200 * concurrent.GIB, [], self.policy)
        first.release()

    def test_conflicting_or_unbounded_reservations_reject(self):
        rows = [{"cgroup": str(self.first), "memory_max_bytes": 40 * concurrent.GIB, "bounded": True}]
        changed = [{**rows[0], "memory_max_bytes": 39 * concurrent.GIB}]
        merged = concurrent.merge(rows, changed)
        self.assertFalse(concurrent.eligible(200 * concurrent.GIB, merged, self.policy))
        with patch.object(concurrent, "reservations", return_value=[{"pid": 9, "bounded": False}]):
            self.assertFalse(self.lease(self.first).sample(200 * concurrent.GIB, ["9 vivado"], self.policy)["admitted"])

    def test_start_time_handles_spaces_in_process_name(self):
        self.assertEqual(concurrent.start_time(os.getpid(), self.proc), "1")


if __name__ == "__main__":
    unittest.main()
