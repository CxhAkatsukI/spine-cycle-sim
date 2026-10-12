"""V3 route changes one XO, retains safe guards and never edits old attempts."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line import route as shared
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row import route, route_preparation as prep
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.validation import FLAGS
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.study import INTEGRATION_FILES
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.validation import FLAGS as OLD_FLAGS


class CrossRowRoutePreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.build, self.basis, self.study, self.host, self.integration, self.output = (
            self.root / name for name in ("build", "basis", "study", "host", "integration", "output"))
        for path in (self.build, self.basis, self.study / "production", self.host / "candidate/sssp", self.integration):
            path.mkdir(parents=True)
        self.compiler, self.platform = self.root / "v++", self.root / "platform.xpfm"
        for path in (self.compiler, self.platform):
            path.write_text("pinned tool/platform")
        self.reference = self.root / "whole-line.xo"
        self.candidate = self.study / "production/adapter.hw.xo"
        for path, flags in ((self.reference, OLD_FLAGS), (self.candidate, FLAGS)):
            xml = ET.Element("root")
            kernel = ET.SubElement(xml, "kernel", name="pma_to_regraph_adapter", hwControlProtocol="ap_ctrl_chain",
                                   compileOptions=" ".join(f"-D{k}={v}" for k, v in flags.items()))
            ET.SubElement(ET.SubElement(kernel, "ports"), "port", name="GMEM0", dataWidth="512")
            ET.SubElement(ET.SubElement(kernel, "args"), "arg", name="pma0", id="0")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("adapter/kernel.xml", ET.tostring(xml))
        self.xos = [self.reference, *[self.build / f"original{i}.xo" for i in range(10)]]
        for path in self.xos[1:]:
            path.write_bytes(b"frozen downstream")
        self.config = self.basis / "link.cfg"
        self.config.write_text(f"platform={self.platform}\n" + "".join(f"{key}=/old/{key}\n" for key in (
            "messageDb", "temp_dir", "report_dir", "log_dir", "remote_ip_cache"))
            + "[connectivity]\nnk=adapter:4\nsp=a:HBM[0:22]\nsp=b:HBM[23]\n")
        self.original_command = [str(self.compiler), "--target", "hw", "--link", "--kernel_frequency", "150",
                                 "--config", str(self.config), "-o", str(self.basis / "candidate.hw.xclbin"),
                                 *map(str, self.xos), "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
        (self.build / "link_command.sh").write_text("frozen original command")
        names = (*INTEGRATION_FILES, "kernels/pma_to_regraph_adapter/cross_row_pipeline.hpp",
                 "scripts/check_pma_adapter_cross_row.sh")
        pins = []
        for name in names:
            path = self.integration / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("production source")
            pins.append(identity(path))
        for path in (self.study, self.host):
            (path / "manifest.json").write_text(json.dumps({"pins": pins}))
            (path / "results.json").write_text("{}")
        self.native_host = self.host / "candidate/sssp/sharded_k4_sssp_native_host"
        self.native_host.write_bytes(b"padded host")
        self.host_manifest = self.native_host.parent / "manifest.txt"
        self.host_manifest.write_text(f"HOST={self.native_host}\nROW_LINE_READ=1\nALGORITHM=weighted_sssp\nPIPELINE_MODE=sharded-k4\n")
        interface = prep.require_xos(self.reference, self.candidate)["interface"]
        basis = {"claim": prep.BASIS_CLAIM, "status": "PREPARED_NOT_ROUTED", "command": self.original_command,
                 "FPGA_timing_admitted": False, "A4_comparison_complete": False, "clock_mhz": 150,
                 "synth_jobs": 2, "impl_jobs": 2, "tree_memory_gib": 40, "reserve_gib": 16,
                 "timeout_seconds": 14400, "candidate_xo": identity(self.reference), "padded_host": identity(self.native_host),
                 "adapter_interface": interface, "row_memory_contract": "padded64B",
                 "pins": [identity(path) for path in (
                     self.build / "link_command.sh", self.config, *self.xos, self.compiler, self.platform)]}
        self.basis_file = self.basis / "manifest.json"
        self.basis_file.write_text(json.dumps(basis))
        for name, value in (("BASIS_SHA", identity(self.basis_file)["sha256"]),
                            ("REFERENCE_SHA", identity(self.reference)["sha256"]),
                            ("TARGET", {"candidate_adapter_xo_sha256": identity(self.candidate)["sha256"]}),
                            ("COMPILER", self.compiler), ("PLATFORM", self.platform)):
            self.mock(name, new=value)
        self.mock("recheck", return_value={"xo": identity(self.candidate)})
        self.mock("recheck_host", return_value={"hardware_executed": False})

    def mock(self, name, **kwargs):
        mock = patch.object(prep, name, **kwargs)
        self.addCleanup(mock.stop)
        return mock.start()

    def prepare(self):
        return prep.prepare(self.build, self.basis, self.study, self.host, self.integration, self.output)

    def test_exact_single_replacement_sources_host_and_unchanged_limits(self):
        before = self.basis_file.read_bytes()
        result = self.prepare()
        expected = [str(self.candidate) if value == str(self.reference) else value for value in self.original_command]
        expected[expected.index("--config") + 1] = str(self.output / "link.cfg")
        expected[expected.index("-o") + 1] = str(self.output / "candidate.hw.xclbin")
        self.assertEqual(result["command"], expected)
        self.assertEqual(result["replacement_flags"], FLAGS)
        self.assertEqual(result["candidate_xo"], identity(self.candidate))
        self.assertEqual(result["padded_host"], identity(self.native_host))
        self.assertEqual(self.config.read_text().split("[connectivity]")[1],
                         (self.output / "link.cfg").read_text().split("[connectivity]")[1])
        self.assertEqual([result[key] for key in ("tree_memory_gib", "reserve_gib", "timeout_seconds")], [40, 16, 14400])
        self.assertFalse(result["FPGA_timing_admitted"])
        self.assertFalse(result["A4_comparison_complete"])
        self.assertEqual(self.basis_file.read_bytes(), before)
        for pin in result["pins"]:
            self.assertEqual(pin, identity(Path(pin["path"])))
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_changed_inputs_are_rejected_before_output_creation(self):
        for name in ("basis", "config", "kernel", "candidate", "source", "host", "host_flag", "platform", "compiler"):
            with self.subTest(name=name):
                case = CrossRowRoutePreparationTests()
                case.setUp()
                try:
                    path = {"basis": case.basis_file, "config": case.config, "kernel": case.xos[-1],
                            "candidate": case.candidate, "source": case.integration / INTEGRATION_FILES[0],
                            "host": case.native_host, "host_flag": case.host_manifest,
                            "platform": case.platform, "compiler": case.compiler}[name]
                    path.write_text("changed")
                    with self.assertRaises((ValueError, KeyError)):
                        case.prepare()
                    self.assertFalse(case.output.exists())
                finally:
                    case.doCleanups()

    def test_failed_prerequisite_and_missing_v3_source_rejected(self):
        with patch.object(prep, "recheck", side_effect=ValueError("failed RTL")):
            with self.assertRaisesRegex(ValueError, "failed RTL"):
                self.prepare()
        self.assertFalse(self.output.exists())
        for path in (self.study, self.host):
            manifest = json.loads((path / "manifest.json").read_text())
            manifest["pins"] = [pin for pin in manifest["pins"] if not pin["path"].endswith("cross_row_pipeline.hpp")]
            (path / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "V3-specific"):
            self.prepare()
        self.assertFalse(self.output.exists())


class CrossRowRouteRunnerTests(unittest.TestCase):
    def test_delegates_to_the_unchanged_environment_and_memory_owner(self):
        paths = [Path("/" + name) for name in ("build", "basis", "study", "host", "integration", "output")]
        manifest = {"claim": prep.CLAIM}
        with patch.object(route, "prepare", return_value=manifest) as prepare, patch.object(route, "run_prepared") as runner:
            route.run(*paths, requested=True)
        prepare.assert_called_once_with(*paths)
        runner.assert_called_once_with(paths[0], paths[-1], manifest, requested=True)
        self.assertIs(route.run_prepared, shared.run_prepared)

    def test_fresh_path_failure_does_not_enter_the_runner(self):
        with patch.object(route, "prepare", side_effect=FileExistsError), patch.object(route, "run_prepared") as runner:
            with self.assertRaises(FileExistsError):
                route.run(*[Path("/old")] * 6, requested=True)
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
