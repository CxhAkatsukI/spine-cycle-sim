"""Gather reuse changes scheduling, not physical work or legacy observations."""

from copy import deepcopy
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import (
    gather_reuse, prefetch_convergence, runtime, software_compatibility)
from tests.test_regraph_wrapper_schedule import fixture as wrapper_fixture


def fixture():
    before, reference, _ = wrapper_fixture()
    indexed = {gather_reuse.elastic_analysis.identity(row): row for row in before}
    rows = []
    for latency, reverse, arm in gather_reuse.MATRIX:
        previous_arm = gather_reuse.ARMS[1] if arm == gather_reuse.ARMS[2] else arm
        row = deepcopy(indexed[(latency, reverse, previous_arm)])
        row["arm"] = row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]:
            part["arm"] = arm
        rows.append(row)
    return before, rows, reference


class GatherReuseTests(unittest.TestCase):
    def matrix(self):
        before, current, _ = fixture()
        return before, current

    def test_complete_matrix_old_replay_and_unchanged_traffic(self):
        before, rows = self.matrix()
        result = gather_reuse.summarize(rows, [], before=before)
        self.assertEqual(result["pre_edit_controls_replayed_exactly"], 8)
        self.assertTrue(result["retention_pass"])
        self.assertFalse(result["production_baseline_admitted"])
        self.assertEqual(result["physical_masters"]["prefetch_gather_reuse"], 16)

    def test_missing_row_or_legacy_drift_is_rejected(self):
        before, rows = self.matrix()
        with self.assertRaises(ValueError):
            gather_reuse.summarize(rows[:-1], [], before=before)
        rows[0]["observations"]["result"]["cycles"] += 1
        with self.assertRaises(ValueError):
            gather_reuse.summarize(rows, [], before=before)

    def test_candidate_cannot_drop_physical_reads_or_writes(self):
        before, rows = self.matrix()
        for field in ("read_bytes", "write_bytes"):
            changed = deepcopy(rows)
            for row in changed:
                if row["arm"] == gather_reuse.ARMS[2]:
                    row["observations"]["result"][field] -= 1
            with self.assertRaisesRegex(ValueError, "traffic"):
                gather_reuse.summarize(changed, [], before=before)

    def test_fresh_cpu_profile_is_explicit_bounded_and_not_core_reuse(self):
        selected = prefetch_convergence.execution_profile(None, [0, 1, 2, 3], runtime.FRESH_CPU)
        self.assertEqual(selected["policy"]["tree_memory_gib"], 6)
        self.assertEqual(selected["policy"]["reserve_gib"], 24)
        self.assertEqual(selected["high_gib"], 5)
        with self.assertRaises(ValueError):
            prefetch_convergence.execution_profile({}, [0], runtime.FRESH_CPU)
        with self.assertRaises(ValueError):
            runtime.settings(runtime.FRESH_CPU, 5)

    def test_sst_build_cannot_select_cached_or_unknown_profiles(self):
        for profile in (runtime.CACHED_LOCAL, runtime.CPU_ONLY, "unknown"):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, "fresh-build"):
                software_compatibility.run(None, None, None, memory_profile=profile)


if __name__ == "__main__":
    unittest.main()
