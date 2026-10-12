"""Cross-row admission rejects incomplete gates and altered legacy timing."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row import validation as v
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.study import compile_command
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.delivery import verify
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.recheck import recheck


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/"
    "adapter_optimization/row_line/cross_row/evidence")


class CrossRowTests(unittest.TestCase):
    def test_three_exact_format_matrices(self):
        line = "ROW_PREFETCH_EQUIVALENCE status=PASS cases=254 packets=1482 skip_empty=1 row_line=1 cross_row=1\n"
        v.require_functional(line * 3)
        for bad in (line * 2, line * 4, (line * 3).replace("1482", "1481", 1),
                    (line * 3).replace("cross_row=1", "cross_row=0", 1)):
            with self.subTest(text=bad), self.assertRaises(ValueError):
                v.require_functional(bad)

    def test_external_abi_and_flags(self):
        with patch.object(v, "adapter_interface", side_effect=[({"abi": "same"}, v.REFERENCE_FLAGS),
                                                              ({"abi": "same"}, v.FLAGS)]):
            self.assertEqual(v.require_xos("old", "new")["interface"], {"abi": "same"})
        for interface, flags in (({"abi": "changed"}, v.FLAGS),
                                 ({"abi": "same"}, v.FLAGS | {"GRASU_TEST_DEPTH": "1"}),
                                 ({"abi": "same"}, v.REFERENCE_FLAGS)):
            with patch.object(v, "adapter_interface", side_effect=[({"abi": "same"}, v.REFERENCE_FLAGS),
                                                                   (interface, flags)]):
                with self.assertRaises(ValueError):
                    v.require_xos("old", "new")

    def test_full_reference_replay_and_same_traffic(self):
        frozen = json.loads((ROOT / v.BASE).read_text())
        reference = frozen["arms"]["candidate"]
        candidate = deepcopy(reference)
        candidate[5]["cycles"] += 100
        self.assertEqual(len(v.compare(reference, candidate, frozen)), 12)
        changed = deepcopy(reference)
        changed[5]["cycles"] += 1
        with self.assertRaises(ValueError):
            v.compare(changed, candidate, frozen)

    def test_no_performance_threshold_or_traffic_omission(self):
        frozen = json.loads((ROOT / v.BASE).read_text())
        reference = frozen["arms"]["candidate"]
        candidate = deepcopy(reference)
        for row in candidate:
            row["cycles"] *= 2
        v.compare(reference, candidate, frozen)
        candidate[5]["pma_requests"] -= 1
        with self.assertRaises(ValueError):
            v.compare(reference, candidate, frozen)
        with self.assertRaises(ValueError):
            v.compare(reference, reference[:-1], frozen)

    def test_production_compile_not_a_test_depth(self):
        command = compile_command(Path("/integration"), Path("/output/production"))
        self.assertIn("-DGRASU_REGRAPH_CROSS_ROW_PIPELINE=1", command)
        self.assertNotIn("--link", command)
        self.assertEqual(command[command.index("--kernel_frequency") + 1], "150")
        self.assertFalse(any("TEST" in arg for arg in command))

    def test_portable_raw_admission_keeps_regressions(self):
        report = verify(EVIDENCE)
        self.assertEqual(report, json.loads((EVIDENCE / "results.json").read_text()))
        cases = report["comparison"]
        self.assertGreater(cases[8]["candidate_cycles"], cases[8]["reference_cycles"])
        self.assertLess(cases[5]["candidate_cycles"], cases[5]["reference_cycles"])
        self.assertFalse(report["FPGA_timing_admitted"])
        self.assertFalse(report["simulator_modified"])

    def test_sealed_package_mutations_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "evidence"
            shutil.copytree(EVIDENCE, copy)
            for name in ("results.json", "raw_cross_row.tar.gz"):
                path = copy / name
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.subTest(name=name), self.assertRaises(ValueError):
                    verify(copy)
                path.write_bytes(original)

    def test_raw_changes_rejected_even_without_outer_seal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with tarfile.open(EVIDENCE / "raw_cross_row.tar.gz", "r:gz") as bundle:
                bundle.extractall(root, filter="data")
            run = root / "run"
            manifest = json.loads((run / "manifest.json").read_text())
            source = next(row for row in manifest["source_copies"]
                          if row["archive_path"].endswith("cross_row_pipeline.hpp"))
            for path in (run / source["archive_path"], run / "production/adapter.hw.xo",
                         run / "candidate/simulate.stdout.txt"):
                original = path.read_bytes()
                altered = (original.replace(b"cycles=6 ", b"cycles=7 ", 1)
                           if path.name == "simulate.stdout.txt" else original + b"changed")
                self.assertNotEqual(altered, original)
                path.write_bytes(altered)
                with self.subTest(path=path.name), self.assertRaises(ValueError):
                    recheck(run)
                path.write_bytes(original)
            path = run / "production/compile.resources.json"
            original = json.loads(path.read_text())
            path.write_text(json.dumps(original | {"reserve_gib": 0}))
            with self.assertRaises(ValueError):
                recheck(run)


if __name__ == "__main__":
    unittest.main()
