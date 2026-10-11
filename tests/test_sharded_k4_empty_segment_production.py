"""Production XOs must preserve ABI without leaking test-only compilation."""

from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.production import FLAGS, require_xo
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.production_validation import require_execution


class EmptySegmentProductionTests(unittest.TestCase):
    def test_resource_and_cleanup_evidence_required(self):
        record = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None,
                  "tree_memory_gib": 8, "reserve_gib": 16, "timeout_seconds": 1200,
                  "peak_tree_rss_kib": 2 * 1024**2, "minimum_available_bytes": 50 * 1024**3}
        require_execution(record, budget=8, timeout=1200)
        for key, value in (("exit_code", 1), ("stop_reason", "timeout"), ("cleanup_snapshot_error", "missing"),
                           ("tree_memory_gib", 9), ("reserve_gib", 0), ("timeout_seconds", 10),
                           ("peak_tree_rss_kib", 9 * 1024**2), ("minimum_available_bytes", 15 * 1024**3)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_execution({**record, key: value}, budget=8, timeout=1200)

    def test_production_flags_and_frozen_abi(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def write(name, flags, width="512", extra=""):
                xml = ET.Element("root")
                kernel = ET.SubElement(xml, "kernel", name="pma_to_regraph_adapter",
                                       hwControlProtocol="ap_ctrl_chain",
                                       compileOptions=" ".join(f"-D{key}={value}" for key, value in flags.items()) + extra)
                ET.SubElement(ET.SubElement(kernel, "ports"), "port", name="GMEM0", dataWidth=width)
                ET.SubElement(ET.SubElement(kernel, "args"), "arg", name="pma0", id="0", offset="0x10")
                path = root / name
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("adapter/kernel.xml", ET.tostring(xml))
                return path
            baseline = write("original.xo", {})
            candidate = write("candidate.xo", FLAGS)
            self.assertEqual(require_xo(candidate, baseline)["flags"], FLAGS)
            for flags in ({**FLAGS, "GRASU_REGRAPH_COSIM_DEPTH": "1"},
                          {**FLAGS, "GRASU_REGRAPH_SKIP_EMPTY_SEGMENT": "0"},
                          {key: value for key, value in FLAGS.items() if not key.endswith("ROW_PREFETCH")},
                          {**FLAGS, "GRASU_REGRAPH_UNKNOWN": "1"}):
                with self.assertRaises(ValueError):
                    require_xo(write("candidate.xo", flags), baseline)
            with self.assertRaises(ValueError):
                require_xo(write("candidate.xo", FLAGS, "256"), baseline)
            for extra in (" -UGRASU_REGRAPH_SKIP_EMPTY_SEGMENT", " -U GRASU_REGRAPH_SKIP_EMPTY_SEGMENT",
                          " -DGRASU_REGRAPH_SKIP_EMPTY_SEGMENT=0", " -DGRASU_REGRAPH_SKIP_EMPTY_SEGMENT=1",
                          " -D", " -U"):
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    require_xo(write("candidate.xo", FLAGS, extra=extra), baseline)


if __name__ == "__main__":
    unittest.main()
