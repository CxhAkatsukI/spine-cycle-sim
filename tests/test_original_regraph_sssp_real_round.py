"""Admission and adversarial checks for the real-topology SSSP round control."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.analysis import (
    LATENCIES, MODES, REPLICAS, admit_matrix, admit_round,
)
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.preparation import (
    ACTIVE, INFINITY, distances, overlay, read_words, write_words,
)
from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.capture = self.root / "capture"
        self.capture.mkdir()
        # The nonidentity DBG permutation must be honored by both tasks and state.
        self.graph = SliceGraph("tiny", 3, (SliceRecord(0, 1, 3), SliceRecord(1, 2, 5)))
        for name, words in {
            "original_to_reordered": [2, 0, 1], "csr_offsets": [0, 1, 1, 2],
            "csr_destinations": [1, 0], "initial": [0] * 16, "degrees": [1, 0, 1] + [0] * 13,
            "tasks": [0, 1, 2, 0, 2, ACTIVE] + [ACTIVE, ACTIVE] * 5,
        }.items():
            write_words(self.capture / (name + ".u32le"), words)
        self.layout = {"summary": {"vertices": 3, "logical_edges": 2, "aligned_vertices": 16, "partitions": 1},
            "tasks": [{"kind": "dense", "partition": 0, "subpartition": 0, "kernel": 0,
                       "dst_offset": 0, "dst_len": 65536, "offset_words": 0, "words": 16}]}

    def test_exact_weight_overlay_and_author_padding(self):
        target = self.root / "cold"
        result = overlay(self.graph, self.capture, self.layout, target, "cold")
        self.assertEqual(result["root_reordered"], 2)
        self.assertEqual(read_words(target / "sssp_initial.u32le")[:3], [INFINITY, INFINITY, ACTIVE])
        words = read_words(target / "sssp_tasks.u32le")
        self.assertEqual(words[:6], [0, 1 | (5 << 19), 2, 3 << 19, 2, ACTIVE])
        self.assertEqual(read_words(target / "sssp_weights.u32le"), [5, 3])
        self.assertEqual((target / "tasks.u32le").read_bytes(), (self.capture / "tasks.u32le").read_bytes())

    def test_warm_state_converged_before_root_weight_change(self):
        target = self.root / "warm"
        result = overlay(self.graph, self.capture, self.layout, target, "warm_update")
        self.assertEqual(read_words(target / "sssp_initial.u32le")[:3], [19, 40, ACTIVE])
        self.assertEqual(read_words(target / "sssp_weights.u32le"), [21, 3])
        self.assertTrue(result["old_state_converged"])
        self.assertEqual(result["changed_weights"], 1)
        self.assertFalse(result["convergence_comparison"])

    def test_inactive_is_explicit_negative_not_update_correctness(self):
        target = self.root / "inactive"
        result = overlay(self.graph, self.capture, self.layout, target, "inactive")
        self.assertEqual(read_words(target / "sssp_initial.u32le")[:3], [19, 40, 0])
        self.assertEqual(result["active_initial"], 0)

    def test_reject_duplicate_pairs_and_invalid_mode(self):
        graph = SliceGraph("duplicate", 3, self.graph.records + self.graph.records[:1])
        with self.assertRaises(ValueError):
            overlay(graph, self.capture, self.layout, self.root / "bad", "cold")
        with self.assertRaises(ValueError):
            overlay(self.graph, self.capture, self.layout, self.root / "bad", "silent_warm")

    def test_reject_nonpermutation(self):
        path = self.capture / "original_to_reordered.u32le"
        path.unlink()
        write_words(path, [0, 0, 2])
        with self.assertRaises(ValueError):
            overlay(self.graph, self.capture, self.layout, self.root / "bad", "cold")

    def test_independent_dijkstra_handles_unreachable(self):
        self.assertEqual(distances(4, {(0, 1): 5, (0, 2): 20, (1, 2): 2}, 0), [0, 5, 7, INFINITY])


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in REPLICAS:
            write_words(self.root / (name + ".u32le"), [0] * 16)
        self.geometry = {"mode": "cold", "vertices": 3, "logical_edges": 2, "padded_vertices": 16}
        self.rows = [
            {"path": "a4", "passed": True, "full_state_and_traffic_pass": True, "cycles": 100,
             "read_bytes": 128, "write_bytes": 256, "active_vertices": 1,
             "physical_edges": 8, "dummy_edges": 6, "checked_words_per_replica": 16, "replicas": 4},
            {"path": "actual_k4", "passed": True, "full_state_and_traffic_pass": True, "cycles": 200,
             "read_bytes": 128, "write_bytes": 196, "active_vertices": 1,
             "live_edges": 2, "checked_words_per_replica": 16, "replicas": 3},
        ]

    def stdout(self, rows=None):
        return "\n".join("REAL_ROUND " + json.dumps(r) for r in (rows or self.rows))

    def test_complete_replicas_required_and_ratio_is_diagnostic(self):
        result = admit_round(self.stdout(), self.root, self.geometry)
        self.assertEqual(result["k4_over_a4_cycles_diagnostic_only"], 2)
        self.assertFalse(result["hardware_timing_admitted"])
        path = self.root / "k4_source1.u32le"
        path.unlink()
        write_words(path, [1] + [0] * 15)
        with self.assertRaises(ValueError):
            admit_round(self.stdout(), self.root, self.geometry)

    def test_reject_missing_path_and_wrong_traffic(self):
        with self.assertRaises(ValueError):
            admit_round(self.stdout(self.rows[:1]), self.root, self.geometry)
        self.rows[1]["write_bytes"] += 64
        with self.assertRaises(ValueError):
            admit_round(self.stdout(), self.root, self.geometry)

    def matrix(self):
        result = admit_round(self.stdout(), self.root, self.geometry)
        cases = []
        for mode in MODES:
            for latency in LATENCIES:
                for reverse in (0, 1):
                    row = copy.deepcopy(result)
                    row.update(mode=mode, latency=latency, reverse=reverse)
                    for path in row["paths"]:
                        path["cycles"] += latency
                    cases.append(row)
        return cases

    def test_complete_matrix_and_order_invariance(self):
        cases = self.matrix()
        self.assertEqual(admit_matrix(cases)["cases"], 12)
        with self.assertRaises(ValueError):
            admit_matrix(cases[:-1])
        cases[1]["paths"][0]["cycles"] += 1
        with self.assertRaises(ValueError):
            admit_matrix(cases)

    def test_latency_changes_only_timing_not_state_or_traffic(self):
        cases = self.matrix()
        cases[2]["paths"][0]["read_bytes"] += 64
        cases[3]["paths"][0]["read_bytes"] += 64
        with self.assertRaises(ValueError):
            admit_matrix(cases)


if __name__ == "__main__":
    unittest.main()
