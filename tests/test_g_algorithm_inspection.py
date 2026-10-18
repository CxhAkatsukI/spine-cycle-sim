"""Reject incomplete exports without promoting an HLS storage screen to hardware evidence."""

import copy
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build import inspection
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.resource_fit import RESOURCES


def interface(kernel, mode, width=512):
    return {"kernel": kernel, "control": "ap_ctrl_chain", "macros": {}, "ports": {
        "GMEM": {"name": "GMEM", "mode": "master", "portType": "addressable", "dataWidth": "512"},
        "CONTROL": {"name": "CONTROL", "mode": "slave", "portType": "addressable", "dataWidth": "32"},
        "EDGE": {"name": "EDGE", "mode": mode, "portType": "stream", "dataWidth": str(width)}},
        "args": {"pma0": {"name": "pma0", "id": "0", "port": "GMEM"},
                 "row_offset": {"name": "row_offset", "id": "1", "port": "GMEM"},
                 "count": {"name": "count", "id": "2", "port": "CONTROL"},
                 "edge": {"name": "edge", "id": "3", "port": "EDGE"}}}


def export(path, view, options="", internal_copy=False):
    root = ET.Element("root")
    kernel = ET.SubElement(root, "kernel", name=view["kernel"],
                           hwControlProtocol=view["control"], compileOptions=options)
    ports, args = ET.SubElement(kernel, "ports"), ET.SubElement(kernel, "args")
    for port in view["ports"].values():
        ET.SubElement(ports, "port", **port)
    for arg in view["args"].values():
        ET.SubElement(args, "arg", **arg)
    with ZipFile(path, "w") as archive:
        archive.writestr(view["kernel"] + "/kernel.xml", ET.tostring(root))
        if internal_copy:
            archive.writestr("ip_repo/internal/.kernelxml/kernel.xml", "<internal/>")


CONFIG = ("[connectivity]\nnk=pma_to_regraph_adapter:1:a\nnk=consume:1:b\n"
          "slr=a:SLR0\nslr=b:SLR1\nstream_connect=a.edge:b.edge:32\n"
          "sp=a.pma0:HBM[0:22]\nsp=b.pma0:HBM[23]\n")
CAPACITY = {"SLR0": 320, "SLR1": 320, "SLR2": 320, "device": 960}


def fixture(root):
    config = root / "link.cfg"
    config.write_text(CONFIG)
    rows = []
    for kernel, mode in (("pma_to_regraph_adapter", "write_only"), ("consume", "read_only")):
        xo, cfg = root / (kernel + ".xo"), root / (kernel + ".cfg")
        export(xo, interface(kernel, mode))
        cfg.write_text("temp_dir=" + str(root / "tmp" / kernel) + "\n")
        report = root / "tmp" / kernel / (kernel + "_csynth.xml")
        report.parent.mkdir(parents=True)
        report.write_text("<Report><UserAssignments><TopModelName>" + kernel + "</TopModelName>"
            "<TargetClockPeriod>6.67</TargetClockPeriod><Part>" + inspection.PART + "</Part>"
            "</UserAssignments><AreaEstimates><Resources>" +
            "".join("<" + name + ">" + ("256" if name == "URAM" else "1") + "</" + name + ">"
                    for name in RESOURCES) + "</Resources><AvailableResources>" +
            "".join("<" + name + ">" + str(value) + "</" + name + ">"
                    for name, value in inspection.PART_RESOURCES.items()) +
            "</AvailableResources></AreaEstimates><PerformanceEstimates>"
            "<SummaryOfTimingAnalysis><EstimatedClockPeriod>8.0</EstimatedClockPeriod>"
            "</SummaryOfTimingAnalysis></PerformanceEstimates></Report>")
        rows.append({"kernel": kernel, "xo": str(xo), "argv": ["v++", "--config", str(cfg)]})
    return config, rows


class ExportTests(unittest.TestCase):
    def test_split_defines_normalize_and_undefinitions_or_redefinitions_fail(self):
        self.assertEqual(inspection.definitions("-D GRASU_A=1 -DCACHE_BANK_REGISTERED -DUNRELATED=2"),
                         {"GRASU_A": "1", "CACHE_BANK_REGISTERED": "1"})
        for flags in ("-D", "-U GRASU_A", "-DGRASU_A=1 -D GRASU_A=0"):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                inspection.definitions(flags)

    def test_uses_canonical_export_not_internal_vivado_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "adapter.xo"
            view = interface("pma_to_regraph_adapter", "write_only")
            export(path, view, "-D GRASU_REGRAPH_ROW_LINE_READ=1", internal_copy=True)
            result = inspection.exported(path, view["kernel"], ["-DGRASU_REGRAPH_ROW_LINE_READ=1"])
            self.assertEqual(result["args"], view["args"])
            with self.assertRaisesRegex(ValueError, "macros"):
                inspection.exported(path, view["kernel"], ["-DGRASU_REGRAPH_ROW_LINE_READ=0"])
            with self.assertRaisesRegex(ValueError, "canonical"):
                inspection.exported(path, "different", [])

    def test_rejects_adapter_width_alias_and_duplicate_argument_ids(self):
        original = interface("pma_to_regraph_adapter", "write_only")
        changes = (lambda v: v["ports"]["GMEM"].update(dataWidth="64"),
                   lambda v: v["args"]["row_offset"].update(port="CONTROL"),
                   lambda v: v["args"]["row_offset"].update(port="MISSING"),
                   lambda v: v["args"]["row_offset"].update(id="0"))
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                view = copy.deepcopy(original)
                change(view)
                path = Path(temporary) / "adapter.xo"
                export(path, view)
                with self.assertRaises(ValueError):
                    inspection.exported(path, view["kernel"], [])


