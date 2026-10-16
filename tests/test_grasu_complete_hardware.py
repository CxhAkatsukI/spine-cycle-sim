"""Diagnostic topology changes preserve all kernel counts and HBM connections."""

import json
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

    def test_legacy_candidate_gate_and_packet_arguments_are_preserved(self):
        paths = [Path("/old") / str(i) for i in range(8)]
        checked = ({"bin_search": Path("/search.xo"), "process_cache": Path("/cache.xo")},
                   [Path("/review.json")], {"original_core": "unchanged"})
        with patch.object(preparation, "candidates", return_value=checked) as candidates, \
                patch.object(preparation, "freeze", return_value={"unchanged": True}) as freeze:
            result = preparation.prepare(*paths, link_timeout_seconds=43200)
        candidates.assert_called_once_with(*paths[2:7])
        freeze.assert_called_once_with(*paths[:2], *checked, *paths[6:], link_timeout_seconds=43200)
        self.assertEqual(result, {"unchanged": True})

    def test_shared_freeze_preserves_legacy_packet_and_only_two_replacements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            basis, fit = root / "basis", root / "fit"
            basis.mkdir()
            (fit / "source").mkdir(parents=True)
            contents, ledger = self.fixture()
            config = basis / "link.cfg"
            config.write_text(contents)
            (fit / "source/link.cfg").write_text(contents)
            (fit / "results.json").write_text(json.dumps(ledger))
            xos = []
            for name in COUNTS:
                path = basis / (name + ".hw.xo")
                path.write_bytes(name.encode())
                xos.append(str(path))
            command = ["v++", "--target", "hw", "--link", "--kernel_frequency", "150",
                       "--config", str(config), "-o", str(basis / "candidate.hw.xclbin"), *xos,
                       "--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
            (basis / "manifest.json").write_text(json.dumps({"command": command, "pins": [],
                "clock_mhz": 150, "FPGA_timing_admitted": False}))
            replacements = {}
            for name in ("bin_search", "process_cache"):
                path = root / (name + ".xo")
                path.write_bytes(("production-" + name).encode())
                replacements[name] = path
            checked = replacements, [fit / "results.json"], {"core": "reviewed"}
            old, new = root / "legacy", root / "shared"
            with patch.object(preparation, "candidates", return_value=checked), \
                    patch.object(preparation, "reconstruct", return_value=({}, {"pins": []})):
                legacy = preparation.prepare(root, basis, root, root, root, root, fit, old,
                                             link_timeout_seconds=43200)
                shared = preparation.freeze(root, basis, *checked, fit, new, link_timeout_seconds=43200)
            def normalize(data, path):
                result = json.loads(json.dumps(data).replace(str(path), "OUTPUT"))
                for row in result["pins"]:
                    if row["path"] == "OUTPUT/link.cfg":
                        row["sha256"] = "PATH_SPECIFIC_CONFIG_HASH"
                return result
            self.assertEqual(normalize(legacy, old), normalize(shared, new))
            self.assertEqual((old / "link.cfg").read_text().replace(str(old), "OUTPUT"),
                             (new / "link.cfg").read_text().replace(str(new), "OUTPUT"))
            self.assertEqual(set(shared["kernel_inputs"]), set(COUNTS))
            self.assertEqual({name for name, row in shared["kernel_inputs"].items() if row["replaced"]},
                             {"bin_search", "process_cache"})
            for name in COUNTS:
                expected = replacements.get(name, basis / (name + ".hw.xo"))
                self.assertEqual((new / "inputs" / (name + ".hw.xo")).read_bytes(), expected.read_bytes())
            self.assertEqual([shared[key] for key in ("tree_memory_gib", "reserve_gib", "background_memory_gib",
                "allow_bounded_builds", "timeout_seconds")], [40, 24, 8, True, 43200])
            for claim in ("integrated_rtl_admitted", "FPGA_timing_admitted", "production_baseline_admitted",
                          "publication_match_admitted"):
                self.assertFalse(shared[claim])


if __name__ == "__main__":
    unittest.main()
