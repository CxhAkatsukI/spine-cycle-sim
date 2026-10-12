"""Whole-line route binds both production gates and never bypasses safe admission."""

import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line import route, route_preparation as preparation
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.study import INTEGRATION_FILES
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.validation import BASE_FLAGS, FLAGS


class RoutePreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.build, self.study, self.host, self.integration, self.output = (
            self.root / name for name in ("build", "study", "host", "integration", "route"))
        for directory in (self.build, self.study / "production", self.host / "candidate/sssp", self.integration):
            directory.mkdir(parents=True)
        self.xos = [self.build / "pma_to_regraph_adapter.hw.xo", *[self.build / f"other{i}.xo" for i in range(10)]]
        self.reference = self.root / "reference.xo"
        self.candidate = self.study / "production/adapter.hw.xo"
        for path, flags in ((self.xos[0], {}), (self.reference, BASE_FLAGS), (self.candidate, FLAGS)):
            xml = ET.Element("root")
            kernel = ET.SubElement(xml, "kernel", name="pma_to_regraph_adapter", hwControlProtocol="ap_ctrl_chain",
                                   compileOptions=" ".join(f"-D{k}={v}" for k, v in flags.items()))
            ET.SubElement(ET.SubElement(kernel, "ports"), "port", name="GMEM0", dataWidth="512")
            ET.SubElement(ET.SubElement(kernel, "args"), "arg", name="pma0", id="0")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("adapter/kernel.xml", ET.tostring(xml))
        for path in self.xos[1:]:
            path.write_bytes(b"unchanged original kernel")
        self.config = self.build / "link.cfg"
        self.topology = "[connectivity]\nnk=adapter:4\nnk=gather:4\nsp=a:HBM[0:22]\nsp=b:HBM[23]\n"
        self.config.write_text(f"platform={preparation.PLATFORM}\n" + "".join(f"{key}=/old/{key}\n" for key in (
            "messageDb", "temp_dir", "report_dir", "log_dir", "remote_ip_cache")) + self.topology)
        command = ["v++", "--target", "hw", "--link", "--kernel_frequency", "150", "--config", str(self.config),
                   "-o", str(self.build / "old.xclbin"), *map(str, self.xos)]
        self.command = self.build / "link_command.sh"
        self.command.write_text(shlex.join(command) + "\n")
        self.historical = self.root / "historical.json"
        self.historical.write_text(json.dumps({"pins": [identity(path) for path in (
            self.command, self.config, *self.xos)]}))
        pins = []
        for name in INTEGRATION_FILES:
            path = self.integration / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("reviewed production source")
            pins.append(identity(path))
        self.study_manifest = {"pins": pins, "reference": identity(self.reference),
                               "route_manifest": identity(self.historical)}
        (self.study / "manifest.json").write_text(json.dumps(self.study_manifest))
        (self.host / "manifest.json").write_text(json.dumps({"pins": pins}))
        for directory in (self.study, self.host):
            (directory / "results.json").write_text("{}")
        self.native_host = self.host / "candidate/sssp/sharded_k4_sssp_native_host"
        self.native_host.write_bytes(b"checked padded host")
        self.host_manifest = self.host / "candidate/sssp/manifest.txt"
        self.host_manifest.write_text(f"HOST={self.native_host}\nROW_LINE_READ=1\nALGORITHM=weighted_sssp\nPIPELINE_MODE=sharded-k4\n")
        for name, result in (("recheck", {"xo": identity(self.candidate)}), ("recheck_host", {"hardware_executed": False})):
            mock = patch.object(preparation, name, return_value=result)
            mock.start()
            self.addCleanup(mock.stop)

    def prepare(self):
        return preparation.prepare(self.build, self.study, self.host, self.integration, self.output)

    def test_exact_single_replacement_and_padded_host_binding(self):
        manifest = self.prepare()
        self.assertEqual(manifest["candidate_xo"], identity(self.candidate))
        self.assertEqual(manifest["padded_host"], identity(self.native_host))
        self.assertEqual(manifest["replacement_flags"], FLAGS)
        self.assertEqual([arg for arg in manifest["command"] if arg.endswith(".xo")],
                         [str(self.candidate), *map(str, self.xos[1:])])
        self.assertEqual((self.output / "link.cfg").read_text().split("[connectivity]")[1],
                         self.topology.split("[connectivity]")[1])
        self.assertEqual((manifest["tree_memory_gib"], manifest["reserve_gib"], manifest["timeout_seconds"]), (40, 16, 14400))
        self.assertFalse(manifest["FPGA_timing_admitted"])
        self.assertFalse(manifest["A4_comparison_complete"])
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_changed_source_wrong_checkout_host_or_old_kernel_fail_before_output(self):
        cases = ("source", "checkout", "host", "kernel", "config", "candidate")
        # Each subtest creates its own fixtures because the prerequisite identities are immutable.
        for case in cases:
            with self.subTest(case=case):
                test = RoutePreparationTests("test_exact_single_replacement_and_padded_host_binding")
                test.setUp()
                try:
                    if case == "source":
                        (test.integration / INTEGRATION_FILES[0]).write_text("changed HLS")
                    elif case == "checkout":
                        test.integration = test.root / "another_checkout"
                    elif case == "host":
                        test.host_manifest.write_text(test.host_manifest.read_text().replace("ROW_LINE_READ=1", "ROW_LINE_READ=0"))
                    elif case == "kernel":
                        test.xos[-1].write_bytes(b"different downstream")
                    elif case == "config":
                        test.config.write_text(test.config.read_text().replace("HBM[23]", "HBM[22]"))
                    else:
                        test.candidate.write_bytes(b"different XO")
                    with self.assertRaises(ValueError):
                        test.prepare()
                    self.assertFalse(test.output.exists())
                finally:
                    test.doCleanups()


class RouteRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "route"
        self.input = self.root / "input"
        self.input.write_text("frozen")
        self.environment = {"PATH": "/usr/bin"}
        self.contract = {"contract": "explicit", "pins": [identity(self.input)]}
        self.mock("prepare", side_effect=self.prepare_fixture)
        self.mock("reconstruct", return_value=(self.environment, self.contract))
        self.preflight = self.mock("preflight", side_effect=self.preflight_fixture)
        self.admit = self.mock("admit", return_value={"status": "MEMORY_ADMITTED_NOT_STARTED", "route_started": False})
        self.execute = self.mock("execute", return_value={"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD"})

    def mock(self, name, **kwargs):
        patcher = patch.object(route, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def prepare_fixture(self, build, study, host, integration, output):
        output.mkdir()
        manifest = {"pins": [identity(self.input)], "command": ["v++"]}
        (output / "manifest.json").write_text(json.dumps(manifest))
        return manifest

    def preflight_fixture(self, output, environment, contract):
        directory = output / "preflight"
        directory.mkdir()
        (directory / "results.json").write_text('{"status":"PREFLIGHT_PASS_NOT_ROUTED"}')

    def run_route(self):
        return route.run(self.root, self.root, self.root, self.root, self.output, requested=True)

    def test_refusal_does_not_launch(self):
        self.admit.return_value = {"status": "ADMISSION_REJECTED_NOT_STARTED", "route_started": False}
        result = self.run_route()
        self.assertEqual(result["exit_code"], 2)
        self.execute.assert_not_called()
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertIn(identity(self.output / "preflight/results.json"), manifest["pins"])

    def test_explicit_environment_passed_and_link_not_timing_admitted(self):
        result = self.run_route()
        self.assertEqual(result["status"], "LINK_PASS_AWAITING_TIMING_AND_BOARD")
        self.assertEqual(self.execute.call_args.args[2:], (self.environment, self.contract))

    def test_failed_preflight_cannot_launch(self):
        self.preflight.side_effect = RuntimeError("preflight failed")
        result = self.run_route()
        self.assertEqual((result["stage"], result["exit_code"]), ("preflight", 1))
        self.admit.assert_not_called()
        self.execute.assert_not_called()

    def test_failed_link_and_existing_directory_are_retained(self):
        self.execute.return_value = {"status": "LINK_FAILED"}
        result = self.run_route()
        self.assertEqual(result["exit_code"], 1)
        failure = self.output / "failure.json"
        self.assertEqual(json.loads(failure.read_text()), result)
        with self.assertRaises(FileExistsError):
            self.run_route()
        self.assertEqual(json.loads(failure.read_text()), result)


if __name__ == "__main__":
    unittest.main()
