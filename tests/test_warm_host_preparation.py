"""A partial CPU measurement must never become an inferred XRT/E2E result."""

import copy
import unittest

from spine_cycle_sim.experiments.evaluation_impact.warm_comparison import host_analysis
import test_warm_spine_comparison as warm_fixtures


class WarmHostTests(unittest.TestCase):
    def rows(self):
        warm = warm_fixtures.WarmComparisonTests().rows()
        for row in warm:
            row["input"].update(vertices=96, updates=[[0, 95, 1], [0, 94, 2], [0, 93, 3]])
        rows = [dict(workload=workload, repeat=repeat, result=dict(vertices=96,
            updates=[[0, 95, 1], [0, 94, 2], [0, 93, 3]], self_test=True, partition_vertices=65536,
            iterations_per_sample=1000, warmup_blocks=20, source_seed_count=1,
            spine_payload_bytes=48, gr_lane_allocation_bytes=32,
            spine_ns_per_batch=[100.0] * 100, gr_ns_per_batch=[200.0] * 100))
            for workload in ("smoke", "amazon") for repeat in range(7)]
        return rows, warm

    def test_partial_cpu_arithmetic_preserves_unknown_full_host_time(self):
        rows, warm = self.rows()
        comparisons = host_analysis.summarize(rows, warm)
        self.assertEqual(len(comparisons), 4)
        self.assertTrue(all(r["full_host_inclusive_speedup"] is None for r in comparisons))
        self.assertEqual(comparisons[0]["clock_mhz"], 150)
        self.assertEqual(comparisons[0]["partial_gap_gr_minus_spine_ns"], 100 / .15 - 50 / .15 + 100)
        self.assertEqual(comparisons[0]["break_even_extra_host_on"], "spine")

    def test_negative_result_not_hidden(self):
        rows, warm = self.rows()
        for row in warm:
            if row["arm"] == "spine":
                row["result"]["cycles"] = 200
        comparisons = host_analysis.summarize(rows, warm)
        self.assertTrue(all(r["break_even_extra_host_on"] == "gr" for r in comparisons))
        self.assertTrue(all(r["device_plus_partial_cpu_ratio"] < 1 for r in comparisons))

    def test_complete_process_matrix_and_all_samples_required(self):
        for mutation in (lambda rows: rows.pop(), lambda rows: rows[0].update(repeat=1),
                         lambda rows: rows[0]["result"].update(gr_ns_per_batch=[1.0] * 99),
                         lambda rows: rows[0]["result"].update(gr_ns_per_batch=[float("nan")] * 100)):
            rows, warm = self.rows()
            mutation(rows)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                host_analysis.summarize(rows, warm)

    def test_changed_input_and_abi_rejected(self):
        for key, value in (("updates", [[0, 94, 1]]), ("vertices", 97), ("partition_vertices", 131072),
                           ("source_seed_count", 2), ("spine_payload_bytes", 24), ("gr_lane_allocation_bytes", 24)):
            rows, warm = self.rows()
            rows[0]["result"][key] = copy.deepcopy(value)
            with self.subTest(key=key), self.assertRaises(ValueError):
                host_analysis.summarize(rows, warm)


if __name__ == "__main__":
    unittest.main()
