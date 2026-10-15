"""Admission fails closed; no small test needs vendor tools or large allocations."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import (
    admission, containment, preparation, supervisor)


class ConcurrentAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.proc = self.root / "proc"
        self.groups = self.root / "cgroups"
        self.groups.mkdir()
        self.own = self.groups / "route"
        self.policy = {"tree_memory_gib": 40, "reserve_gib": 24,
                       "allow_bounded_builds": True, "background_memory_gib": 6}

    def process(self, pid, name="search", limit="8589934592", swap="0"):
        process = self.proc / str(pid)
        process.mkdir(parents=True)
        (process / "cgroup").write_text(f"0::/{name}\n")
        directory = self.groups / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "memory.max").write_text(limit)
        (directory / "memory.swap.max").write_text(swap)
        return directory

    def inspect(self, rows):
        return admission.reservations(rows, self.own, proc=self.proc, root=self.groups)

    def test_two_processes_share_one_reserved_scope(self):
        self.process(1)
        self.process(2)
        rows = self.inspect(["1 vitis_hls", "2 vitis_hls"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pids"], [1, 2])
        self.assertEqual(admission.required_bytes(self.policy, rows), 78 * containment.GIB)
        self.assertTrue(admission.eligible(78 * containment.GIB, rows, self.policy))
        self.assertFalse(admission.eligible(77 * containment.GIB, rows, self.policy))

    def test_shared_bounded_parent_not_reserved_twice(self):
        self.process(1, "shared", str(12 * containment.GIB))
        self.process(2, "shared/child", str(8 * containment.GIB))
        rows = self.inspect(["1 vivado", "2 vitis_hls"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["memory_max_bytes"], 12 * containment.GIB)

    def test_own_scope_and_exited_processes_are_not_competitors(self):
        self.process(1, "route", str(40 * containment.GIB))
        self.assertEqual(self.inspect(["1 vivado", "9 vitis_hls"]), [])

    def test_unbounded_swapping_and_missing_limits_reject(self):
        for limit, swap in (("max", "0"), ("0", "0"), ("8589934592", "max")):
            with self.subTest(limit=limit, swap=swap):
                directory = self.process(1, limit=limit, swap=swap)
                rows = self.inspect(["1 vitis_hls"])
                self.assertFalse(admission.eligible(200 * containment.GIB, rows, self.policy))
                (self.proc / "1/cgroup").unlink()
                (self.proc / "1").rmdir()
        (directory / "memory.max").unlink()
        self.process(2, "different")
        (self.groups / "different/memory.max").unlink()
        self.assertFalse(admission.eligible(200 * containment.GIB,
                                          self.inspect(["2 vivado"]), self.policy))

    def test_unsafe_membership_and_invalid_background_reject(self):
        self.process(1)
        (self.proc / "1/cgroup").write_text("0::/../outside\n")
        self.assertFalse(admission.eligible(200 * containment.GIB, self.inspect(["1 vivado"]), self.policy))
        for value in (-1, 41, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                admission.required_bytes({**self.policy, "background_memory_gib": value}, [])


class HardwareSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.policy = {"tree_memory_gib": 40, "reserve_gib": 24,
                       "timeout_seconds": 21600, "queue_timeout_seconds": 86400, "pins": []}
        self.cgroup = self.root / "cgroup"
        self.cgroup.mkdir()
        for key, value in {"memory.max": str(40 * containment.GIB),
                "memory.high": str(36 * containment.GIB), "memory.swap.max": "0",
                "memory.oom.group": "1", "memory.events": "oom 0\noom_kill 0\n"}.items():
            (self.cgroup / key).write_text(value)

    def test_hard_containment_verified_and_unbounded_modes_rejected(self):
        self.assertEqual(containment.verify(self.cgroup)["path"], str(self.cgroup))
        for key, values in {"memory.max": ("max", str(41 * containment.GIB), "0"),
                "memory.high": ("max", str(37 * containment.GIB), "0"),
                "memory.swap.max": ("max", "1024"), "memory.oom.group": ("0",)}.items():
            original = (self.cgroup / key).read_text()
            for value in values:
                with self.subTest(key=key, value=value):
                    (self.cgroup / key).write_text(value)
                    with self.assertRaises(ValueError):
                        containment.verify(self.cgroup)
            (self.cgroup / key).write_text(original)

    def test_gate_uses_available_not_free_and_requires_no_other_builds(self):
        self.assertFalse(supervisor.eligible(63 * containment.GIB, [], self.policy))
        self.assertTrue(supervisor.eligible(64 * containment.GIB, [], self.policy))
        self.assertFalse(supervisor.eligible(128 * containment.GIB, ["123 vivado"], self.policy))

    def test_changed_pin_rejected(self):
        path = self.root / "input.xo"
        path.write_bytes(b"frozen")
        manifest = {"pins": [identity(path)]}
        supervisor.unchanged(manifest)
        path.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            supervisor.unchanged(manifest)

    def test_low_memory_never_executes_and_queue_times_out(self):
        output = self.root / "attempt"
        output.mkdir()
        (output / "manifest.json").write_text(json.dumps(self.policy))
        with patch.object(supervisor, "current", return_value=self.cgroup), \
                patch.object(supervisor, "available_memory_bytes", return_value=54 * containment.GIB), \
                patch.object(supervisor, "other_builds", return_value=[]), \
                patch.object(supervisor.time, "monotonic", side_effect=[0, 86401]), \
                patch.object(supervisor.Path, "home", return_value=self.root), \
                patch.object(supervisor, "execute") as execute:
            result = supervisor.run(self.root / "build", output)
        self.assertEqual(result["status"], "QUEUE_TIMEOUT_NOT_STARTED")
        self.assertEqual(json.loads((output / "execution.json").read_text())["status"], result["status"])
        self.assertFalse(result["route_started"])
        execute.assert_not_called()

    def test_stable_gate_precedes_execution_and_existing_attempt_rejected(self):
        output = self.root / "attempt"
        output.mkdir()
        (output / "manifest.json").write_text(json.dumps(self.policy))
        (output / "environment.json").write_text("{}")
        with patch.object(supervisor, "current", return_value=self.cgroup), \
                patch.object(supervisor, "available_memory_bytes", side_effect=[70, 54] + [70] * 8) as memory, \
                patch.object(supervisor, "other_builds", return_value=[]), \
                patch.object(supervisor, "eligible", side_effect=lambda available, builds, manifest: available == 70), \
                patch.object(supervisor.time, "sleep"), \
                patch.object(supervisor.Path, "home", return_value=self.root), \
                patch.object(supervisor, "reconstruct", return_value=({}, {})), \
                patch.object(supervisor, "execute", return_value={"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD"}) as execute:
            result = supervisor.run(self.root / "build", output)
        self.assertEqual(memory.call_count, 10)
        self.assertTrue(result["route_started"])
        execute.assert_called_once()
        with self.assertRaises(FileExistsError):
            supervisor.run(self.root / "build", output)

    def test_bounded_competing_tool_does_not_serialize_route(self):
        output = self.root / "concurrent"
        output.mkdir()
        policy = {**self.policy, "allow_bounded_builds": True, "background_memory_gib": 6}
        (output / "manifest.json").write_text(json.dumps(policy))
        (output / "environment.json").write_text("{}")
        budgets = [{"cgroup": "/search", "bounded": True, "memory_max_bytes": 8 * containment.GIB}]
        with patch.object(supervisor, "current", return_value=self.cgroup), \
                patch.object(supervisor, "available_memory_bytes", return_value=100 * containment.GIB), \
                patch.object(supervisor, "other_builds", return_value=["123 vitis_hls"]), \
                patch.object(supervisor, "reservations", return_value=budgets), \
                patch.object(supervisor.time, "sleep"), \
                patch.object(supervisor.Path, "home", return_value=self.root), \
                patch.object(supervisor, "reconstruct", return_value=({}, {})), \
                patch.object(supervisor, "execute", return_value={"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD"}) as execute:
            result = supervisor.run(self.root / "build", output)
        self.assertTrue(result["route_started"])
        execute.assert_called_once()

    def test_process_inspection_errors_fail_closed(self):
        with patch.object(containment.subprocess, "run") as run:
            run.return_value.returncode = 2
            run.return_value.stderr = "error"
            with self.assertRaises(RuntimeError):
                containment.other_builds()


class LinkInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.compiler, self.platform = root / "v++", root / "platform.xpfm"
        self.xos = [root / f"kernel{i}.xo" for i in range(11)]
        self.config, self.host, self.candidate = root / "link.cfg", root / "host", root / "candidate.xo"
        for path in [self.compiler, self.platform, self.config, self.host, self.candidate, *self.xos]:
            path.write_bytes(b"frozen")
        self.manifest = {"status": "PREPARED_NOT_ROUTED", "FPGA_timing_admitted": False,
            "candidate_xo": identity(self.xos[0]), "padded_host": identity(self.host),
            "adapter_interface": {"test": "interface"},
            "pins": [identity(path) for path in [self.config, *self.xos, self.compiler, self.platform, self.host]],
            "command": [str(self.compiler), "--target", "hw", "--link", "--kernel_frequency", "150",
                "--config", str(self.config), "-o", str(root / "result.xclbin"), *map(str, self.xos),
                "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]}
        flags = {"GRASU_REGRAPH_" + key: value for key, value in {
            "WEIGHTED_PMA": "1", "SHARDED_PMA": "1", "SHARE_ALL_MEMORY_PORTS": "1",
            "ROW_PREFETCH": "1", "STOP_AFTER_LAST": "1", "SKIP_EMPTY_SEGMENT": "1", "ROW_LINE_READ": "1",
            "CROSS_ROW_PIPELINE": "1", "DIRECTORY_TILE_ROWS": "1024", "PACKET_PIPELINE": "1",
            "BANK_STREAM": "1", "BANK_FIFO_LINES": "256"}.items()}
        for name, value in (("COMPILER", self.compiler), ("PLATFORM", self.platform)):
            mock = patch.object(preparation, name, value)
            self.addCleanup(mock.stop)
            mock.start()
        mock = patch.object(preparation, "adapter_interface", return_value=({"test": "interface"}, flags))
        self.addCleanup(mock.stop)
        self.interface = mock.start()

    def test_exact_eleven_inputs_and_no_concurrency_or_clock_changes(self):
        command, config, xos = preparation.link_inputs(self.manifest, self.candidate)
        self.assertEqual(command, self.manifest["command"])
        self.assertEqual(config, self.config)
        self.assertEqual(xos, self.xos)
        for flag in ("--target", "--kernel_frequency", "--vivado.synth.jobs", "--vivado.impl.jobs"):
            changed = copy.deepcopy(self.manifest)
            changed["command"][changed["command"].index(flag) + 1] = "changed"
            with self.subTest(flag=flag), self.assertRaises(ValueError):
                preparation.link_inputs(changed, self.candidate)

    def test_modified_downstream_abi_or_selection_rejected(self):
        self.xos[-1].write_bytes(b"changed")
        with self.assertRaises(ValueError):
            preparation.link_inputs(self.manifest, self.candidate)
        self.xos[-1].write_bytes(b"frozen")
        for interface, flags in (({}, {}), ({"test": "interface"}, {})):
            self.interface.return_value = interface, flags
            with self.assertRaises(ValueError):
                preparation.link_inputs(self.manifest, self.candidate)


if __name__ == "__main__":
    unittest.main()
