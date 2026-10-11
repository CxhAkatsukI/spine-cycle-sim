"""The real matrix must preserve v3 exactly and v4's logical work completely."""

import copy
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_exit_matrix import compare_real_results
from spine_cycle_sim.experiments.sharded_k4_stages.sst_candidate import EMPTY_EXIT_PROFILE_ID, STREAM_PROFILE_ID
from tests.test_sharded_k4_row_exit_delivery import payload


class EmptyExitMatrixTests(unittest.TestCase):
    def setUp(self):
        self.prior = {**payload(), "profile_id": STREAM_PROFILE_ID}
        self.replay = copy.deepcopy(self.prior)
        self.corrected = copy.deepcopy(self.prior)
        self.corrected.update(profile_id=EMPTY_EXIT_PROFILE_ID)
        self.corrected["counters"]["end_cycle"] = 1900

    def test_explicit_profile_and_only_time_change(self):
        result = compare_real_results(self.prior, self.replay, self.corrected)
        self.assertEqual(result["v4_over_v3_cycles"], 1.9)
        self.assertEqual(result["ignored_result_fields"], [])
        self.assertTrue(result["non_timing_counters_equal"])

    def test_any_replay_difference_rejected(self):
        self.replay["counters"]["end_cycle"] += 1
        with self.assertRaises(ValueError):
            compare_real_results(self.prior, self.replay, self.corrected)

    def test_profile_work_traffic_and_convergence_rejected(self):
        changes = [lambda r: r.update(profile_id=STREAM_PROFILE_ID),
                   lambda r: r.update(expected_rounds=3), lambda r: r.update(success=False),
                   lambda r: r["counters"].update(end_cycle=0),
                   lambda r: r["counters"].update(axi_completed_beats=12),
                   lambda r: r["backend_reads"].update(bytes=512),
                   lambda r: r["rounds"][-1].update(active_vertices=1)]
        for change in changes:
            result = copy.deepcopy(self.corrected)
            change(result)
            with self.subTest(change=change), self.assertRaises(ValueError):
                compare_real_results(self.prior, self.replay, result)


if __name__ == "__main__":
    unittest.main()
