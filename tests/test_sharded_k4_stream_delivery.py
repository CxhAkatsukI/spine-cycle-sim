"""A stream-capacity timing change cannot hide changed workload or traffic."""

import copy
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.stream_delivery import compare_stream_results
from spine_cycle_sim.experiments.sharded_k4_stages.sst_candidate import INDEPENDENT_PROFILE_ID, STREAM_PROFILE_ID


def result():
    return {"profile_id": INDEPENDENT_PROFILE_ID, "success": True, "done": True,
            "ledger_closed": True, "replicas_equal": True, "vertices": 5,
            "partitions": 1, "pma_slots": 16, "live_edges_per_round": 4,
            "expected_rounds": 2, "rounds": [{"active_vertices": 1}, {"active_vertices": 0}],
            "boundary": "resident", "evidence": "prediction", "backend_reads": 8, "backend_writes": 2,
            "counters": {"axi_requests": 4, "axi_completions": 4, "axi_beats": 10,
                         "axi_completed_beats": 10, "start_cycle": 0, "end_cycle": 100}}


class StreamDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.parent = result()
        self.replay = copy.deepcopy(self.parent)
        self.corrected = copy.deepcopy(self.parent)
        self.corrected["profile_id"] = STREAM_PROFILE_ID
        self.corrected["counters"]["end_cycle"] = 80

    def test_timing_change_admitted_only_with_exact_replay_and_traffic(self):
        report = compare_stream_results(self.parent, self.replay, self.corrected)
        self.assertEqual(report["v3_over_v2_cycles"], 0.8)
        self.assertTrue(report["non_timing_counters_equal"])
        self.assertEqual(report["ignored_result_fields"], [])

    def test_replay_cannot_change_even_timing(self):
        self.replay["counters"]["end_cycle"] += 1
        with self.assertRaises(ValueError):
            compare_stream_results(self.parent, self.replay, self.corrected)

    def test_rejects_hidden_changes_and_incomplete_results(self):
        changes = [lambda r: r.update(profile_id=INDEPENDENT_PROFILE_ID),
                   lambda r: r.update(done=False), lambda r: r.update(replicas_equal=False),
                   lambda r: r.update(vertices=6), lambda r: r.update(expected_rounds=3),
                   lambda r: r.update(backend_reads=9), lambda r: r.update(boundary="other"),
                   lambda r: r["rounds"][0].update(active_vertices=2),
                   lambda r: r["rounds"][-1].update(active_vertices=1),
                   lambda r: r["counters"].update(end_cycle=0),
                   lambda r: r["counters"].update(axi_completions=3),
                   lambda r: r["counters"].update(axi_requests=5, axi_completions=5)]
        for index, mutate in enumerate(changes):
            changed = copy.deepcopy(self.corrected)
            mutate(changed)
            with self.subTest(index=index), self.assertRaises(ValueError):
                compare_stream_results(self.parent, self.replay, changed)


if __name__ == "__main__":
    unittest.main()
