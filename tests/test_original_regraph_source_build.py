import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_build import (
    configuration as config, execution, gates, snapshot,
)
from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import SECTIONS


class SourceBuildConfigurationTests(unittest.TestCase):
    def test_unique_compile_paths_and_all_six_objects_in_link(self):
        output, source = Path("/run/fresh"), Path("/run/fresh/source")
        self.assertEqual(sum(count for _, count in config.KERNELS.values()), 18)
        directories = set()
        for name in config.KERNELS:
            command = config.compile_command(source, output, name)
            self.assertEqual(command[command.index("--kernel") + 1], name)
            self.assertEqual(command[command.index("--kernel_frequency") + 1], "150")
            self.assertEqual(command[command.index("-o") + 1], str(output / "xo" / (name + ".hw.xo")))
            directories.add(command[command.index("--temp_dir") + 1])
            for key, value in config.DEFINES.items():
                self.assertIn(f"-D{key}={value}", command)
        self.assertEqual(len(directories), 6)
        link = config.link_command(source, output)
        self.assertEqual(link[-6:], [str(output / "xo" / (name + ".hw.xo")) for name in config.KERNELS])
        self.assertEqual(link[link.index("--vivado.impl.jobs") + 1], "2")
        self.assertTrue(config.POLICY["allow_bounded_builds"])
        self.assertEqual(sum(config.POLICY[key] for key in (
            "tree_memory_gib", "reserve_gib", "background_memory_gib")), 72)

    def test_mergers_are_free_running_stream_only_author_abi(self):
        for name in config.KERNELS:
            expected = "ap_ctrl_none" if "Merger" in name else "ap_ctrl_chain"
            self.assertEqual(config.control_protocol(name), expected)
            if "Merger" in name:
                self.assertFalse(any("paritions" in arg for arg in config.argument_names(name)))
                self.assertEqual(len(config.argument_names(name)), 12 if "Little" in name else 4)
        for function in (config.control_protocol, config.argument_names):
            with self.assertRaises(ValueError):
                function("unknown")


