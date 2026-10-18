"""Original-source control preparation and fail-closed build admission, not FPGA tests."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import (
    configuration as config, gates, preparation, study)


def packet(root):
    root.mkdir()
    (root / "source").mkdir()
    hashes = {}
    for name in config.SOURCE_HASHES:
        payload = ("fixture " + name).encode()
        (root / "source" / name).write_bytes(payload)
        hashes[name] = hashlib.sha256(payload).hexdigest()
    with patch.object(config, "SOURCE_HASHES", hashes):
        (root / "link.cfg").write_text(config.connectivity())
        (root / "packet.json").write_text(json.dumps(preparation.contract()))
    return hashes


def xo(path, name, *, masters=None, control="ap_ctrl_chain", width="96"):
    root = ET.Element("root")
    kernel = ET.SubElement(root, "kernel", name=name, hwControlProtocol=control)
    args = ET.SubElement(kernel, "args")
    for index, argument in enumerate(config.argument_names(name)):
        ET.SubElement(args, "arg", id=str(index), name=argument)
    ports = ET.SubElement(kernel, "ports")
    count = {"bin_search": 9, "dispatch": 0, "process_cache": 1, "process_ddr": 4}[name]
    for index in range(count if masters is None else masters):
        ET.SubElement(ports, "port", name="memory_" + str(index), mode="master", portType="addressable")
    for index in range(8 if name == "dispatch" else 1):
        ET.SubElement(ports, "port", name="stream_" + str(index), portType="stream", dataWidth=width)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(name + "/kernel.xml", ET.tostring(root))
        archive.writestr(".Xil/scratch/kernel.xml", b"not the canonical ABI")


class OriginalGraSUHardwareTests(unittest.TestCase):
    def test_connectivity_preserves_all_46_masters_and_eight_streams(self):
        lines = config.connectivity().splitlines()
        self.assertEqual(sum(row.startswith("sp=") for row in lines), 46)
        self.assertEqual(sum(row.startswith("stream_connect=") for row in lines), 8)
        self.assertEqual(sum(row.startswith("nk=") for row in lines), 4)
        self.assertEqual(sum(config.KERNELS.values()), 9)
        for index in range(1, 5):
            self.assertIn(f"sp=bin_search_{index}.row_offset_3:HBM[{index-1}]", lines)

    def test_commands_keep_original_source_and_do_not_override_geometry(self):
        compiles, link = config.commands("/vendor/v++", Path("/platform"), Path("/packet"), Path("/output"),
                                        legacy_include=Path("/vendor/Vitis_HLS/2024.1/include/etc"))
        self.assertEqual(list(compiles), list(config.KERNELS))
        for name, command in compiles.items():
            self.assertEqual(command[-1], f"/packet/source/kernel_{name}.cpp")
            self.assertIn("-D_GTHREAD_USE_COND_INIT_FUNC", command)
            self.assertIn("-I/vendor/Vitis_HLS/2024.1/include/etc", command)
            self.assertFalse(any("GRASU" in arg for arg in command))
            self.assertEqual(command[command.index("--kernel_frequency") + 1], "150")
        self.assertEqual(len([arg for arg in link if arg.endswith(".xo")]), 4)
        self.assertEqual(link[link.index("--vivado.impl.jobs") + 1], "2")

    def test_legacy_header_support_is_explicit_pinned_and_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = root / "Vitis_HLS/2024.1/include/etc"
            directory.mkdir(parents=True)
            with self.assertRaises(FileNotFoundError):
                study.legacy_headers(root)
            for name in ("ap_utils.h", "autopilot_ssdm_op.h"):
                (directory / name).write_text(name)
            found, pins = study.legacy_headers(root)
            self.assertEqual(found, directory)
            self.assertEqual([row["path"] for row in pins],
                             [str(directory / name) for name in ("ap_utils.h", "autopilot_ssdm_op.h")])
            with self.assertRaises(TypeError):
                config.commands("/vendor/v++", root, root, root)

    def test_packet_relocation_and_all_claims_remain_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "packet"
            hashes = packet(root)
            moved = root.with_name("relocated")
            root.rename(moved)
            with patch.object(config, "SOURCE_HASHES", hashes):
                self.assertEqual(len(preparation.verify(moved)), 7)
            self.assertTrue(all(preparation.contract()[key] is False for key in config.FLAGS))
            self.assertIn("not_U250", preparation.contract()["claim"])

    def test_changed_sources_connectivity_claims_and_extra_files_rejected(self):
        for damage in ("source", "connectivity", "claim", "extra", "symlink"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "packet"
                hashes = packet(root)
                if damage == "source":
                    (root / "source/kernel_config.h").write_text("changed")
                elif damage == "connectivity":
                    (root / "link.cfg").write_text("compacted")
                elif damage == "claim":
                    data = json.loads((root / "packet.json").read_text())
                    data["publication_performance_match"] = True
                    (root / "packet.json").write_text(json.dumps(data))
                elif damage == "extra":
                    (root / "unrecorded.hpp").write_text("extra")
                else:
                    (root / "alias").symlink_to(root / "source/kernel_config.h")
                with patch.object(config, "SOURCE_HASHES", hashes), self.assertRaises(ValueError):
                    preparation.verify(root)

    def test_all_canonical_xo_interfaces(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in config.KERNELS:
                path = Path(directory) / (name + ".xo")
                xo(path, name)
                self.assertEqual(gates.inspect_xo(path, name)["kernel"], name)

    def test_compacted_ports_and_changed_control_or_streams_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "search.xo"
            for options in ({"masters": 2}, {"control": "ap_ctrl_hs"}, {"width": "64"}):
                with self.subTest(options=options):
                    xo(path, "bin_search", **options)
                    with self.assertRaises(ValueError):
                        gates.inspect_xo(path, "bin_search")

    def test_hls_requires_exact_part_and_150mhz_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "bin_search_csynth.xml"
            for part, period, accepted in ((config.PART, "6.66667", True),
                    (config.PART, "5", False), ("other", "6.66667", False),
                    (config.PART, "nan", False)):
                report.write_text(f"<Report><UserAssignments><Part>{part}</Part>"
                    f"<TargetClockPeriod>{period}</TargetClockPeriod></UserAssignments></Report>")
                if accepted:
                    self.assertEqual(gates.inspect_hls(root, "bin_search")["target_clock_ns"], 6.66667)
                else:
                    with self.assertRaises(ValueError):
                        gates.inspect_hls(root, "bin_search")

    def test_wrong_packet_stops_before_environment_or_compiler(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(preparation, "verify", side_effect=ValueError("bad source")), \
                    patch.object(study.environment, "capture") as capture, \
                    patch.object(study, "run_link") as compiler, self.assertRaises(ValueError):
                study.run(root / "input", root / "output", root, root, root, root)
            capture.assert_not_called()
            compiler.assert_not_called()
            report = json.loads((root / "output/results.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertTrue(all(report[key] is False for key in config.FLAGS))


if __name__ == "__main__":
    unittest.main()
