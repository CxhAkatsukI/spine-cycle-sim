"""Reject incomplete or ambiguous component gate reports."""

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from spine_cycle_sim.experiments.sharded_k4_stages.model_frontend import REPORTS, require_report, routed_source
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity


class FrontendReports(unittest.TestCase):
    def test_complete_reports(self):
        for name, text in REPORTS.items():
            require_report(name, text + "\n")

    def test_hls_informational_stream_depth(self):
        require_report("hls", REPORTS["hls"] + "\nINFO [HLS SIM]: The maximum depth reached by any hls::stream() instance in the design is 1026\n")

    def test_duplicate_rejected(self):
        for name, text in REPORTS.items():
            with self.assertRaises(ValueError):
                require_report(name, text + "\n" + text)

    def test_reduced_matrix_rejected(self):
        with self.assertRaises(ValueError):
            require_report("scatter", REPORTS["scatter"].replace("80", "40"))

    def test_unexpected_diagnostic_rejected(self):
        with self.assertRaises(ValueError):
            require_report("hls", REPORTS["hls"] + "\nERROR missing result")

    def test_missing_report_rejected(self):
        with self.assertRaises(ValueError):
            require_report("hls", "INFO [HLS SIM]: The maximum depth reached by any hls::stream() instance in the design is 1026")


class RoutedSourceIdentity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.header = self.root / "hbm_wrapper.h"
        self.header.write_text("// pinned header\n")
        self.xo = self.root / "source.xo"
        self.route = self.root / "route.json"
        self.inputs = self.root / "inputs.tsv"
        self.make_xo()
        self.route.write_text(json.dumps({"pins": [identity(self.xo)]}))
        with self.inputs.open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=["path", "sha256"], delimiter="\t")
            writer.writeheader()
            writer.writerows([
                {"path": "/old/ReGraph/hbm_wrapper.h", "sha256": identity(self.header)["sha256"]},
                {"path": "/old/kernels/regraph_k4_shared_hbm_wrapper/kernel_hbm_wrapper.cpp",
                 "sha256": hashlib.sha256(b"// embedded source\n").hexdigest()},
            ])

    def make_xo(self, masters=4, source=b"// embedded source\n"):
        with zipfile.ZipFile(self.xo, "w") as archive:
            ports = "".join(f'<port name="M_AXI_GMEM{i}" mode="master"/>' for i in range(1, masters + 1))
            archive.writestr("kernelHBMWrapper/kernel.xml", "<root>" + ports + "</root>")
            archive.writestr("kernelHBMWrapper/cpu_sources/kernel_hbm_wrapper.cpp", source)

    def validate(self):
        return routed_source(self.xo, self.route, self.inputs, [self.header], self.root, self.root / "out")

    def test_matching_embedded_source_and_headers(self):
        source, record = self.validate()
        self.assertEqual(source.read_bytes(), b"// embedded source\n")
        self.assertEqual(len(record["masters"]), 4)
        self.assertTrue(record["header_hashes_match_routed_compile"])

    def test_other_route_rejected(self):
        self.route.write_text(json.dumps({"pins": []}))
        with self.assertRaisesRegex(ValueError, "not pinned"):
            self.validate()

    def test_changed_header_rejected(self):
        self.header.write_text("// later source\n")
        with self.assertRaisesRegex(ValueError, "header differs"):
            self.validate()

    def test_pairwise_xo_not_confused_with_measured_four_master(self):
        self.make_xo(masters=2)
        self.route.write_text(json.dumps({"pins": [identity(self.xo)]}))
        with self.assertRaisesRegex(ValueError, "four-master"):
            self.validate()

    def test_changed_embedded_source_rejected(self):
        self.make_xo(source=b"// another source\n")
        self.route.write_text(json.dumps({"pins": [identity(self.xo)]}))
        with self.assertRaisesRegex(ValueError, "embedded source differs"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
