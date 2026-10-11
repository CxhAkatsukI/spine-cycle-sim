"""Cross-version equality and admission gates for the AXI correction."""

import copy
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.channel_delivery import compare_channel_results
from spine_cycle_sim.experiments.sharded_k4_stages.sst_candidate import INDEPENDENT_PROFILE_ID


class ChannelResultTests(unittest.TestCase):
    def setUp(self):
        self.old = {"success": True, "done": True, "ledger_closed": True, "replicas_equal": True,
                    "profile_id": "grasu_regraph_routed_sssp_compute_v1", "vertices": 10,
                    "partitions": 1, "pma_slots": 16, "live_edges_per_round": 2, "expected_rounds": 1,
                    "counters": {"start_cycle": 0, "end_cycle": 100, "axi_requests": 3,
                                 "axi_completions": 3, "axi_beats": 4, "axi_completed_beats": 4}}
        self.new = copy.deepcopy(self.old)
        self.new["profile_id"] = INDEPENDENT_PROFILE_ID
        self.new["counters"]["end_cycle"] = 80

    def test_exact_replay_and_versioned_correction(self):
        report = compare_channel_results(self.old, copy.deepcopy(self.old), self.new)
        self.assertEqual(report["version_2_over_version_1_cycles"], 0.8)
        self.assertEqual(report["ignored_result_fields"], [])

    def test_replay_cannot_hide_any_field(self):
        replay = copy.deepcopy(self.old)
        replay["arbitration"] = {"stalls": 1}
        with self.assertRaisesRegex(ValueError, "full-result regression"):
            compare_channel_results(self.old, replay, self.new)

    def test_incomplete_or_different_corrected_run_rejected(self):
        for field, value in (("profile_id", "implicit"), ("done", False), ("ledger_closed", False),
                             ("replicas_equal", False), ("expected_rounds", 2), ("vertices", 11)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                compare_channel_results(self.old, self.old, {**self.new, field: value})
        broken = copy.deepcopy(self.new)
        broken["counters"]["axi_completed_beats"] = 0
        with self.assertRaisesRegex(ValueError, "does not conserve"):
            compare_channel_results(self.old, self.old, broken)


if __name__ == "__main__":
    unittest.main()
