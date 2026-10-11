"""Reject incomplete packet/transaction evidence for the new HLS control."""

from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.analysis import (
    CASES, check_trace, transactions)
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.validation import compile_contract


class EmptySegmentAnalysisTests(unittest.TestCase):
    def test_complete_ordered_transaction_table(self):
        text = "latency interval\n" + "".join(
            f"transaction {i}: {i + 1} x\n" for i in range(len(CASES)))
        self.assertEqual(transactions(text), list(range(1, 14)))
        for invalid in (text.replace("transaction 12:", "transaction 11:"),
                        text + "transaction bad\n", text.replace("12: 13", "12: 0")):
            with self.assertRaises(ValueError):
                transactions(invalid)

    def test_complete_C_and_RTL_packet_checks(self):
        group = "".join(f"PMA_COSIM_CASE vertices={v} placement={p} length={n} "
                        f"packets={packets} status=PASS\n" for v, p, n, packets in CASES)
        group += "PMA_COSIM_RESULT status=PASS cases=13 packets=200\n"
        check_trace(group * 2)
        for invalid in (group, group * 2 + "ERROR late failure\n",
                        (group * 2).replace("packets=60", "packets=61", 1)):
            with self.assertRaises(ValueError):
                check_trace(invalid)

    def test_effective_flags_part_and_rounded_clock_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "project/solution/syn/report/pma_to_regraph_adapter_csynth.xml"
            report.parent.mkdir(parents=True)
            project = ET.Element("project")
            files = ET.SubElement(project, "files")
            definitions = ["COSIM_DEPTH", "SHARDED_PMA", "SHARE_ALL_MEMORY_PORTS",
                           "ROW_PREFETCH", "STOP_AFTER_LAST", "WEIGHTED_PMA",
                           "SKIP_EMPTY_SEGMENT"]
            flags = " ".join(f"-DGRASU_REGRAPH_{name}=1" for name in definitions)
            for name in ("pma_to_regraph_adapter.cpp", "pma_adapter_cosim_tb.cpp"):
                ET.SubElement(files, "file", name=name, cflags=flags)
            project_path = root / "project/hls.app"
            ET.ElementTree(project).write(project_path)
            xml = ET.Element("profile")
            assignments = ET.SubElement(xml, "UserAssignments")
            part = ET.SubElement(assignments, "Part")
            part.text = "xcu55c-fsvh2892-2L-e"
            clock = ET.SubElement(assignments, "TargetClockPeriod")
            clock.text = "6.67"
            ET.ElementTree(xml).write(report)
            compile_contract(root, 1)
            with self.assertRaises(ValueError):
                compile_contract(root, 0)
            for value in ("4.76", "6.66"):
                clock.text = value
                ET.ElementTree(xml).write(report)
                with self.assertRaises(ValueError):
                    compile_contract(root, 1)
            clock.text = "6.67"
            part.text = "other_part"
            ET.ElementTree(xml).write(report)
            with self.assertRaises(ValueError):
                compile_contract(root, 1)
            part.text = "xcu55c-fsvh2892-2L-e"
            ET.ElementTree(xml).write(report)
            for invalid in (flags.replace("SKIP_EMPTY_SEGMENT=1", "SKIP_EMPTY_SEGMENT=0"),
                            flags + " -DGRASU_REGRAPH_SKIP_EMPTY_SEGMENT=1",
                            flags.replace("-DGRASU_REGRAPH_ROW_PREFETCH=1", "")):
                files[0].set("cflags", invalid)
                ET.ElementTree(project).write(project_path)
                with self.assertRaises(ValueError):
                    compile_contract(root, 1)


if __name__ == "__main__":
    unittest.main()
