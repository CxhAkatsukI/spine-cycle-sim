import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe import binding_preparation
from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.binding_abi import compare
from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.binding_analysis import analyze, status
from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.binding_delivery import package, verify
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.abi import NS, exported_members


def interfaces():
    root = ET.Element("root")
    kernel = ET.SubElement(root, "kernel", name="process_cache", hwControlProtocol="ap_ctrl_chain")
    ports, args = ET.SubElement(kernel, "ports"), ET.SubElement(kernel, "args")
    for name, kind, mode, width in (("M_AXI_GMEM0", "addressable", "master", 512),
            ("UPDATE_STREAM", "stream", "read_only", 96),
            ("COMPLETION_TOKEN", "stream", "write_only", 32),
            ("S_AXI_CONTROL", "addressable", "slave", 32)):
        ET.SubElement(ports, "port", name=name, portType=kind, mode=mode, dataWidth=str(width))
    for index, name in enumerate(("pma_cache", "update_stream", "completion_token")):
        ET.SubElement(args, "arg", id=str(index), name=name,
            port="M_AXI_GMEM0" if index == 0 else name.upper(),
            addressQualifier="1" if index == 0 else "4", offset="0x10" if index == 0 else "0",
            size="8" if index == 0 else "0", hostSize="8")

    def element(parent, tag, text=None):
        child = ET.SubElement(parent, "{" + NS["s"] + "}" + tag)
        child.text = text
        return child

    component = ET.Element("{" + NS["s"] + "}component")
    block = element(element(element(component, "memoryMaps"), "memoryMap"), "addressBlock")
    reg = element(block, "register")
    element(reg, "name", "pma_cache_0")
    element(reg, "addressOffset", "16")
    element(reg, "size", "32")
    buses, model = element(component, "busInterfaces"), element(component, "model")
    physical_ports = element(model, "ports")
    for name, direction, width in (("update_stream", "slave", 96), ("completion_token", "master", 32)):
        bus = element(buses, "busInterface")
        element(bus, "name", name)
        element(bus, direction)
        mappings = element(bus, "portMaps")
        for signal, bits in (("TDATA", width), ("TKEEP", width // 8), ("TSTRB", width // 8),
                             ("TLAST", 1), ("TVALID", 1), ("TREADY", 1)):
            physical = name + "_" + signal
            mapping = element(mappings, "portMap")
            element(element(mapping, "logicalPort"), "name", signal)
            element(element(mapping, "physicalPort"), "name", physical)
            port = element(physical_ports, "port")
            element(port, "name", physical)
            wire = element(port, "wire")
            element(wire, "direction", "out" if (direction == "master") != (signal == "TREADY") else "in")
            vector = element(wire, "vector")
            element(vector, "left", str(bits - 1))
            element(vector, "right", "0")
    return ET.tostring(root), ET.tostring(component)


class CacheBindingTests(unittest.TestCase):
    def test_both_axis_buses_registers_and_control_are_checked(self):
        kernel, component = interfaces()
        self.assertTrue(compare(kernel, component, kernel, component)["matches_routed_cache_abi"])
        for wrong_kernel, wrong_component in (
            (kernel.replace(b'offset="0x10"', b'offset="0x14"'), component),
            (kernel.replace(b'ap_ctrl_chain', b'ap_ctrl_hs'), component),
            (kernel.replace(b'name="completion_token"', b'name="done"'), component),
            (kernel.replace(b'dataWidth="96"', b'dataWidth="128"'), component),
            (kernel, component.replace(b'>11<', b'>15<')),
            (kernel, component.replace(b'>3<', b'>7<')),
            (kernel, component.replace(b'>16<', b'>20<')),
            (kernel, component.replace(b'>out<', b'>in<', 1))):
            with self.subTest(), self.assertRaises(ValueError):
                compare(wrong_kernel, wrong_component, kernel, component)

    def test_canonical_xo_members_are_kernel_specific(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.xo"
            with ZipFile(path, "w") as archive:
                archive.writestr("process_cache/kernel.xml", "canonical")
                archive.writestr("ip_repo/cache/component.xml", "component")
                archive.writestr("ip_repo/cache/.Xil/run/kernel.xml", "scratch")
            with ZipFile(path) as archive:
                self.assertEqual(exported_members(archive, "process_cache")["kernel.xml"],
                                 "process_cache/kernel.xml")
                with self.assertRaisesRegex(ValueError, "canonical"):
                    exported_members(archive)

    def fixture(self, root, clock="3.65"):
        kernel, component = interfaces()
        reference = root / "reference"
        reference.mkdir()
        (reference / "kernel.xml").write_bytes(kernel)
        (reference / "component.xml").write_bytes(component)
        files = {
            "syn/report/process_cache_csynth.xml": "<Report><PerformanceEstimates><SummaryOfTimingAnalysis>"
                f"<EstimatedClockPeriod>{clock}</EstimatedClockPeriod></SummaryOfTimingAnalysis>"
                "</PerformanceEstimates><AreaEstimates><Resources><URAM>256</URAM></Resources></AreaEstimates></Report>",
            "csim/report/process_cache_csim.log": "\n".join(
                f"CACHE_FULL_PASS updates={count} conflict={conflict}"
                for count, conflict in ((0, 0), (16, 0), (64, 0), (4096, 0), (65536, 0), (4096, 1))),
            "sim/report/process_cache_cosim.rpt": "| Verilog | Pass |",
            "sim/report/verilog/result.transaction.rpt": "latency interval\n" + "\n".join(
                f"transaction {index}: {278000 + index} x" for index in range(6))}
        for name, contents in files.items():
            path = root / "project/solution" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        with ZipFile(root / "process_cache.hw.xo", "w") as archive:
            archive.writestr("process_cache/kernel.xml", kernel)
            archive.writestr("ip_repo/cache/component.xml", component)
        return reference

    def test_wrapper_pass_cannot_promote_complete_g_or_board_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root)
            result = analyze(root, reference)
        self.assertEqual(result["errors"], {})
        self.assertEqual(status(result), "CACHE_WRAPPER_RTL_ABI_PASS_TARGET_MET_REQUIRES_INTEGRATION")
        self.assertEqual([row["updates"] for row in result["transactions"]], [0, 16, 64, 4096, 65536, 4096])
        for key in ("integrated_g_admitted", "hardware_timing_admitted", "production_baseline_admitted",
                    "publication_match_admitted", "external_RTL_backpressure_tested"):
            self.assertFalse(result[key])

    def test_clock_failure_and_missing_transaction_are_separate_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root, "5.6")
            result = analyze(root, reference)
            self.assertEqual(result["errors"], {})
            self.assertEqual(status(result), "CACHE_WRAPPER_RTL_ABI_PASS_CLOCK_GATE_FAILED")
            (root / "project/solution/sim/report/verilog/result.transaction.rpt").write_text("latency interval\n")
            self.assertEqual(status(analyze(root, reference)), "FAILED_RETAINED")

    def test_reordered_state_calls_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = self.fixture(root)
            path = root / "project/solution/csim/report/process_cache_csim.log"
            path.write_text(path.read_text().replace("updates=16", "updates=64", 1))
            self.assertIn("csim", analyze(root, reference)["errors"])

    def test_missing_reports_retain_every_independent_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = analyze(root, root / "reference")
        self.assertEqual(set(result["errors"]), {"synthesis", "csim", "rtl", "abi"})
        self.assertEqual(status(result), "FAILED_RETAINED")

    def test_preparation_requires_passed_composition_before_creating_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results.json").write_text(json.dumps({"status": "FAILED_RETAINED"}))
            with self.assertRaisesRegex(ValueError, "passing full-capacity"):
                binding_preparation.prepare(root / "output", root, root, root)
            self.assertFalse((root / "output").exists())

    def test_preparation_refuses_changed_shared_cache_core(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "results.json").write_text(json.dumps({"status": binding_preparation.PASS}))
            path = root / "source/hls/cache_pipeline.hpp"
            path.parent.mkdir(parents=True)
            path.write_text("not the checked cache core")
            with patch.object(binding_preparation, "validate"), \
                    self.assertRaisesRegex(ValueError, "shared cache implementation"):
                binding_preparation.prepare(root / "output", root, root, root)
            self.assertFalse((root / "output").exists())

    def test_tcl_uses_production_top_and_exports_after_rtl(self):
        script = binding_preparation.tcl()
        self.assertIn("set_top process_cache\n", script)
        self.assertIn("CACHE_PRODUCTION_BINDING", script)
        self.assertIn("GRASU_ENABLE_COMPLETION_TOKEN", script)
        self.assertIn("create_clock -period 5", script)
        self.assertNotIn("GRASU_PURE_PIPELINE_DIRECT_CACHE", script)
        self.assertLess(script.index("cosim_design"), script.index("export_design"))


