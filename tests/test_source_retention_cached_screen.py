import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import cached_screen
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity


class CachedScreenTest(unittest.TestCase):
    def test_garbage_collected_service_requires_prior_witness_and_receipts(self):
        invocation = "a" * 32
        dead = dict(LoadState="not-found", ActiveState="inactive", SubState="dead", MainPID="0",
                    Result="success", ExecMainStatus="0", InvocationID="")
        active = dict(dead, LoadState="loaded", ActiveState="active", SubState="running", MainPID="123",
                      InvocationID=invocation)
        self.assertFalse(cached_screen.stopped(active, invocation))
        self.assertTrue(cached_screen.stopped(dead, invocation))
        for bad in (dict(active, InvocationID=""), dict(active, InvocationID="b" * 32),
                    dict(dead, Result="timeout"), dict(dead, MainPID="123")):
            with self.assertRaises(ValueError):
                cached_screen.stopped(bad, invocation)

    def test_clean_completion_binds_plan_cgroup_and_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = Path(tmp)
            execution = route / "execution"
            execution.mkdir()
            plan = route / "manifest.json"
            manifest = {"command": ["v++", "--link"], "pins": []}
            plan.write_text(json.dumps(manifest))
            plan_pin = identity(plan)
            launch = {"command": manifest["command"],
                      "pins": [{key: plan_pin[key] for key in ("path", "sha256")}]}
            (execution / "manifest.json").write_text(json.dumps(launch))
            binary = route / "candidate.hw.xclbin"
            binary.write_bytes(b"image")
            group = Path("/sys/fs/cgroup/cached.service")
            image = {key: value for key, value in identity(binary).items() if key != "bytes"}
            receipt = {"kind": "LINK", "status": "LINK_PASS_AWAITING_TIMING_AND_BOARD", "xclbin": image,
                       "containment": {"path": str(group)}, "admission": {"admitted": True},
                       "resources": {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}}
            record = execution / "execution.json"
            record.write_text(json.dumps(receipt))
            self.assertEqual(cached_screen.completed(route, manifest, plan_pin, group)[-1], image)
            with self.assertRaises(ValueError):
                cached_screen.completed(route, manifest, plan_pin, group.parent / "other.service")
            receipt["resources"]["stop_reason"] = "timeout"
            record.write_text(json.dumps(receipt))
            with self.assertRaises(ValueError):
                cached_screen.completed(route, manifest, plan_pin, group)
            receipt["resources"]["stop_reason"] = "process_exit"
            record.write_text(json.dumps(receipt))
            binary.write_bytes(b"substitute")
            with self.assertRaises(ValueError):
                cached_screen.completed(route, manifest, plan_pin, group)
