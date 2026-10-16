"""Diagnostic topology changes preserve all kernel counts and HBM connections."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware import preparation
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.preparation import COUNTS, relocate
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.resource_fit import topology


class CompleteHardwareTests(unittest.TestCase):
    def fixture(self):
        contents = """messageDb=/old/route.mdb
temp_dir=/old/link
report_dir=/old/reports
log_dir=/old/logs
remote_ip_cache=/old/cache
[connectivity]
"""
        for kernel, count in COUNTS.items():
            contents += f"nk={kernel}:{count}\n"
            for i in range(1, count + 1):
                contents += f"slr={kernel}_{i}:SLR0\n"
        contents += "sp=bin_search_1.edges:HBM[0:22]\nstream_connect=dispatch_1.out:process_ddr_1.in:16\n"
        kernels, places = topology(contents)
        rows = [{"instance": name, "slr": slr} for name, slr in places.items()]
        changed = [{**row, "slr": "SLR1" if row["instance"] == "lksg_stream_4" else row["slr"]}
                   for row in rows]
        return contents, {"instances": rows, "single_cu_relocation_screen": {"instances": changed}}

    def test_only_one_placement_and_output_paths_change(self):
        contents, ledger = self.fixture()
        changed = relocate(contents, Path("/new"), ledger)
        self.assertIn("slr=lksg_stream_4:SLR1", changed)
        self.assertIn("temp_dir=/new/link", changed)
        self.assertIn("sp=bin_search_1.edges:HBM[0:22]", changed)
        self.assertIn("stream_connect=dispatch_1.out:process_ddr_1.in:16", changed)
        self.assertEqual(topology(contents)[0], topology(changed)[0])
        differences = [(a, b) for a, b in zip(contents.splitlines(), changed.splitlines()) if a != b]
        self.assertEqual(len(differences), 6)

    def test_wrong_basis_or_relocation_rejected(self):
        contents, ledger = self.fixture()
        with self.assertRaises(ValueError):
            relocate(contents.replace("slr=lksg_stream_4:SLR0", "slr=lksg_stream_4:SLR2"), Path("/new"), ledger)
        ledger["single_cu_relocation_screen"]["instances"][0]["slr"] = "SLR2"
        with self.assertRaises(ValueError):
            relocate(contents, Path("/new"), ledger)

    def test_timeout_rejected_before_preparation_writes_or_reads_inputs(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(preparation, "candidates") as candidates:
            output = Path(tmp) / "attempt"
            for value in (True, 21600.0, 0, -1, 36000, 86400):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    preparation.prepare(*([Path("/unused")] * 7), output, link_timeout_seconds=value)
                self.assertFalse(output.exists())
            candidates.assert_not_called()

    def test_existing_attempt_rejected_even_with_extended_timeout(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(preparation, "candidates") as candidates:
            output = Path(tmp)
            with self.assertRaises(FileExistsError):
                preparation.prepare(*([Path("/unused")] * 7), output, link_timeout_seconds=43200)
            candidates.assert_not_called()


if __name__ == "__main__":
    unittest.main()
