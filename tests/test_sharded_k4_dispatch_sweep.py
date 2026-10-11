"""Dispatch gaps remain overlapping diagnostics, with bounded affinity arms."""

import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.dispatch_sweep import dispatch_metrics, validate_affinities


class DispatchSweepTests(unittest.TestCase):
    def test_strict_nested_available_unique_affinities(self):
        validate_affinities([[1], [1, 2], [1, 2, 3]], {1, 2, 3})
        for arms in ([[1], [1, 2]], [[1], [1, 2], [1, 2, 4]],
                     [[1], [1, 2], [1, 2, 2, 3]], [[1], [2], [1, 2, 3]],
                     [[], [1], [1, 2]]):
            with self.subTest(arms=arms), self.assertRaises(ValueError):
                validate_affinities(arms, {1, 2, 3})

    def test_queued_and_submit_are_distinct_from_invocation_gap(self):
        events = [dict(stage="adapter", round=0, worker=0, shard=0,
                       queued_ns=1, submit_ns=2, start_ns=3, end_ns=1000),
                  dict(stage="adapter", round=0, worker=0, shard=4,
                       queued_ns=5, submit_ns=3000, start_ns=4000, end_ns=5000)]
        result = dispatch_metrics(dict(compute_span_ms=1, events=events))
        group = result["groups"][0]
        self.assertEqual(group["same_worker_gap_sum_ms"], .003)
        self.assertEqual(group["gaps"][0]["submit_after_previous_end_ms"], .002)
        self.assertTrue(group["gaps"][0]["queued_before_previous_end"])
        self.assertNotIn("total_gap_penalty_ms", result)
        events[-1]["start_ns"] = 999
        with self.assertRaises(ValueError):
            dispatch_metrics(dict(compute_span_ms=1, events=events))


if __name__ == "__main__":
    unittest.main()
