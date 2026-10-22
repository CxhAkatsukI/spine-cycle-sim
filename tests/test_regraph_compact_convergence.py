"""Complete-state, trajectory and bounded parallel admission for compact R."""

import copy
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import compact_analysis as analysis
from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import prefetch_convergence, runtime
from tests.test_regraph_bank_stream_comparison import fixture as bank_fixture


def fixture():
    reference, _ = bank_fixture()
    old = {(r["latency"], r["reverse"], r["arm"]): r for r in reference}
    rows = []
    for latency, reverse, arm in analysis.MATRIX:
        row = copy.deepcopy(old[(latency, reverse, "bank_stream" if arm == "prefetch_compact" else arm)])
        row["arm"] = row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]:
            part["arm"] = arm
        rows.append(row)
    return rows, reference


class CompactConvergenceTests(unittest.TestCase):
    def test_logical_state_matches_despite_different_replica_names_and_counts(self):
        rows, reference = fixture()
        self.assertNotEqual(rows[0]["outputs"], rows[2]["outputs"])
        for row in rows:
            if row["arm"] == "prefetch_compact":
                row["observations"]["result"]["cycles"] *= 2
                for part in row["observations"]["trajectory"]: part["cycles"] *= 2
        result = analysis.summarize(rows, reference)
        self.assertEqual(result["legacy_rows_replayed_exactly"], 8)
        self.assertFalse(result["retention_pass"])
        for field in ("hardware_timing_admitted", "publication_match_admitted",
                      "strict_resource_match_admitted", "production_baseline_admitted",
                      "new_spine_comparison_executed"):
            self.assertIs(result[field], False)

    def test_missing_duplicate_or_reordered_rows_and_reference_rejected(self):
        rows, reference = fixture()
        for changed in (rows[:-1], rows[:-1] + rows[:1], rows[::-1]):
            with self.subTest(), self.assertRaisesRegex(ValueError, "twelve-row"):
                analysis.summarize(changed, reference)
        with self.assertRaisesRegex(ValueError, "32-row"):
            analysis.summarize(rows, reference[:-1])

    def test_legacy_counter_drift_and_registration_order_rejected(self):
        for arm, message in (("bank_stream", "legacy"), ("prefetch_compact", "registration")):
            rows, reference = fixture()
            row = next(row for row in rows if row["arm"] == arm)
            row["observations"]["result"]["read_bytes"] += 64
            with self.subTest(arm=arm), self.assertRaisesRegex(ValueError, message):
                analysis.summarize(rows, reference)

    def test_missing_extra_or_corrupt_replica_rejected(self):
        for kind in ("missing", "extra", "name", "hash", "length", "count"):
            rows, reference = fixture()
            for row in rows:
                if row["arm"] != "prefetch_compact":
                    continue
                outputs = row["outputs"]
                if kind == "missing": outputs.pop()
                elif kind == "extra": outputs.append(copy.deepcopy(outputs[0]))
                elif kind == "name": outputs[0]["name"] = "renamed"
                elif kind == "hash": outputs[0]["sha256"] = "changed"
                elif kind == "length": outputs[0]["bytes"] += 4
                else: row["observations"]["result"]["replicas"] -= 1
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "replicas"):
                analysis.summarize(rows, reference)

    def test_changed_common_state_or_active_trajectory_rejected(self):
        for kind in ("state", "trajectory"):
            rows, reference = fixture()
            for row in rows:
                if row["arm"] != "prefetch_compact": continue
                if kind == "state":
                    for output in row["outputs"]: output["sha256"] = "different"
                else: row["observations"]["trajectory"][0]["active"] += 1
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "semantics"):
                analysis.summarize(rows, reference)

    def test_unclosed_cycles_nonconvergence_wrong_arm_and_negative_traffic_rejected(self):
        for kind in ("cycles", "active", "arm", "traffic"):
            rows, reference = fixture()
            for row in rows:
                if row["arm"] != "prefetch_compact": continue
                observation = row["observations"]
                if kind == "cycles": observation["result"]["cycles"] += 1
                elif kind == "active": observation["trajectory"][-1]["active"] = 1
                elif kind == "arm": observation["result"]["arm"] = "bank_stream"
                else: observation["result"]["read_bytes"] = -1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                analysis.summarize(rows, reference)

    def test_parallel_profile_reserves_all_workers_parent_and_live_reserve(self):
        selected = runtime.settings(runtime.LOCAL_PARALLEL, 4)
        self.assertEqual(selected["high_gib"], 18)
        self.assertEqual(selected["policy"], dict(tree_memory_gib=20, reserve_gib=24,
            background_memory_gib=8, allow_bounded_builds=True))
        self.assertEqual(runtime.high_memory.required_bytes(selected["policy"], []), 52 * 1024**3)
        for workers in (0, 1, 5, True):
            with self.subTest(workers=workers), self.assertRaises(ValueError):
                runtime.settings(runtime.LOCAL_PARALLEL, workers)
        with self.assertRaises(ValueError): runtime.settings(runtime.LOCAL, 4)

    def test_affinity_rejects_duplicate_disallowed_and_unbounded_workers(self):
        with patch.object(prefetch_convergence.os, "sched_getaffinity", return_value={1, 2, 3, 4}):
            prefetch_convergence.validate_cpus([1, 2, 3, 4])
            for cpus in ([], [1, 1], [0], [1, 2, 3, 4, 5], [True]):
                with self.subTest(cpus=cpus), self.assertRaises(ValueError):
                    prefetch_convergence.validate_cpus(cpus)


if __name__ == "__main__":
    unittest.main()
