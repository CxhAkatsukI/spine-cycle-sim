"""Keep endpoint, physical-master and bank identities distinct."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.a4_control import resources

ROOT = Path(__file__).resolve().parents[1]


class CrossRowA4ResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = resources.audit(ROOT)

    def test_complete_raw_matrix_precedes_resource_admission(self):
        self.assertEqual(self.result["status"], "audited_diagnostic_not_strict_resource_match")
        resources.require_claim(self.result, "integrated_path_diagnostic")
        for claim in ("strict_resource_match", "isolated_adapter_overhead", "FPGA_timing",
                      "published_performance_match", "update_to_convergence", "unknown"):
            with self.subTest(claim=claim), self.assertRaisesRegex(ValueError, "does not admit"):
                resources.require_claim(self.result, claim)

    def test_K4_has_four_source_masters_not_two(self):
        ports = self.result["endpoint_bindings"]["cross_row"]
        source = [p for p in ports if p["name"].startswith("source")]
        self.assertEqual(len(ports), 9)
        self.assertEqual([p["channel"] for p in source], [23, 24, 23, 24])
        self.assertEqual([p["direction"] for p in source], ["read_write", "read_write", "read", "read"])
        self.assertTrue(all(p["independent_read_write"] for p in source))
        self.assertFalse(ports[-1]["independent_read_write"])

    def test_original_model_endpoints_are_not_physical_master_count(self):
        counts = self.result["interface_counts"]
        self.assertEqual(counts, {"original_synthesized_physical": 9, "original_modeled_endpoints": 13,
                                  "K4_modeled_physical": 9, "K4_source_masters": 4, "K4_source_banks": 2})
        ports = self.result["endpoint_bindings"]["original"]
        self.assertEqual(len(ports), 13)
        for worker in range(4):
            pair = [p for p in ports if p["name"] in (f"source{worker}", f"state_write{worker}")]
            self.assertEqual([p["channel"] for p in pair], [worker * 2 + 1] * 2)
            self.assertEqual([p["direction"] for p in pair], ["read", "write"])
        self.assertIn("not a shared", self.result["credit_interpretation"])

    def test_publication_counts_retain_all_replicas_and_status(self):
        self.assertEqual(self.result["publication_bytes_per_round"],
                         {"original": 262144 * 4 * 4, "cross_row": 262144 * 4 * 3 + 4})

    def test_common_clock_does_not_hide_unmatched_capacity(self):
        self.assertEqual(self.result["common"]["clock_mhz"], 150)
        self.assertEqual(self.result["common"]["rounds"], 1)
        self.assertEqual(len(self.result["unmatched"]), 6)
        ports = self.result["endpoint_bindings"]
        self.assertEqual({p["parent_credits"] for p in ports["original"]}, {2})
        self.assertEqual({p["parent_credits"] for p in ports["cross_row"]}, {16})

    def test_source_drift_requires_new_review(self):
        path = ROOT / resources.DIRECTORY / "evidence/verification.json"
        index = json.loads(path.read_text())
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            for relative in resources.SOURCES:
                target = copy / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / relative).read_bytes())
            self.assertEqual(resources.source_pins(copy, index), self.result["sources"])
            target = copy / resources.SOURCES[0]
            target.write_bytes(target.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "source changed; review required"):
                resources.source_pins(copy, index)

    def test_symlinked_resource_source_is_not_accepted(self):
        index = json.loads((ROOT / resources.DIRECTORY / "evidence/verification.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            path = copy / resources.SOURCES[0]
            path.parent.mkdir(parents=True)
            path.symlink_to(ROOT / resources.SOURCES[0])
            with self.assertRaisesRegex(ValueError, "source changed; review required"):
                resources.source_pins(copy, index)

    def test_changed_AXI_interface_capacity_is_rejected(self):
        evidence = json.loads((ROOT / resources.ORIGINAL_AXI).read_text())
        self.assertEqual(resources.original_physical_interfaces(evidence), 9)
        changed = deepcopy(evidence)
        changed["axi_interface_evidence"][1]["parameters"]["NUM_READ_OUTSTANDING"][0] = 32
        with self.assertRaisesRegex(ValueError, "geometry differs"):
            resources.original_physical_interfaces(changed)

    def test_evidence_pin_cannot_be_replaced_by_a_new_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "evidence identity differs"):
                resources.checked_json(path.parent, Path(path.name), resources.INDEX_SHA)

    def test_committed_audit_is_recomputed_not_trusted(self):
        stored = json.loads((ROOT / resources.DIRECTORY / "resource_audit.json").read_text())
        self.assertEqual(stored, self.result)


if __name__ == "__main__":
    unittest.main()