class CacheBindingDeliveryTests(unittest.TestCase):
    def fixture(self, root):
        attempt = root / "cache-wrapper"
        build = attempt / "attempt"
        build.mkdir(parents=True)
        reference = CacheBindingTests().fixture(build)
        reference.rename(attempt / "reference")
        source = attempt / "source/top.cpp"
        source.parent.mkdir()
        source.write_text("frozen wrapper")
        script = build / "run.tcl"
        script.write_text("cosim_design\nexport_design\n")
        execution = {"exit_code": 0, "timed_out": False}
        for kind in ("stdout", "stderr"):
            path = build / ("execution." + kind + ".txt")
            path.write_text("tool log")
            execution[kind] = str(path)
        (build / "execution.resources.json").write_text(json.dumps(execution))
        observation = analyze(build, attempt / "reference")
        pin = lambda path: {"path": str(path), "sha256": sha256_file(path)}
        report = {"status": status(observation), "errors": [], "analysis": observation,
                  "execution": execution, "source": [pin(source)], "script": pin(script),
                  "hardware_timing_admitted": False, "production_baseline_admitted": False,
                  "publication_match_admitted": False}
        (attempt / "results.json").write_text(json.dumps(report))
        return attempt, report

    def test_capsule_is_portable_and_keeps_claims_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, _ = self.fixture(root)
            index = package(root / "evidence", attempt)
            attempt.rename(root / "unavailable-local-build")
            self.assertEqual(verify(root / "evidence"), index)
            self.assertFalse(index["integrated_g_admitted"])
            self.assertFalse(index["integrated_rtl_admitted"])
            self.assertFalse(index["hardware_timing_admitted"])

    def test_capsule_refuses_changed_sources_reports_or_export(self):
        for relative in ("source/top.cpp", "attempt/run.tcl", "attempt/process_cache.hw.xo",
                         "attempt/project/solution/sim/report/verilog/result.transaction.rpt"):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                attempt, _ = self.fixture(root)
                with (attempt / relative).open("ab") as stream:
                    stream.write(b"changed")
                with self.assertRaises(ValueError):
                    package(root / "evidence", attempt)

    def test_running_or_promoted_status_is_rejected(self):
        for change in ({"status": "RUNNING_CACHE_WRAPPER_HLS_RTL_ABI"},
                       {"hardware_timing_admitted": True}, {"errors": ["unexpected"]}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                attempt, report = self.fixture(root)
                report.update(change)
                (attempt / "results.json").write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    package(root / "evidence", attempt)

    def test_archive_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt, _ = self.fixture(root)
            index = package(root / "evidence", attempt)
            archive = root / "evidence" / index["attempts"][0]["archive"]
            with archive.open("ab") as stream:
                stream.write(b"changed")
            with self.assertRaisesRegex(ValueError, "archive identity"):
                verify(root / "evidence")


if __name__ == "__main__":
    unittest.main()
