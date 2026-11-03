import tempfile
import unittest
from pathlib import Path

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.resident_oracles import compare


class ResidentOracleTest(unittest.TestCase):
    def compare(self, spine, gr, vertices=1):
        with tempfile.TemporaryDirectory() as directory:
            left = Path(directory) / "spine.tsv"
            right = Path(directory) / "gr.tsv"
            left.write_text(spine)
            right.write_text(gr)
            return compare(left, right, vertices)

    def test_compares_vertex_identity_and_state(self):
        report = self.compare("0\t1\t0.5\t0.25\t0.75\t0\t1\n",
                              "1\t1\t0.5\t0\t0.5\t0\t0\n")
        self.assertEqual(report["claim_class"], "cpu_reference_only")
        self.assertEqual(report["degree_mismatch_vertices"], 1)
        self.assertEqual(report["active_mismatch_vertices"], 1)
        self.assertEqual(report["arm_totals"]["spine"]["old_sinks"], 1)
        self.assertEqual(report["state_errors"]["final_rank"],
                         {"l1": 0.25, "max_abs": 0.25})

    def test_rejects_missing_or_nonfinite_vertices(self):
        row = "0\t1\t0.5\t0\t0.5\t0\t0\n"
        with self.assertRaisesRegex(ValueError, "vertex count"):
            self.compare(row, "")
        with self.assertRaisesRegex(ValueError, "non-finite"):
            self.compare(row, row.replace("0.5", "NaN"))
