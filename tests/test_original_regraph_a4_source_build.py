import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import admission
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_build import (
    configuration as config, execution, gates, preflight, snapshot, waiting,
)
from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import SECTIONS


class A4SourceBuildTests(unittest.TestCase):
    def test_default_configuration_and_commands_remain_11_plus_3(self):
        self.assertEqual(config.kernels(), config.KERNELS)
        self.assertEqual(config.defines(), config.DEFINES)
        self.assertEqual(config.counts(), (11, 3))
        self.assertEqual(config.binary_name(), "original_r_11l3b.hw.xclbin")
        self.assertEqual(config.routed_status(), admission.STATUS)

    def test_a4_has_four_unique_objects_seven_cus_and_no_big_compile(self):
        source, output = Path("/frozen/source"), Path("/frozen/run")
        self.assertEqual(config.counts("a4"), (4, 0))
        self.assertEqual(list(config.kernels("a4")), ["kernelApply", "kernelHBMWrapper",
                        "littleKernelScatterGather", "kernelLittleGSMerger"])
        self.assertEqual(sum(count for _, count in config.kernels("a4").values()), 7)
        self.assertEqual(config.defines("a4"), {**config.DEFINES, "KERNEL_NUM": 4,
                        "LITTLE_KERNEL_NUM": 4, "BIG_KERNEL_NUM": 0})
        for name in config.kernels("a4"):
            command = config.compile_command(source, output, name, "a4")
            for flag in ("-DLITTLE_KERNEL_NUM=4", "-DBIG_KERNEL_NUM=0", "-DKERNEL_NUM=4"):
                self.assertIn(flag, command)
            self.assertEqual(command[command.index("--kernel_frequency") + 1], "150")
        link = config.link_command(source, output, "a4")
        self.assertEqual(link[link.index("-o") + 1], str(output / "original_r_a4.hw.xclbin"))
        self.assertEqual(link[-4:], [str(output / "xo" / (name + ".hw.xo"))
                                    for name in config.kernels("a4")])
        self.assertNotEqual(config.routed_status("a4"), admission.STATUS)

    def test_a4_has_explicit_smaller_abi_and_rejects_absent_big_kernels(self):
        self.assertEqual(config.argument_names("kernelApply", "a4"),
            ["outdegree", "num_dense_paritions", "num_sparse_paritions", "arg_reg",
             "l_merged_prop_stm", "prop_write_burst_stm"])
        wrapper = config.argument_names("kernelHBMWrapper", "a4")
        self.assertEqual(wrapper[:10], [*[f"src_prop_{i}" for i in range(1, 5)],
                                       *[f"new_prop_{i}" for i in range(1, 5)],
                                       "num_dense_paritions", "num_sparse_paritions"])
        self.assertEqual(len(wrapper), 19)
        self.assertFalse(any(arg.startswith("b_") for arg in wrapper))
        self.assertEqual(len(config.argument_names("kernelLittleGSMerger", "a4")), 5)
        for function in (config.argument_names, config.control_protocol):
            with self.assertRaises(ValueError):
                function("bigKernelScatterGather", "a4")
        for topology in ("A4", "original", "4little", None, False, [], {}):
            with self.assertRaises(ValueError):
                config.counts(topology)

    def write_xo(self, path, name, topology):
        document = ET.Element("root")
        kernel = ET.SubElement(document, "kernel", {"name": name,
            "hwControlProtocol": config.control_protocol(name, topology),
            "compileOptions": " ".join(f"-D{k}={v}" for k, v in config.defines(topology).items())})
        args = ET.SubElement(kernel, "args")
        for index, name in enumerate(config.argument_names(name, topology)):
            ET.SubElement(args, "arg", {"id": str(index), "name": name})
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("export/kernel.xml", ET.tostring(document))

    def test_xo_gate_never_accepts_one_topology_as_the_other(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "kernel.xo"
            for name in config.kernels("a4"):
                self.write_xo(path, name, "a4")
                self.assertEqual(gates.inspect_xo(path, name, "a4")["defines"]["BIG_KERNEL_NUM"], "0")
                with self.assertRaises(ValueError):
                    gates.inspect_xo(path, name)
                self.write_xo(path, name, "original_example")
                with self.assertRaises(ValueError):
                    gates.inspect_xo(path, name, "a4")

    def topology(self):
        connections = [("kernelApply:kernelApply_1", 0, "HBM[30]")]
        for lane in range(4):
            connections += [("kernelHBMWrapper:kernelHBMWrapper_1", lane + offset,
                              f"HBM[{2 * lane + 1}]") for offset in (0, 4)]
            connections.append((f"littleKernelScatterGather:littleKernelScatterGather_{lane + 1}",
                                0, f"HBM[{2 * lane}]"))
        return {"kernels": sorted((f"{name}:{name}_{i}", config.control_protocol(name, "a4").upper())
                for name, (_, count) in config.kernels("a4").items() for i in range(1, count + 1)),
                "clock": [("DATA", "DATA_CLK", 150)], "connections": sorted(connections),
                "memory": [(f"HBM[{i}]", "MEM_HBM", "1", "0x80000") for i in range(32)]}

    def test_routed_gate_requires_a4_exact_banks_replica_offsets_and_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in SECTIONS.values():
                (root / (name + ".json")).write_text("{}")
            timing = root / "impl_1_hw_bb_locked_timing_summary_routed.rpt"
            timing.write_text("WNS(ns) TNS TNSend TNSall WHS THS THSend THSall WPWS TPWS TPWSend TPWSall\n"
                              "-----\n0.1 0 0 100 0.01 0 0 100 0 0 0 100\n"
                              "All user specified timing constraints are met.\n")
            topology = self.topology()
            with patch.object(gates, "normalized_topology", return_value=topology):
                result = gates.inspect_routed(root, root, "a4")
                self.assertEqual(result["status"], config.routed_status("a4"))
                self.assertFalse(result["publication_match"])
                with self.assertRaises(ValueError):
                    gates.inspect_routed(root, root)
            for field in ("kernels", "connections"):
                changed = copy.deepcopy(topology)
                changed[field].pop()
                with patch.object(gates, "normalized_topology", return_value=changed), self.assertRaises(ValueError):
                    gates.inspect_routed(root, root, "a4")
            changed = copy.deepcopy(topology)
            changed["clock"] = [("DATA", "DATA_CLK", 149)]
            with patch.object(gates, "normalized_topology", return_value=changed), self.assertRaises(ValueError):
                gates.inspect_routed(root, root, "a4")
            timing.write_text(timing.read_text().replace("0.1 0 0 100", "-0.1 -1 1 100"))
            with patch.object(gates, "normalized_topology", return_value=topology), self.assertRaises(ValueError):
                gates.inspect_routed(root, root, "a4")

    def test_a4_entries_preserve_author_source_and_exclude_big(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "author", Path(directory) / "run"
            output.mkdir()
            originals = []
            for relative, _ in config.kernels("a4").values():
                path = source / "acc_template" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("uint untouched_author(uint value) { return value; }\n")
                originals.append(artifact.identity(path))
            pins = snapshot.prepare_entries(source, output, "a4")
            self.assertEqual(len(pins), 6)
            self.assertEqual(len(list((output / "entries").glob("*.cpp"))), 4)
            snapshot.unchanged([*pins, *originals])

    def test_invalid_topology_stops_before_output_creation_or_memory_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for runner, kwargs in ((execution.run, {}), (waiting.run, {"wait_seconds": 1})):
                with patch.object(execution, "Lease") as lease, self.assertRaises(ValueError):
                    runner(root, root, root, root, root, root / "no-run", topology="not_a4", **kwargs)
                lease.assert_not_called()
                self.assertFalse((root / "no-run").exists())

    def test_existing_11_plus_3_board_gate_rejects_a4_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results.json").write_text(json.dumps({"status": config.routed_status("a4")}))
            with self.assertRaisesRegex(ValueError, "fresh-source route required"):
                admission.review(root, root / "no-admission")
            self.assertFalse((root / "no-admission").exists())

    def test_source_only_preflight_retains_scope_and_never_runs_compile_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group = root / "cgroup"
            group.mkdir()
            (group / "memory.events").write_text("oom 0\noom_kill 0\n")
            output = root / "preflight"
            prepared = {"source": str(output / "source"), "pins": [], "device_algorithm_edits": False}
            with patch.object(preflight, "current", return_value=group), \
                    patch.object(preflight, "verify", return_value={}) as containment, \
                    patch.object(preflight, "available_memory_bytes", return_value=64 * 1024**3), \
                    patch.object(preflight.execution, "runner_pins", return_value=[]), \
                    patch.object(preflight.artifact, "identity", return_value={}), \
                    patch.object(preflight.subprocess, "check_output", side_effect=["revision\n", "", "Python 3.11\n"]), \
                    patch.object(preflight.snapshot, "prepare", return_value=prepared) as prepare, \
                    patch.object(preflight.snapshot, "prepare_entries", return_value=[]) as entries, \
                    patch.object(preflight.snapshot, "unchanged"), \
                    patch.object(preflight.execution, "run") as compiler:
                result = preflight.run(root, root / "author", output, topology="a4")
            containment.assert_called_once_with(group, memory_gib=2)
            prepare.assert_called_once_with(root, root / "author", output, "a4")
            entries.assert_called_once_with(output / "source", output, "a4")
            compiler.assert_not_called()
            self.assertEqual(len(result["commands_not_executed"]["compilations"]), 4)
            self.assertFalse(result["compiler_launched"])
            self.assertFalse(result["hardware_timing_measured"])
            self.assertEqual(json.loads((output / "results.json").read_text()), result)

    def test_source_only_preflight_insufficient_memory_is_retained_before_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "memory.events").write_text("oom 0\n")
            with patch.object(preflight, "current", return_value=root), \
                    patch.object(preflight, "verify", return_value={}), \
                    patch.object(preflight, "available_memory_bytes", return_value=33 * 1024**3), \
                    patch.object(preflight.snapshot, "prepare") as prepare, self.assertRaises(RuntimeError):
                preflight.run(root, root, root / "preflight", topology="a4")
            prepare.assert_not_called()
            result = json.loads((root / "preflight/results.json").read_text())
            self.assertEqual(result["status"], "FAILED_RETAINED")
            self.assertFalse(result["compiler_launched"])


if __name__ == "__main__":
    unittest.main()
