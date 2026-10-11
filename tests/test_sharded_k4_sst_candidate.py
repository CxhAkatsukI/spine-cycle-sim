"""Version and timing-window gates for the distinct SST candidate."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.sst_candidate import component_parameters, load_profile
from spine_cycle_sim.experiments.sharded_k4_stages.sst_timing import timing_diagnostic

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "configs/architectures/grasu_regraph_routed_sssp_compute_v1.json"


class CandidateContractTests(unittest.TestCase):
    def test_explicit_entry_and_flags(self):
        config = {"profile": str(PROFILE), "fixture": "input.bin", "output": "out.json",
                  "dram_output": "dram", "max_cycles": 1000, "arm": "candidate"}
        self.assertEqual(component_parameters(ROOT, config)["row_prefetch"], 1)
        original = component_parameters(ROOT, {**config, "arm": "original"})
        self.assertEqual((original["row_prefetch"], original["stop_after_last"]), (0, 0))
        with self.assertRaises(ValueError):
            component_parameters(ROOT, {**config, "arm": "ideal"})
        with self.assertRaises(ValueError):
            component_parameters(ROOT, {**config, "max_cycles": 0})

    def test_legacy_profile_rejected(self):
        with self.assertRaises(ValueError):
            load_profile(ROOT, ROOT / "configs/architectures/grasu_regraph_sharded_k4_weighted_hls_v8.json")

    def test_silent_model_change_rejected(self):
        profile = json.loads(PROFILE.read_text())
        for mutation in (lambda p: p["fixed_model"].update(apply_latency=1),
                         lambda p: p.update(evidence_tier="hardware_validated"),
                         lambda p: p["memory"].update(sha256="bad"),
                         lambda p: p["memory"].update(axi_outstanding_per_master=32)):
            changed = copy.deepcopy(profile)
            mutation(changed)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "profile.json"
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    load_profile(ROOT, path)


class TimingDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.result = {"success": True, "ledger_closed": True, "replicas_equal": True,
                       "vertices": 129, "partitions": 1, "pma_slots": 16, "live_edges_per_round": 2,
                       "rounds": [{"start": 0, "end": 150000}],
                       "counters": {"start_cycle": 0, "end_cycle": 150000}}
        self.board = {"result": {"vertices": "129", "destination_partitions": "1", "executed_supersteps": "1",
                                  "pma_slots_total": "16", "final_edges": "2"},
                      "compute_span_ms": 2, "events": [{"round": 0, "start_ns": 100, "end_ns": 2000100}]}

    def test_near_total_is_not_calibration(self):
        diagnostic = timing_diagnostic(self.result, self.board)
        self.assertFalse(diagnostic["hardware_timing_admitted"])
        self.assertEqual(diagnostic["nominal_predicted_over_board_span"], 0.5)
        self.assertEqual(diagnostic["board_sum_round_spans_ms"], 2)

    def test_bad_functional_gate_rejected(self):
        for field in ("success", "ledger_closed", "replicas_equal"):
            with self.assertRaises(ValueError):
                timing_diagnostic({**self.result, field: False}, self.board)

    def test_mismatched_geometry_rejected(self):
        for field in ("vertices", "partitions", "pma_slots", "live_edges_per_round"):
            with self.assertRaises(ValueError):
                timing_diagnostic({**self.result, field: 999}, self.board)
        with self.assertRaises(ValueError):
            timing_diagnostic({**self.result, "rounds": []}, self.board)

    def test_missing_round_rejected(self):
        with self.assertRaises(ValueError):
            timing_diagnostic(self.result, {**self.board, "events": []})


if __name__ == "__main__":
    unittest.main()
