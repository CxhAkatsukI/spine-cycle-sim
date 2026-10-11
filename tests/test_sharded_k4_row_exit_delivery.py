"""Empty-exit model acceptance must not substitute timing agreement for correctness."""

import copy
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_exit_delivery import compare_payloads


def payload():
    return {"success": True, "done": True, "ledger_closed": True, "replicas_equal": True,
            "vertices": 16, "partitions": 1, "pma_slots": 32, "live_edges_per_round": 4,
            "expected_rounds": 2, "backend_reads": {"bytes": 1024}, "backend_writes": {"bytes": 64},
            "boundary": "resident", "evidence": "prediction",
            "counters": {"start_cycle": 0, "end_cycle": 1000, "axi_requests": 17,
                         "axi_completions": 17, "axi_beats": 17, "axi_completed_beats": 17},
            "rounds": [{"start": 0, "end": 500, "active_vertices": 1},
                       {"start": 500, "end": 1000, "active_vertices": 0}]}


class EmptyExitDeliveryTests(unittest.TestCase):
    def test_new_cycles_allowed_not_new_work(self):
        before = payload()
        after = copy.deepcopy(before)
        after["counters"]["end_cycle"] = 1900
        after["rounds"][1]["end"] = 1900
        compare_payloads(before, after)

    def test_semantic_or_traffic_changes_rejected(self):
        changes = [lambda p: p.update(success=False), lambda p: p.update(done=False),
                   lambda p: p.update(ledger_closed=False), lambda p: p.update(replicas_equal=False),
                   lambda p: p.update(vertices=17), lambda p: p.update(expected_rounds=3),
                   lambda p: p["backend_reads"].update(bytes=512),
                   lambda p: p["counters"].update(axi_completions=16),
                   lambda p: p["counters"].update(axi_completed_beats=16),
                   lambda p: p["rounds"][0].update(active_vertices=2),
                   lambda p: p["rounds"][1].update(active_vertices=1)]
        for change in changes:
            before = payload()
            after = copy.deepcopy(before)
            change(after)
            with self.subTest(change=change), self.assertRaises(ValueError):
                compare_payloads(before, after)


if __name__ == "__main__":
    unittest.main()
