"""Concurrent diagnostic routes retain budget, fresh-attempt and failure gates."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware import supervisor


class RouteSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "route"
        self.output.mkdir()
        self.group = Path(self.tmp.name) / "cgroup"
        self.group.mkdir()
        (self.group / "memory.events").write_text("oom 0\noom_kill 0\n")
        self.manifest = {"status": "PREPARED_DIAGNOSTIC_LINK_NOT_BASELINE_ADMISSION",
            "tree_memory_gib": 40, "reserve_gib": 24, "background_memory_gib": 8,
            "allow_bounded_builds": True, "timeout_seconds": 21600,
            "queue_timeout_seconds": 86400, "pins": []}
        self.write_manifest()
        (self.output / "environment.json").write_text(json.dumps({"pins": []}))
        self.peer = "123 vivado"
        self.samples = []

    def write_manifest(self):
        (self.output / "manifest.json").write_text(json.dumps(self.manifest))

    def mocks(self):
        for name, value in (("current", self.group), ("verify", {"limits": {}}),
                ("available_memory_bytes", 126 * 1024**3), ("other_builds", [self.peer]),
                ("unchanged", None), ("reconstruct", ({}, {"pins": []})),
                ("execute", {"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD"})):
            patcher = patch.object(supervisor, name, return_value=value)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            setattr(self, name + "_mock", mock)
        self.preflight = patch.object(supervisor, "preflight", side_effect=self.preflight_ok).start()
        self.addCleanup(patch.stopall)
        patch.object(supervisor.time, "sleep", return_value=None).start()
        self.lease = patch.object(supervisor, "Lease").start().return_value
        self.lease.held = False
        self.lease.sample.side_effect = self.sample

    def preflight_ok(self, output, *_):
        (output / "preflight").mkdir()
        (output / "preflight/results.json").write_text('{}')

    def sample(self, available, active, manifest, *, commit):
        self.samples.append(commit)
        self.assertEqual(active, [self.peer])
        self.assertEqual(available, 126 * 1024**3)
        self.assertEqual(manifest["tree_memory_gib"], 40)
        self.lease.held = commit
        return {"admitted": True, "required_bytes": 112 * 1024**3}

    def test_peer_tool_does_not_prevent_admitted_route(self):
        self.mocks()
        result = supervisor.run(Path("/old-build"), self.output)
        self.assertEqual(self.samples, [False] * 7 + [True])
        self.assertTrue(result["route_started"])
        self.assertFalse(result["production_baseline_admitted"])
        self.assertFalse(result["FPGA_timing_admitted"])
        self.preflight.assert_called_once()
        self.execute_mock.assert_called_once()
        self.lease.release.assert_called_once()
        self.assertEqual(json.loads((self.output / "cgroup_events.json").read_text())["oom"], "0")

    def test_preflight_failure_retained_without_route_or_leaked_lease(self):
        self.mocks()
        self.preflight.side_effect = ValueError("bad environment")
        with self.assertRaises(ValueError):
            supervisor.run(Path("/old-build"), self.output)
        self.execute_mock.assert_not_called()
        self.lease.release.assert_called_once()
        failure = json.loads((self.output / "execution.json").read_text())
        self.assertEqual(failure["status"], "SUPERVISOR_FAILED_RETAINED")
        self.assertFalse(failure["route_started"])

    def test_existing_execution_not_overwritten(self):
        self.mocks()
        record = self.output / "execution.json"
        record.write_text('{"status":"OLD_ATTEMPT"}')
        with self.assertRaises(FileExistsError):
            supervisor.run(Path("/old-build"), self.output)
        self.lease.sample.assert_not_called()
        self.execute_mock.assert_not_called()
        self.assertEqual(json.loads(record.read_text())["status"], "OLD_ATTEMPT")

    def test_changed_safety_policy_rejected(self):
        self.mocks()
        self.manifest["reserve_gib"] = 0
        self.write_manifest()
        with self.assertRaises(ValueError):
            supervisor.run(Path("/old-build"), self.output)
        self.lease.sample.assert_not_called()


if __name__ == "__main__":
    unittest.main()
