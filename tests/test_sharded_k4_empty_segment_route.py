"""Production route preparation must preserve topology and record non-starts."""

import json
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.production import FLAGS, PLATFORM
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route import admit, prepare
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity

OWNER = "spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route"


class EmptySegmentRouteTests(unittest.TestCase):
    def fixture(self, root):
        build, production = root / "build", root / "production"
        build.mkdir()
        production.mkdir()
        xos = [build / "pma_to_regraph_adapter.hw.xo", *[build / f"other{i}.xo" for i in range(10)]]
        for path, flags in ((xos[0], {}), (production / "adapter.hw.xo", FLAGS)):
            xml = ET.Element("root")
            kernel = ET.SubElement(xml, "kernel", name="pma_to_regraph_adapter", hwControlProtocol="ap_ctrl_chain",
                                   compileOptions=" ".join(f"-D{k}={v}" for k, v in flags.items()))
            ET.SubElement(ET.SubElement(kernel, "ports"), "port", name="GMEM0", dataWidth="512")
            ET.SubElement(ET.SubElement(kernel, "args"), "arg", name="pma0", id="0")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("adapter/kernel.xml", ET.tostring(xml))
        for path in xos[1:]:
            path.write_bytes(b"other frozen kernel")
        config = build / "link.cfg"
        topology = "[connectivity]\nnk=adapter:4\nnk=gather:4\nsp=a:HBM[0:22]\nsp=b:HBM[23]\n"
        config.write_text(f"platform={PLATFORM}\n" + "".join(f"{key}=/old/{key}\n" for key in (
            "messageDb", "temp_dir", "report_dir", "log_dir", "remote_ip_cache")) + topology)
        command = ["v++", "--target", "hw", "--link", "--kernel_frequency", "150", "--config", str(config),
                   "-o", str(build / "old.xclbin"), *map(str, xos)]
        (build / "link_command.sh").write_text(shlex.join(command) + "\n")
        for path in [production / "manifest.json", production / "results.json", production / "compile.resources.json",
                     production.with_name("production_watchdog.resources.json")]:
            path.write_text("{}")
        gate = {"manifest": {"reference_xo": identity(xos[0]), "pins": []}}
        return build, production, gate, topology, xos

    def test_only_one_xo_and_output_paths_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build, production, gate, topology, xos = self.fixture(root)
            output = root / "route"
            with patch(OWNER + ".recheck", return_value=gate) as recheck:
                result = prepare(build, production, output)
            recheck.assert_called_once_with(production, current_inputs=True)
            self.assertEqual(result["status"], "PREPARED_NOT_ROUTED")
            self.assertEqual([arg for arg in result["command"] if arg.endswith(".xo")],
                             [str(production / "adapter.hw.xo"), *map(str, xos[1:])])
            self.assertEqual((output / "link.cfg").read_text().split("[connectivity]")[1],
                             topology.split("[connectivity]")[1])
            self.assertEqual((result["tree_memory_gib"], result["reserve_gib"]), (40, 16))
            with self.assertRaises(FileExistsError):
                prepare(build, production, output)

    def test_memory_refusal_is_persisted_without_launching(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build, production, gate, _, _ = self.fixture(root)
            output = root / "route"
            with patch(OWNER + ".recheck", return_value=gate):
                prepare(build, production, output)
            with patch(OWNER + ".available_memory_bytes", return_value=51 * 1024**3):
                result = admit(output)
            self.assertEqual(result["status"], "ADMISSION_REJECTED_NOT_STARTED")
            self.assertEqual(result["required_bytes"], 56 * 1024**3)
            self.assertFalse(result["route_started"])
            self.assertEqual(json.loads((output / "admission.json").read_text()), result)
            self.assertFalse((output / "route.resources.json").exists())
            with self.assertRaises(FileExistsError):
                admit(output)

    def test_changed_kernel_and_wrong_reference_refused(self):
        for failure in ("reference", "input"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                build, production, gate, _, xos = self.fixture(root)
                output = root / "route"
                if failure == "reference":
                    gate["manifest"]["reference_xo"]["sha256"] = "wrong"
                with patch(OWNER + ".recheck", return_value=gate):
                    if failure == "reference":
                        with self.assertRaises(ValueError):
                            prepare(build, production, output)
                    else:
                        prepare(build, production, output)
                        xos[-1].write_bytes(b"changed")
                        with self.assertRaises(ValueError):
                            admit(output)
                self.assertFalse((output / "admission.json").exists())


if __name__ == "__main__":
    unittest.main()
