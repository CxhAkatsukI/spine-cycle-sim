"""Recheck portable cross-row evidence and reject changed raw timing or state."""

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_archive import extracted
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.model_checkpoint import recheck, verify
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.model_delivery import CROSS_ROW
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.model_delivery import verify as verify_resident

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / ("docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/"
              "adapter_optimization/row_line/cross_row/model")


class CrossRowModelDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        record = json.loads((DOC / "evidence/verification.json").read_text())
        cls.context = extracted(DOC / "evidence/raw_checkpoint.tar.gz", record, max_bytes=256 * 1024**2)
        cls.evidence_root = cls.context.__enter__()
        cls.addClassCleanup(cls.context.__exit__, None, None, None)

    def reject(self, relative, mutate, pattern):
        path = self.evidence_root / relative
        original = path.read_bytes()
        try:
            path.write_bytes(mutate(original))
            with self.assertRaisesRegex(ValueError, pattern):
                recheck(self.evidence_root)
        finally:
            path.write_bytes(original)

    def test_portable_checkpoint_keeps_legacy_equality_and_timing_failures(self):
        result = verify(DOC / "evidence")
        self.assertEqual(result["core_executables_passed"], 27)
        self.assertEqual(len(result["legacy_cases"]), 5)
        self.assertTrue(all(row["equivalent"] and not row["changed_fields"] for row in result["legacy_cases"]))
        diagnostic = result["rtl_diagnostic"]
        self.assertEqual(len(diagnostic["rows"]), 24)
        self.assertFalse(diagnostic["all_rows_within_10_percent"])
        self.assertFalse(result["hardware_timing_admitted"])
        self.assertFalse(result["original_A4_comparison_complete"])

    def test_portable_resident_matrix_preserves_all_full_outputs(self):
        result = verify_resident(DOC / "resident_evidence", model=CROSS_ROW)
        self.assertEqual([row["id"] for row in result["rows"]], ["au", "su", "wk"])
        self.assertTrue(all(row["complete_external_state_equal"] and row["work_and_round_activity_equal"]
                            for row in result["rows"]))
        self.assertFalse(result["hardware_timing_admitted"])

    def test_raw_traffic_mutation_rejected(self):
        def mutate(data):
            lines = data.decode().splitlines()
            row = json.loads(lines[0])
            row["row_reads"] += 1
            lines[0] = json.dumps(row)
            return ("\n".join(lines) + "\n").encode()
        self.reject("timing/probe.stdout.txt", mutate, "traffic differs")

    def test_basis_pin_mutation_rejected(self):
        def mutate(data):
            manifest = json.loads(data)
            manifest["basis"]["sha256"] = "0" * 64
            return json.dumps(manifest).encode()
        self.reject("timing/manifest.json", mutate, "not pinned")

    def test_legacy_result_mutation_rejected(self):
        def mutate(data):
            result = json.loads(data)
            result["cycles"] += 1
            return json.dumps(result).encode()
        self.reject("legacy-after/cases/sssp_mixed_cold/result.json", mutate,
                    "legacy full-result equivalence differs")

    def test_changed_sealed_conclusion_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary)
            for name in ("results.json", "verification.json"):
                (copy / name).write_bytes((DOC / "evidence" / name).read_bytes())
            (copy / "results.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "sealed checkpoint conclusion"):
                verify(copy)


if __name__ == "__main__":
    unittest.main()
