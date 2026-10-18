import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages import sst_candidate
from spine_cycle_sim.experiments.sharded_k4_stages.bank_stream import model_contract as contract

ROOT = Path(__file__).resolve().parents[1]


class BankStreamProfileTests(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / contract.PROFILE_PATH
        self.raw = json.loads(self.path.read_text())
        self.profile = sst_candidate.load_profile(ROOT, self.path)

    def test_explicit_topology_and_no_old_measurement_identity(self):
        self.assertEqual(self.profile["memory"]["physical_master_count"], 7)
        self.assertEqual(self.profile["memory"]["worker_source_services"], [0, 1, 0, 1])
        self.assertEqual(self.profile["memory"]["source_service_channels"], [23, 24])
        self.assertEqual(set(self.profile["target"]), {
            "integration_revision", "production_source_index_sha256", "hls_sources"})
        self.assertEqual(self.profile["status"], "source_bound_prediction_not_hardware_calibrated")
        self.assertTrue(self.profile["fixed_model"]["bank_stream_schedule"]["bank_read_beats"])

    def test_rejects_schedule_source_topology_boundary_and_implicit_drift(self):
        for section, key, value in (
            ("bank_stream_schedule", "bank_fifo_lines", 128),
            ("bank_stream_schedule", "bank_read_beats", False),
            ("memory_overrides", "physical_master_count", 9),
            ("target", "integration_revision", "different"),
        ):
            invalid = copy.deepcopy(self.raw)
            invalid[section][key] = value
            with self.assertRaises(ValueError):
                contract.expand(ROOT, invalid)
        for key, value in (("boundary", "setup-inclusive"), ("status", "calibrated"),
                           ("unexpected", 1)):
            with self.assertRaises(ValueError):
                contract.expand(ROOT, {**self.raw, key: value})

    def test_basis_hash_rejected(self):
        from spine_cycle_sim.experiments.campaign_runtime import sha256_file
        basis_path = ROOT / self.raw["timing_basis"]["path"]
        with patch.object(contract, "sha256_file", side_effect=lambda path:
                          "changed" if path == basis_path else sha256_file(path)):
            with self.assertRaisesRegex(ValueError, "timing basis"):
                contract.expand(ROOT, self.raw)

    def test_parameters_are_candidate_only(self):
        config = {"profile": str(self.path), "arm": "candidate", "max_cycles": 100,
                  "fixture": "/fixture", "output": "/output", "dram_output": "/dram"}
        params = sst_candidate.component_parameters(ROOT, config)
        self.assertEqual(params["profile_id"], contract.PROFILE_ID)
        for key in ("bank_stream_model", "cross_row_pipeline", "row_line_read",
                    "row_prefetch", "stop_after_last", "independent_read_write", "routed_stream_depths"):
            self.assertEqual(params[key], 1)
        for key in ("row_line_model", "cross_row_model", "routed_empty_exit"):
            self.assertNotIn(key, params)
        with self.assertRaisesRegex(ValueError, "candidate-only"):
            sst_candidate.component_parameters(ROOT, {**config, "arm": "original"})

    def test_hls_input_and_implementation_sources_are_all_checked(self):
        hashes = {**{"include/" + name: sha for name, sha in self.profile["input_export"].items()},
                  **self.profile["target"]["hls_sources"]}
        integration = Path("/frozen-integration")
        for failed in (None, *self.profile["target"]["hls_sources"]):
            with patch.object(sst_candidate, "sha256_file", side_effect=lambda path:
                              hashes[path.relative_to(integration).as_posix()]), \
                    patch.object(contract, "sha256_file", side_effect=lambda path:
                                 "changed" if path.relative_to(integration).as_posix() == failed else
                                 hashes[path.relative_to(integration).as_posix()]):
                if failed:
                    with self.assertRaises(ValueError):
                        sst_candidate.require_export_headers(integration, self.profile)
                else:
                    self.assertEqual(len(sst_candidate.require_export_headers(integration, self.profile)), 12)
        for name in self.profile["input_export"]:
            with patch.object(sst_candidate, "sha256_file", side_effect=lambda path:
                              "changed" if path.name == name else
                              hashes[path.relative_to(integration).as_posix()]):
                with self.assertRaisesRegex(ValueError, name):
                    sst_candidate.require_export_headers(integration, self.profile)

    def test_all_legacy_profiles_stay_explicitly_four_source_readers(self):
        for version in range(1, 5):
            profile = sst_candidate.load_profile(ROOT, ROOT / (
                f"configs/architectures/grasu_regraph_routed_sssp_compute_v{version}.json"))
            self.assertEqual(profile["memory"]["physical_master_count"], 9)
            self.assertNotIn("bank_stream_schedule", profile["fixed_model"])


if __name__ == "__main__":
    unittest.main()
