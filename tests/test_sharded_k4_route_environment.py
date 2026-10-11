"""Explicit environment pinning and non-launch/failure semantics."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment import contract, probe
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment import __main__ as runner
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity


class EnvironmentContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.settings = self.root / "Vitis/2024.1/settings64.sh"
        self.settings.parent.mkdir(parents=True)
        self.leaf = self.root / "vendor.sh"
        self.leaf.write_text('export XILINX_VITIS=/vendor\n')
        self.settings.write_text("source " + str(self.leaf) + "\n")
        self.build, self.output = self.root / "build", self.root / "output"
        self.build.mkdir()
        shim = self.build / "gcc_compat/bits/gthr-default.h"
        shim.parent.mkdir(parents=True)
        shim.write_text("compatibility shim")
        for key in ("v++", "vivado", "gcc", "g++"):
            path = self.settings.parent / "bin" / key
            path.parent.mkdir(exist_ok=True)
            path.write_text("tool " + key)
        self.env = {"PATH": "/tools", "HOME": "/home/test", "LM_LICENSE_FILE": "secret"}
        lines = ["#!/usr/bin/env bash", "set -euo pipefail", "source " + str(self.settings)]
        values = {k: str(self.build / "tmp") for k in ("TMPDIR", "TMP", "TEMP")}
        values.update(contract.SEARCH_PATHS)
        values["CPLUS_INCLUDE_PATH"] = str(self.build / "gcc_compat")
        for key in ("TMPDIR", "TMP", "TEMP", "CPATH", "C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH",
                    "LIBRARY_PATH", "COMPILER_PATH"):
            suffix = "" if key in ("TMPDIR", "TMP", "TEMP") else "${" + key + ":+:${" + key + "}}"
            lines.append(f"export {key}={values[key]}{suffix}")
        lines.append("v++ --link --target hw")
        (self.build / "link_command.sh").write_text("\n".join(lines) + "\n")
        p = patch.object(contract, "SETTINGS", self.settings)
        p.start()
        self.addCleanup(p.stop)

    def capture(self):
        payload = b"PATH=/tools\0HOME=/home/test\0LM_LICENSE_FILE=secret\0PWD=/cwd\0SHLVL=1\0_=env\0"
        with patch.object(contract.subprocess, "run") as process, \
                patch.object(contract.shutil, "which", side_effect=lambda name, **_: str(self.settings.parent / "bin" / name)):
            process.return_value.stdout = payload
            result = contract.reconstruct(self.build, self.output)
            self.assertNotIn("--link", process.call_args.args[0])
            self.assertEqual(process.call_args.kwargs["env"]["PATH"], "/usr/bin:/bin")
            return result

    def test_exact_prefix_dependency_closure(self):
        paths = contract.require_prefix(self.build)
        self.assertIn(self.leaf, paths)
        self.assertIn(self.build / "gcc_compat/bits/gthr-default.h", paths)

    def test_extra_shell_command_rejected_without_execution(self):
        path = self.build / "link_command.sh"
        path.write_text(path.read_text() + "echo unreviewed\n")
        with self.assertRaisesRegex(ValueError, "prefix differs"):
            contract.require_prefix(self.build)

    def test_changed_export_rejected(self):
        path = self.build / "link_command.sh"
        path.write_text(path.read_text().replace("COMPILER_PATH=/usr/bin", "COMPILER_PATH=/elsewhere"))
        with self.assertRaises(ValueError):
            contract.require_prefix(self.build)

    def test_dynamic_settings_source_rejected(self):
        self.settings.write_text('source "$OTHER"\n')
        with self.assertRaisesRegex(ValueError, "literal source"):
            contract.require_prefix(self.build)

    def test_nested_settings_source_rejected(self):
        self.leaf.write_text("source /unlisted.sh\n")
        with self.assertRaisesRegex(ValueError, "nested settings"):
            contract.require_prefix(self.build)

    def test_clean_base_relocation_redaction_and_tools(self):
        environment, report = self.capture()
        self.assertEqual(environment["TMPDIR"], str(self.output / "tmp"))
        self.assertNotIn("PWD", environment)
        self.assertEqual(environment["COMPILER_PATH"], "/usr/bin")
        self.assertNotIn("secret", json.dumps(report))
        self.assertIn("LM_LICENSE_FILE", report["effective"]["license_value_sha256"])
        contract.require_unchanged(report, environment)

    def test_mutated_environment_rejected(self):
        environment, report = self.capture()
        environment["CPATH"] = "/wrong"
        with self.assertRaisesRegex(ValueError, "environment changed"):
            contract.require_unchanged(report, environment)

    def test_mutated_settings_rejected(self):
        environment, report = self.capture()
        self.leaf.write_text("modified")
        with self.assertRaisesRegex(ValueError, "dependency changed"):
            contract.require_unchanged(report, environment)

    def test_changed_license_rejected_without_exposing_value(self):
        environment, report = self.capture()
        environment["LM_LICENSE_FILE"] = "different secret"
        with self.assertRaisesRegex(ValueError, "environment changed"):
            contract.require_unchanged(report, environment)


class EnvironmentRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "route"
        self.input = self.root / "input"
        self.input.write_text("frozen")
        self.environment = {"PATH": "/usr/bin"}
        self.contract = {"contract": "explicit", "pins": [identity(self.input)]}
        self.prepare = self.mock("prepare", side_effect=self.prepare_fixture)
        self.mock("reconstruct", return_value=(self.environment, self.contract))
        self.preflight = self.mock("preflight", side_effect=self.probe_fixture)
        self.admit = self.mock("admit", return_value={"status": "MEMORY_ADMITTED_NOT_STARTED", "route_started": False})
        self.execute = self.mock("execute", return_value={"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD"})

    def mock(self, name, **kwargs):
        p = patch.object(runner, name, **kwargs)
        self.addCleanup(p.stop)
        return p.start()

    def prepare_fixture(self, build, production, output):
        output.mkdir()
        manifest = {"pins": [identity(self.input)], "command": ["v++"],
                    "tree_memory_gib": 40, "reserve_gib": 16, "timeout_seconds": 14400}
        atomic_write_json(output / "manifest.json", manifest)
        return manifest

    def probe_fixture(self, output, environment, report):
        path = output / "preflight/results.json"
        path.parent.mkdir()
        atomic_write_json(path, {"status": "PREFLIGHT_PASS_NOT_ROUTED"})

    def run_route(self, requested=True):
        return runner.run(self.root, self.root, self.output, requested=requested)

    def test_preflight_is_bound_before_admission(self):
        result = self.run_route(False)
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertIn(identity(self.output / "preflight/results.json"), manifest["pins"])
        self.assertIn(identity(self.output / "environment.json"), manifest["pins"])
        self.assertEqual((manifest["tree_memory_gib"], manifest["reserve_gib"]), (40, 16))
        self.assertEqual(result["exit_code"], 0)
        self.execute.assert_not_called()

    def test_memory_refusal_never_starts_route_and_is_nonzero(self):
        self.admit.return_value = {"status": "ADMISSION_REJECTED_NOT_STARTED", "route_started": False}
        result = self.run_route()
        self.assertEqual(result["exit_code"], 2)
        self.execute.assert_not_called()

    def test_preflight_failure_preserved_without_admission(self):
        self.preflight.side_effect = RuntimeError("thread compilation failed")
        result = self.run_route()
        self.assertEqual((result["stage"], result["exit_code"]), ("preflight", 1))
        self.assertFalse(result["route_started"])
        self.assertTrue((self.output / "failure.json").is_file())
        self.admit.assert_not_called()
        self.execute.assert_not_called()

    def test_execute_receives_explicit_environment(self):
        result = self.run_route()
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(self.execute.call_args.args[2:], (self.environment, self.contract))

    def test_link_failure_preserved_and_nonzero(self):
        self.execute.return_value = {"status": "LINK_FAILED", "resources": {"stop_reason": "timeout"}}
        result = self.run_route()
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(json.loads((self.output / "failure.json").read_text()), result)

    def test_existing_path_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "failure.json"
        sentinel.write_text("keep historical result")
        with self.assertRaises(FileExistsError):
            self.run_route()
        self.assertEqual(sentinel.read_text(), "keep historical result")
        self.preflight.assert_not_called()


class EnvironmentProbeTests(unittest.TestCase):
    def test_watchdog_failure_cannot_become_preflight_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            tools = {name: {"invocation": "/tools/" + name} for name in ("v++", "vivado", "gcc", "g++")}
            with patch.object(probe, "require_unchanged"), patch.object(probe, "run_link", return_value={
                    "exit_code": 0, "stop_reason": "live_memory_reserve", "cleanup_snapshot_error": None}):
                with self.assertRaises(RuntimeError):
                    probe.run(output, {}, {"tools": tools})
            result = json.loads((output / "preflight/results.json").read_text())
            self.assertEqual(result["status"], "PREFLIGHT_FAILED_NOT_ROUTED")
            self.assertEqual(len(result["commands"]), 1)


if __name__ == "__main__":
    unittest.main()
