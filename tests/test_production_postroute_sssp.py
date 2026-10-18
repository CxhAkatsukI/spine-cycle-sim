"""The remote SSSP producer is not the experimental algorithm-link schema."""

import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.postroute import (
    inputs, sssp_inputs,
)
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def fixture(root):
    capsule, delivery = sssp_inputs.capsule, sssp_inputs.delivery
    packet = {"parent": {"path": "/frozen/parent.json", "sha256": "a" * 64},
              "files": [{"member": "inputs/kernel.xo"}], "timeout_seconds": 43200}
    for name in ("capsule.json", "inputs/kernel.xo", "environment.json", "link.cfg",
                 "candidate.hw.xclbin"):
        write(root / name, {})
    write(root / "environment.json", {"tools": {"v++": {"invocation": "/vendor/v++"}}})
    command = ["/vendor/v++", "--link", "--kernel_frequency", "150"]
    clean = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}
    child = {**clean, "command": command, "cwd": str(root), "tree_memory_gib": 40,
             "reserve_gib": 32, "timeout_seconds": 43200}
    probes = {"status": "PREFLIGHT_PASS_NOT_ROUTED",
              "commands": [{"label": label, **clean} for label in delivery.LABELS]}
    for row in probes["commands"]:
        write(root / f"preflight/{row['label']}.resources.json", clean)
    write(root / "preflight/results.json", probes)
    write(root / "route.resources.json", child)
    manifest = {"parent": packet["parent"], "relocation": identity(root / "capsule.json"),
                "clock_mhz": 150, "policy": dict(capsule.POLICY), "command": command,
                "pins": [identity(root / name) for name in
                         ("capsule.json", "inputs/kernel.xo", "environment.json", "link.cfg")],
                **dict.fromkeys(capsule.FLAGS, False)}
    write(root / "manifest.json", manifest)
    execution = {"parent": packet["parent"], "host": socket.gethostname(),
                 "capsule": identity(root / "capsule.json"), "manifest": identity(root / "manifest.json"),
                 "xclbin": identity(root / "candidate.hw.xclbin"), "route": child,
                 "status": delivery.PASS, "errors": [],
                 "memory_events_after": "oom 0\noom_kill 0\noom_group_kill 0\n",
                 **dict.fromkeys(capsule.FLAGS, False)}
    write(root / "execution.json", execution)
    return packet, manifest, execution, probes, command


class RemoteSSSPPostrouteTests(unittest.TestCase):
    def test_distinct_schema_replays_raw_records_and_freezes_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, _, _, _, command = fixture(root)
            with patch.object(sssp_inputs.capsule, "verify", return_value=(packet, {})) as verify, \
                    patch.object(sssp_inputs.capsule, "command", return_value=command):
                execution, manifest = sssp_inputs.completed(root)
            verify.assert_called_once_with(root)
            self.assertEqual(manifest["algorithm"], "weighted_sssp")
            self.assertEqual(execution["status"], sssp_inputs.delivery.PASS)
            self.assertEqual(len(manifest["pins"]), 12)
            self.assertIn(identity(root / "preflight/thread_execute.resources.json"), manifest["pins"])

    def test_changed_contract_or_raw_records_never_reach_checkpoint(self):
        for damage in ("status", "oom", "clock", "host", "capsule", "parent", "command",
                       "raw_link", "raw_probe", "budget", "timeout", "closure"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                packet, manifest, execution, probes, command = fixture(root)
                if damage == "status": execution["status"] = "ROUTING_NOT_BOARD_ADMISSION"
                if damage == "oom": execution["memory_events_after"] = "oom 1\noom_kill 0\noom_group_kill 0\n"
                if damage == "clock": manifest["clock_mhz"] = 149
                if damage == "host": execution["host"] = "different-machine"
                if damage == "capsule": execution["capsule"] = {}
                if damage == "parent": manifest["parent"] = {}
                if damage == "command": manifest["command"] = ["other-command"]
                if damage == "budget": execution["route"]["reserve_gib"] = 0
                if damage == "timeout": execution["route"]["timeout_seconds"] = 0
                if damage == "closure": manifest["pins"] = manifest["pins"][:-1]
                write(root / "manifest.json", manifest)
                execution["manifest"] = identity(root / "manifest.json")
                write(root / "execution.json", execution)
                if damage == "raw_link": write(root / "route.resources.json", {})
                if damage == "raw_probe": write(root / "preflight/thread_execute.resources.json", {})
                with patch.object(sssp_inputs.capsule, "verify", return_value=(packet, {})), \
                        patch.object(sssp_inputs.capsule, "command", return_value=command), \
                        self.assertRaises(ValueError):
                    sssp_inputs.completed(root)

    def test_explicit_owner_is_not_inferred_from_failed_validation(self):
        with patch.object(inputs.artifacts, "completed") as algorithm, \
                patch.object(inputs.sssp_inputs, "completed", side_effect=ValueError("bad remote")) as remote, \
                patch.object(inputs, "service_state", return_value={}), \
                patch.object(inputs, "route_finished", return_value=True):
            with self.assertRaises(ValueError):
                inputs.admit(Path("unused"), "unit.service", "0" * 32, producer_kind="remote-sssp")
            algorithm.assert_not_called()
            remote.assert_called_once()
            with self.assertRaises(ValueError):
                inputs.admit(Path("unused"), "unit.service", "0" * 32, producer_kind="auto")


if __name__ == "__main__":
    unittest.main()