class ConnectionTests(unittest.TestCase):
    def views(self):
        return {"pma_to_regraph_adapter": interface("pma_to_regraph_adapter", "write_only"),
                "consume": interface("consume", "read_only")}

    def test_complete_streams_and_master_aliases(self):
        result = inspection.check_connections(CONFIG, self.views())
        self.assertEqual(result["streams"], [{"source": "a.edge", "sink": "b.edge",
                                             "width_bits": 512, "fifo_depth": 32}])
        self.assertEqual(result["automatic_memory_masters"], [])
        result = inspection.check_connections(CONFIG.replace("sp=b.pma0:HBM[23]\n", ""), self.views())
        self.assertEqual(result["automatic_memory_masters"], [{"instance": "b", "port": "GMEM"}])

    def test_missing_reused_wrong_direction_and_width_are_rejected(self):
        for config in (CONFIG.replace("stream_connect=a.edge:b.edge:32\n", ""),
                       CONFIG + "stream_connect=a.edge:b.edge:32\n",
                       CONFIG.replace("a.edge:b.edge", "b.edge:a.edge"),
                       CONFIG.replace("a.edge:b.edge", "a.unknown:b.edge"),
                       CONFIG.replace(":b.edge:32", ":b.edge:0")):
            with self.subTest(config=config), self.assertRaises(ValueError):
                inspection.check_connections(config, self.views())
        views = self.views()
        views["consume"]["ports"]["EDGE"]["dataWidth"] = "256"
        with self.assertRaisesRegex(ValueError, "width"):
            inspection.check_connections(CONFIG, views)

    def test_alias_conflict_duplicate_mapping_and_control_mapping_rejected(self):
        for addition in ("sp=a.row_offset:HBM[23]\n", "sp=a.pma0:HBM[0:22]\n",
                         "sp=a.count:HBM[0:22]\n", "sp=a.missing:HBM[0:22]\n"):
            with self.subTest(addition=addition), self.assertRaises(ValueError):
                inspection.check_connections(CONFIG + addition, self.views())


class StorageInspectionTests(unittest.TestCase):
    def test_whole_device_limit_rejects_ff_excess_and_missing_or_wrong_capacity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, rows = fixture(root)
            report = root / "tmp/consume/consume_csynth.xml"
            original = report.read_text()
            report.write_text(original.replace("<FF>1</FF>", "<FF>6019300</FF>"))
            result = inspection.inspect(config, rows, CAPACITY, CAPACITY)
            self.assertEqual(result["status"], "RESOURCE_ESTIMATE_CONFLICT_REQUIRES_IMPLEMENTATION_REVIEW")
            self.assertEqual(result["resource_ledger"]["whole_device_screen"]["oversubscribed_resources"], ["FF"])
            for replacement in ("<FF>99999999</FF>", ""):
                report.write_text(original.replace("<FF>2607360</FF>", replacement))
                with self.assertRaises((ValueError, TypeError)):
                    inspection.inspect(config, rows, CAPACITY, CAPACITY)

    def test_all_exports_counted_without_timing_or_rtl_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            config, rows = fixture(Path(temporary))
            result = inspection.inspect(config, rows, CAPACITY, CAPACITY)
            self.assertEqual(result["status"], "EXPORT_AND_STORAGE_SCREEN_PASS_NOT_RTL_OR_ROUTE_ADMISSION")
            self.assertEqual(result["resource_ledger"]["hls_totals"]["URAM"], 512)
            self.assertEqual(result["reports"][0]["estimated_ns"], 8)
            self.assertTrue(all(result[key] is False for key in (
                "rtl_admitted", "routed", "board_admitted", "publication_match")))
            conflict = inspection.inspect(config, rows, CAPACITY, {**CAPACITY, "SLR0": 128, "device": 768})
            self.assertEqual(conflict["status"], "STORAGE_CONFLICT_REQUIRES_PLACEMENT_REVIEW")
            self.assertEqual(conflict["resource_ledger"]["platform_storage_screen"]["uram_oversubscribed_slrs"],
                             ["SLR0"])

    def test_part_clock_finiteness_top_and_report_uniqueness_fail_closed(self):
        replacements = ((inspection.PART, "wrong-part"), ("6.67", "5.0"), ("6.67", "nan"),
                        ("8.0", "inf"), ("8.0", "-1.0"),
                        ("<TopModelName>consume", "<TopModelName>wrong"))
        for before, after in replacements:
            with self.subTest(before=before, after=after), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                config, rows = fixture(root)
                report = root / "tmp/consume/consume_csynth.xml"
                report.write_text(report.read_text().replace(before, after))
                with self.assertRaises(ValueError):
                    inspection.inspect(config, rows, CAPACITY, CAPACITY)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config, rows = fixture(root)
            (root / "tmp/consume/duplicate").mkdir()
            report = root / "tmp/consume/consume_csynth.xml"
            (report.parent / "duplicate" / report.name).write_text(report.read_text())
            with self.assertRaisesRegex(ValueError, "one exact"):
                inspection.inspect(config, rows, CAPACITY, CAPACITY)


if __name__ == "__main__":
    unittest.main()
