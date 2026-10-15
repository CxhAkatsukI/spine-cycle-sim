from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.abi import NAMES, NS, compare
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.rtl_analysis import analyze, bench, status
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding import rtl_preparation
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_binding.rtl_preparation import tcl
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.rtl_analysis import COUNTS


def interfaces():
    root = ET.Element("root")
    kernel = ET.SubElement(root, "kernel", name="bin_search", hwControlProtocol="ap_ctrl_chain")
    ports, args = ET.SubElement(kernel, "ports"), ET.SubElement(kernel, "args")
    for name, kind, mode, width in (("M_AXI_GMEM_EDGES", "addressable", "master", 64),
        ("M_AXI_GMEM_BINARY", "addressable", "master", 64),
        ("SEGMENT_HEAD_STREAM_OUT", "stream", "write_only", 96),
        ("S_AXI_CONTROL", "addressable", "slave", 32)):
        ET.SubElement(ports, "port", name=name, portType=kind, mode=mode, dataWidth=str(width))
    for index, name in enumerate(NAMES):
        port = ("M_AXI_GMEM_EDGES" if index == 0 else "M_AXI_GMEM_BINARY" if index in (1, 5)
                else "SEGMENT_HEAD_STREAM_OUT" if index == 10 else "S_AXI_CONTROL")
        ET.SubElement(args, "arg", id=str(index), name=name, port=port,
            addressQualifier=str(4 if index == 10 else 1 if index in (0, 1, 5) else 0),
            offset=hex(0 if index == 10 else 16 + index * 12),
            size=hex(0 if index == 10 else 4 if index == 9 else 8), hostSize=hex(4 if index == 9 else 8))

    def element(parent, tag, text=None):
        child = ET.SubElement(parent, "{" + NS["s"] + "}" + tag)
        child.text = text
        return child

    component = ET.Element("{" + NS["s"] + "}component")
    block = element(element(element(component, "memoryMaps"), "memoryMap"), "addressBlock")
    for index, name in enumerate(NAMES[:10]):
        for half in range(1 if index == 9 else 2):
            reg = element(block, "register")
            element(reg, "name", name + "_" + str(half))
            element(reg, "addressOffset", str(16 + index * 12 + half * 4))
            element(reg, "size", "32")
    bus = element(element(component, "busInterfaces"), "busInterface")
    element(bus, "name", "segment_head_stream_out")
    element(bus, "master")
    maps = element(bus, "portMaps")
    ports = element(element(component, "model"), "ports")
    for name, width in (("TDATA", 96), ("TKEEP", 12), ("TSTRB", 12),
                        ("TLAST", 1), ("TVALID", 1), ("TREADY", 1)):
        physical = "segment_head_stream_out_" + name
        mapping = element(maps, "portMap")
        element(element(mapping, "logicalPort"), "name", name)
        element(element(mapping, "physicalPort"), "name", physical)
        port = element(ports, "port")
        element(port, "name", physical)
        wire = element(port, "wire")
        element(wire, "direction", "in" if name == "TREADY" else "out")
        vector = element(wire, "vector")
        element(vector, "left", str(width - 1))
        element(vector, "right", "0")
    return ET.tostring(root), ET.tostring(component)


def stdout():
    return "\n".join(f"SEARCH_PIPELINE_PASS updates={count} probes=0 stalled=0 channels=0 "
        f"output_blocked=0 host_vendor_keep_bits=12\nSEARCH_BINDING_RTL_ROW generation={generation} updates={count}"
        for count in COUNTS for generation in range(2))