class SourceBuildGateTests(unittest.TestCase):
    def xo(self, path, name, changes=None, mutate=None, extra=False):
        root = ET.Element("root")
        attributes = {"name": name, "hwControlProtocol": config.control_protocol(name),
                      "compileOptions": " ".join(f"-D{key}={value}" for key, value in config.DEFINES.items())}
        attributes.update(changes or {})
        kernel = ET.SubElement(root, "kernel", attributes)
        args = ET.SubElement(kernel, "args")
        for index, arg in enumerate(config.argument_names(name)):
            ET.SubElement(args, "arg", {"id": str(index), "name": arg})
        if mutate:
            mutate(kernel)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(name + "/kernel.xml", ET.tostring(root))
            if extra:
                archive.writestr("other/kernel.xml", ET.tostring(root))

    def test_exact_abi_and_macros_for_each_author_kernel(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in config.KERNELS:
                path = Path(directory) / (name + ".xo")
                self.xo(path, name)
                result = gates.inspect_xo(path, name)
                self.assertEqual(result["control"], config.control_protocol(name))
                self.assertEqual(result["defines"]["LITTLE_KERNEL_NUM"], "11")

    def test_bad_name_control_argument_order_and_duplicate_xml_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kernel.xo"
            name = "kernelApply"
            for changes in ({"name": "other"}, {"hwControlProtocol": "ap_ctrl_hs"}):
                self.xo(path, name, changes)
                with self.assertRaises(ValueError):
                    gates.inspect_xo(path, name)
            for mutate in (lambda kernel: kernel.find("args/arg").set("id", "1"),
                           lambda kernel: kernel.find("args/arg").set("name", "other")):
                self.xo(path, name, mutate=mutate)
                with self.assertRaises(ValueError):
                    gates.inspect_xo(path, name)
            self.xo(path, name, extra=True)
            with self.assertRaises(ValueError):
                gates.inspect_xo(path, name)

    def test_missing_redefined_undefined_or_wrong_macros_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kernel.xo"
            options = " ".join(f"-D {key}={value}" for key, value in config.DEFINES.items())
            self.xo(path, "kernelApply", {"compileOptions": options})
            gates.inspect_xo(path, "kernelApply")
            for bad in (options.replace("-D LITTLE_KERNEL_NUM=11", ""),
                        options + " -DLITTLE_KERNEL_NUM=11", options + " -U LITTLE_KERNEL_NUM",
                        options.replace("LITTLE_KERNEL_NUM=11", "LITTLE_KERNEL_NUM=4")):
                self.xo(path, "kernelApply", {"compileOptions": bad})
                with self.assertRaises(ValueError):
                    gates.inspect_xo(path, "kernelApply")

    def test_hls_part_clock_and_report_multiplicity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "kernelApply_csynth.xml"
            template = "<Report><UserAssignments><Part>{}</Part><TargetClockPeriod>{}</TargetClockPeriod></UserAssignments></Report>"
            report.write_text(template.format(config.PART, 1000 / 150))
            self.assertEqual(gates.inspect_hls(root, "kernelApply")["part"], config.PART)
            for part, clock in (("other", 1000 / 150), (config.PART, 5), (config.PART, "nan")):
                report.write_text(template.format(part, clock))
                with self.assertRaises(ValueError):
                    gates.inspect_hls(root, "kernelApply")
            report.unlink()
            with self.assertRaises(ValueError):
                gates.inspect_hls(root, "kernelApply")

    def topology(self):
        kernels = sorted((f"{name}:{name}_{index}", config.control_protocol(name).upper())
                         for name, (_, count) in config.KERNELS.items() for index in range(1, count + 1))
        connections = [("kernelApply:kernelApply_1", 0, "HBM[30]")]
        for lane in range(14):
            connections.extend(("kernelHBMWrapper:kernelHBMWrapper_1", lane + offset, f"HBM[{2 * lane + 1}]")
                               for offset in (0, 14))
            name, index = ("littleKernelScatterGather", lane + 1) if lane < 11 else ("bigKernelScatterGather", lane - 10)
            connections.append((f"{name}:{name}_{index}", 0, f"HBM[{2 * lane}]"))
        return {"kernels": kernels, "clock": [("DATA", "DATA_CLK", 150)],
                "connections": sorted(connections),
                "memory": [(f"HBM[{i}]", "MEM_HBM" if i == 0 else "MEM_DRAM", "1", "0x80000") for i in range(32)]}

    def routed_fixture(self, root):
        for name in SECTIONS.values():
            (root / (name + ".json")).write_text("{}")
        timing = root / "impl_1_hw_bb_locked_timing_summary_routed.rpt"
        timing.write_text("WNS(ns) TNS TNSend TNSall WHS THS THSend THSall WPWS TPWS TPWSend TPWSall\n"
                          "-----\n0.1 0 0 100 0.01 0 0 100 0.0 0 0 100\n"
                          "All user specified timing constraints are met.\n")
        return timing

    def test_routed_clock_topology_memory_protocol_and_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timing = self.routed_fixture(root)
            topology = self.topology()
            with patch.object(gates, "normalized_topology", return_value=topology):
                result = gates.inspect_routed(root, root)
                self.assertFalse(result["board_programmed"])
                self.assertFalse(result["hardware_timing_measured"])
                self.assertFalse(result["publication_match"])
            for field, bad in (("clock", [("DATA", "DATA_CLK", 149)]),
                               ("kernels", topology["kernels"][:-1]),
                               ("connections", topology["connections"][:-1]),
                               ("memory", [(tag, kind, "0", size) for tag, kind, used, size in topology["memory"]]),
                               ("memory", [(tag, kind, used, "0x40000") for tag, kind, used, size in topology["memory"]])):
                changed = {**topology, field: bad}
                with patch.object(gates, "normalized_topology", return_value=changed), self.assertRaises(ValueError):
                    gates.inspect_routed(root, root)
            changed = copy.deepcopy(topology)
            changed["kernels"][0] = (changed["kernels"][0][0], "AP_CTRL_HS")
            with patch.object(gates, "normalized_topology", return_value=changed), self.assertRaises(ValueError):
                gates.inspect_routed(root, root)
            timing.write_text(timing.read_text().replace("0.1 0 0 100", "-0.1 -1 1 100"))
            with patch.object(gates, "normalized_topology", return_value=topology), self.assertRaises(ValueError):
                gates.inspect_routed(root, root)


class SourceBuildSnapshotTests(unittest.TestCase):
    def test_snapshot_allows_only_declared_author_generated_outputs(self):
        for mode in ("allowed", "algorithm_edit", "added_file", "source_drift"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                upstream, output = root / "upstream", root / "run"
                upstream.mkdir()
                output.mkdir()
                generated = snapshot.GENERATED_FILES[0]
                names = [generated, "algorithm.cpp"]
                for name in names:
                    path = upstream / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("author source")
                pin_file = root / "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json"
                pin_file.parent.mkdir(parents=True)
                pin_file.write_text("{}")

                def generate(command, destination, prefix, **kwargs):
                    self.assertEqual(command[-4:], ["11", "3", "true", "false"])
                    target = {"allowed": destination / generated,
                              "algorithm_edit": destination / "algorithm.cpp",
                              "added_file": destination / "helper.h",
                              "source_drift": upstream / "algorithm.cpp"}[mode]
                    target.write_text("changed")
                    return {"exit_code": 0, "timed_out": False}

                with patch.object(snapshot, "read_pins", return_value={"regraph": {}}), \
                        patch.object(snapshot.sources, "review", return_value={"revision": "pinned"}), \
                        patch.object(snapshot, "tracked_files", return_value=names), \
                        patch.object(snapshot, "run_bounded", side_effect=generate):
                    if mode == "allowed":
                        prepared = snapshot.prepare(root, upstream, output)
                        self.assertFalse(prepared["device_algorithm_edits"])
                        self.assertEqual(prepared["changed_generated_files"], [generated])
                        self.assertFalse((output / "source/helper.h").exists())
                    else:
                        with self.assertRaises(ValueError):
                            snapshot.prepare(root, upstream, output)

    def test_missing_or_changed_pin_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "frozen.py"
            path.write_text("frozen")
            pin = artifact.identity(path)
            snapshot.unchanged([pin])
            path.write_text("changed")
            with self.assertRaises(ValueError):
                snapshot.unchanged([pin])

    def test_duplicate_unsafe_and_symlinked_tracked_files_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "file").write_text("tracked")
            (root / "link").symlink_to(root, target_is_directory=True)
            for names in (b"", b"file\0file\0", b"../file\0", b"/file\0", b"link/file\0"):
                with patch.object(snapshot.subprocess, "check_output", return_value=names), self.assertRaises(ValueError):
                    snapshot.tracked_files(root)
            with patch.object(snapshot.subprocess, "check_output", return_value=b"file\0"):
                self.assertEqual(snapshot.tracked_files(root), ["file"])

    def test_insufficient_memory_prevents_tools_without_waiting_for_peers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory.events").write_text("oom 0\noom_kill 0\n")
            with patch.object(execution, "current", return_value=root), \
                    patch.object(execution, "verify", return_value={}), \
                    patch.object(execution, "Lease") as lease, \
                    patch.object(execution, "available_memory_bytes", return_value=1), \
                    patch.object(execution, "other_builds", return_value=[{"peer": "running"}]), \
                    patch.object(execution, "run_link") as tool, \
                    patch.object(execution, "prerequisites") as prerequisite:
                lease.return_value.sample.return_value = {"admitted": False}
                with self.assertRaisesRegex(RuntimeError, "no tools launched"):
                    execution.run(root, root, root, root, root, root / "fresh")
                tool.assert_not_called()
                prerequisite.assert_not_called()
                lease.return_value.release.assert_called_once()
                self.assertEqual(json.loads((root / "fresh/results.json").read_text())["status"], "FAILED_RETAINED")


if __name__ == "__main__":
    unittest.main()
