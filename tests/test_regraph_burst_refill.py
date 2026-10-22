"""A request-grouping optimization cannot skip traffic or admit full R."""

from copy import deepcopy
import json
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import (
    burst_refill_analysis as analysis, prefetch_analysis)
from tests.test_regraph_reader_ports import cases as previous
from tests.test_regraph_prefetch_compact import reference


def cases():
    old = {(r["latency"], r["reverse"], r["ports"]): r["observations"] for r in previous()}
    rows = []
    for latency, reverse, ports, full in analysis.MATRIX:
        obs = deepcopy(old[latency, reverse, ports])
        if full:
            obs.update(schema_version=4, refill_policy="full-burst",
                       physical_masters=4 * ports, masters_per_frontend=ports)
            for worker in obs["workers"]:
                worker.update(pma_requests=6, short_pma_requests=1)
        rows.append(dict(latency=latency, reverse=reverse, ports=ports,
                         full_burst=full, observations=obs))
    return rows


class BurstRefillTests(unittest.TestCase):
    def test_complete_comparison_does_not_admit_integrated_r(self):
        result = analysis.summarize(cases(), previous(), reference())
        self.assertEqual(result["pre_edit_rows_exact"], 8)
        self.assertEqual(len(result["rows"]), 4)
        self.assertFalse(result["integrated_r_retention_passed"])
        self.assertFalse(result["input_layout_changed"])
        self.assertEqual({r["physical_masters"] for r in result["rows"]}, {4, 8})

    def test_physical_resource_and_full_burst_policy_are_required(self):
        for key, value in (("physical_masters", 8), ("physical_masters", 4.0),
                ("masters_per_frontend", True), ("masters_per_frontend", 3),
                ("refill_policy", "eager"), ("refill_policy", None)):
            obs = deepcopy(cases()[1]["observations"])
            obs[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                prefetch_analysis.parse("PREFETCH_COMPACT " + json.dumps(obs))

    def test_short_parents_only_at_physical_bank_tails(self):
        for key, value in (("short_pma_requests", 5), ("short_pma_requests", -1),
                ("short_pma_requests", True), ("pma_requests", 0), ("pma_requests", 11),
                ("pma_requests", 0.5)):
            obs = deepcopy(cases()[1]["observations"])
            obs["workers"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                prefetch_analysis.parse("PREFETCH_COMPACT " + json.dumps(obs))

    def test_default_exact_and_candidate_traffic_conserved(self):
        for index, key, value in ((0, "cycles", 99), (1, "read_bytes", 2500),
                                  (1, "schema_version", 2), (1, "masters_per_frontend", 2)):
            rows = cases()
            rows[index]["observations"][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(ValueError):
                analysis.summarize(rows, previous(), reference())
        rows = cases()
        rows[1]["observations"]["workers"][0]["input_dummy"] += 1
        rows[1]["observations"]["workers"][0]["physical_slots"] += 1
        with self.assertRaisesRegex(ValueError, "per-shard"):
            analysis.summarize(rows, previous(), reference())

    def test_all_rows_both_orders_and_reference_required(self):
        for rows, before in ((cases()[:-1], previous()), (cases(), previous()[:-1])):
            with self.assertRaises(ValueError):
                analysis.summarize(rows, before, reference())
        rows = cases()
        rows[5]["observations"]["cycles"] += 1
        with self.assertRaisesRegex(ValueError, "registration"):
            analysis.summarize(rows, previous(), reference())


if __name__ == "__main__":
    unittest.main()