class SearchBindingRTLTests(unittest.TestCase):
    def test_preparation_rejects_incomplete_controls_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, status_label in (("binding", "SEARCH_BINDING_SOURCE_PASS_NOT_RTL"),
                                       ("search", "RUNNING")):
                folder = root / name
                folder.mkdir()
                (folder / "results.json").write_text(json.dumps({"status": status_label}))
            with self.assertRaisesRegex(ValueError, "complete binding"):
                rtl_preparation.prepare(root / "output", root / "binding", root / "search", root / "reference")
            self.assertFalse((root / "output").exists())

    def test_preparation_rejects_different_shared_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            previous, stdout_path = root / "previous.json", root / "stdout.txt"
            previous.write_text("{}")
            stdout_path.write_text("")
            for name, label, contents in (("binding", "SEARCH_BINDING_SOURCE_PASS_NOT_RTL", "new"),
                                          ("search", "FINITE_HLS_SOURCE_PASS_NOT_RTL_TIMING", "old")):
                folder = root / name
                source = folder / "source" / rtl_preparation.SOURCE / "hls/search_pipeline/network.hpp"
                source.parent.mkdir(parents=True)
                source.write_text(contents)
                (folder / "results.json").write_text(json.dumps({"status": label, "dependencies": [],
                    "source": [{"path": str(source), "sha256": sha256_file(source)}],
                    "execute": {"stdout": str(stdout_path)},
                    "previous": {"path": str(previous), "sha256": sha256_file(previous)}}))
            with patch.object(rtl_preparation, "analyze_binding") as binding_analysis, \
                    patch.object(rtl_preparation, "analyze_isolated") as isolated_analysis:
                with self.assertRaisesRegex(ValueError, "different source: network.hpp"):
                    rtl_preparation.prepare(root / "output", root / "binding", root / "search", root / "reference")
                binding_analysis.assert_called_once()
                isolated_analysis.assert_called_once()
            self.assertFalse((root / "output").exists())

    def test_metadata_refresh_matrix_requires_all_18_ordered_calls(self):
        self.assertEqual(bench(stdout())["calls"], 18)
        self.assertTrue(bench(stdout())["pointer_storage_reused"])
        for wrong in (stdout().replace("generation=1", "generation=0", 1),
                      stdout().replace("SEARCH_BINDING_RTL_ROW", "OTHER", 1), stdout() + "\n" + stdout()):
            with self.assertRaises(ValueError):
                bench(wrong)

    def test_abi_checks_unused_arguments_register_offsets_and_sidebands(self):
        kernel, component = interfaces()
        self.assertTrue(compare(kernel, component, kernel, component)["matches_routed_search_abi"])
        for new_kernel, new_component in (
            (kernel.replace(b'name="binary_3"', b'name="binary_4"'), component),
            (kernel.replace(b'offset="0x10"', b'offset="0x14"'), component),
            (kernel.replace(b'ap_ctrl_chain', b'ap_ctrl_hs'), component),
            (kernel.replace(b'dataWidth="96"', b'dataWidth="128"'), component),
            (kernel, component.replace(b'>11<', b'>15<')),
            (kernel, component.replace(b'>16<', b'>20<'))):
            with self.subTest(), self.assertRaises(ValueError):
                compare(new_kernel, new_component, kernel, component)

    def test_export_and_all_transactions_cannot_hide_clock_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kernel, component = interfaces()
            reference = root / "reference"
            reference.mkdir()
            (reference / "kernel.xml").write_bytes(kernel)
            (reference / "component.xml").write_bytes(component)
            solution = root / "project/solution"
            files = {
                "syn/report/bin_search_csynth.xml": "<Report><PerformanceEstimates><SummaryOfTimingAnalysis>"
                "<EstimatedClockPeriod>5.6</EstimatedClockPeriod></SummaryOfTimingAnalysis></PerformanceEstimates>"
                "<AreaEstimates><Resources><LUT>123</LUT></Resources></AreaEstimates></Report>",
                "csim/report/bin_search_csim.log": stdout(),
                "sim/report/bin_search_cosim.rpt": "| Verilog | Pass |",
                "sim/report/verilog/result.transaction.rpt": "latency interval\n" +
                    "\n".join(f"transaction {index}: {index + 100} x" for index in range(18))}
            for name, contents in files.items():
                path = solution / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)
            with ZipFile(root / "search_binding.xo", "w") as archive:
                archive.writestr("kernel/kernel.xml", kernel)
                archive.writestr("ip_repo/component.xml", component)
            result = analyze(root, reference)
            self.assertEqual(result["errors"], {})
            self.assertEqual(status(result), "WRAPPER_RTL_ABI_PASS_CLOCK_GATE_FAILED")
            self.assertEqual([row["metadata_generation"] for row in result["transactions"]], [0, 1] * 9)
            for key in ("hardware_timing_admitted", "production_baseline_admitted", "publication_match_admitted",
                        "integrated_g_admitted", "external_RTL_backpressure_tested"):
                self.assertFalse(result[key])
            (solution / "sim/report/bin_search_cosim.rpt").write_text("| Verilog | Fail |")
            self.assertEqual(status(analyze(root, reference)), "FAILED_RETAINED")

    def test_missing_reports_retain_separate_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = analyze(root, root / "reference")
            self.assertEqual(set(result["errors"]), {"synthesis", "csim", "rtl", "abi"})
            self.assertEqual(status(result), "FAILED_RETAINED")

    def test_tcl_runs_real_wrapper_and_exports_only_after_rtl(self):
        script = tcl()
        self.assertIn("set_top bin_search\n", script)
        self.assertIn("hls/search_binding", script)
        self.assertLess(script.index("cosim_design"), script.index("export_design"))
        self.assertIn("create_clock -period 5", script)
