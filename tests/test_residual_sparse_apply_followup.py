"""Reject hidden model/input/state changes in the sparse Apply comparison."""

import copy
import json
import struct
import unittest

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm import sparse_apply_followup as study
from test_residual_propagation_followup import fixture


def controls():
    previous = fixture()
    for row in previous["rows"]:
        for arm in ("spine", "gr"):
            row[arm]["evidence"] = row["dataset"] + "_" + arm
    dense = copy.deepcopy(previous)
    dense["model"].update(spine_residual_apply="dense", apply_evidence="control")
    sparse = copy.deepcopy(previous)
    sparse["model"].update(spine_residual_apply="dirty-bitmap", apply_evidence="candidate")
    for row in sparse["rows"]:
        row["spine"]["cycles"] = 50
    return previous, dense, sparse


def reader(sparse=False):
    def read(name):
        if name.endswith("rounds.csv"):
            return b"round,start,end,active_in,reader_sources,active_out\n0,0,100,2,2,0\n"
        if name.endswith("-in.u32le"):
            return struct.pack("<II", 0, 1)
        if name.endswith("-out.u32le"):
            return b""
        if name.endswith("stdout.txt"):
            trace = dict(dirty_bitmap=int(sparse), vertices_applied=3 if sparse else 100,
                sparse_vertices_applied=3 if sparse else 0, bitmap_clear_cycles=1 if sparse else 0,
                bitmap_read_cycles=1 if sparse else 0, bitmap_marks=10 if sparse else 0,
                bitmap_storage_bytes=8 if sparse else 0, dense_fallback_tiles=0)
            return ("APPLY_TRACE " + json.dumps(trace) + "\nPROPAGATION_TRACE " +
                json.dumps(dict(computed_edges=10, nonempty_rounds=1))).encode()
        return struct.pack("<10f", *([0.0] * 10))
    return read


class SparseApplyFollowupTests(unittest.TestCase):
    def compare(self, reports=None, sparse_read=None):
        return study.compare(*(reports or controls()), reader(), reader(), sparse_read or reader(True))

    def test_identical_work_and_states_allow_a_candidate_speedup(self):
        summary = self.compare()
        self.assertFalse(summary["baseline_admitted"])
        self.assertTrue(summary["dense_default_equivalent"])
        self.assertEqual([r["sparse_speedup_gr_over_spine"] for r in summary["rows"]], [2] * 3)

    def test_remaining_loss_is_not_hidden(self):
        reports = controls()
        for row in reports[2]["rows"]:
            row["spine"]["cycles"] = 200
        self.assertEqual([r["sparse_speedup_gr_over_spine"] for r in self.compare(reports)["rows"]], [0.5] * 3)

    def test_changed_default_or_gr_cannot_be_sealed(self):
        reports = controls()
        reports[1]["rows"][0]["spine"]["cycles"] += 1
        with self.assertRaisesRegex(ValueError, "default dense"):
            self.compare(reports)
        reports = controls()
        reports[2]["rows"][0]["gr"]["cycles"] += 1
        with self.assertRaisesRegex(ValueError, "G\\+R changed"):
            self.compare(reports)

    def test_wrong_state_threshold_or_batch_is_rejected(self):
        def corrupt(name):
            return b"different residual" if name.endswith("residual.u32le") else reader(True)(name)
        with self.assertRaisesRegex(ValueError, "full numerical state"):
            self.compare(sparse_read=corrupt)
        reports = controls()
        reports[2]["model"]["residual_epsilon"] *= 2
        with self.assertRaisesRegex(ValueError, "non-Apply"):
            self.compare(reports)
        reports = controls()
        reports[2]["matrix"][0]["updates"] += 1
        with self.assertRaisesRegex(ValueError, "identical predeclared"):
            self.compare(reports)

    def test_untimed_bitmap_cannot_be_sealed(self):
        def corrupt(name):
            return reader(True)(name).replace(b'"bitmap_clear_cycles": 1', b'"bitmap_clear_cycles": 0')
        with self.assertRaisesRegex(ValueError, "finite timed bitmap"):
            self.compare(sparse_read=corrupt)

    def test_tiny_residual_differences_are_reported_not_bitwise_equivalence(self):
        def changed(name):
            if "_spine/" in name and name.endswith("residual.u32le"):
                return struct.pack("<10f", 1e-14, *([0.0] * 9))
            return reader(True)(name)
        rows = self.compare(sparse_read=changed)["rows"]
        self.assertTrue(all(not r["residual_words_identical"] for r in rows))
        self.assertTrue(all(r["residual_differing_words"] == 1 for r in rows))
        def large(name):
            if "_spine/" in name and name.endswith("residual.u32le"):
                return struct.pack("<10f", 5e-7, *([0.0] * 9))
            return reader(True)(name)
        with self.assertRaisesRegex(ValueError, "FP32 comparison tolerance"):
            self.compare(sparse_read=large)

    def test_frontier_counts_cannot_hide_changed_vertices(self):
        def changed(name):
            return struct.pack("<II", 0, 2) if name.endswith("-in.u32le") else reader(True)(name)
        with self.assertRaisesRegex(ValueError, "frontier vertex sets"):
            self.compare(sparse_read=changed)

    def test_changed_order_is_visible_but_not_a_changed_frontier_set(self):
        def reordered(name):
            return struct.pack("<II", 1, 0) if name.endswith("-in.u32le") else reader(True)(name)
        self.assertTrue(all(r["frontier_order_changed_lists"] == 1 for r in self.compare(sparse_read=reordered)["rows"]))


if __name__ == "__main__":
    unittest.main()
