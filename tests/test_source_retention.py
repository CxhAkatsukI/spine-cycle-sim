"""Fail closed on altered logs, incomplete repetitions and changed CSR graphs."""

from array import array
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.analysis import (
    envelope, profiled_runs, summarize,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.preflight import duplicate_edges
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity


class SourceRetentionTest(unittest.TestCase):
    def test_envelope_keeps_gap_and_does_not_sum_overlaps(self):
        self.assertEqual(envelope([{"start_ns": 10, "end_ns": 20}, {"start_ns": 15, "end_ns": 25},
                                   {"start_ns": 40, "end_ns": 45}]), 35)
        with self.assertRaises(ValueError):
            envelope([{"start_ns": 10, "end_ns": 9}])

    def test_ratio_of_medians_ignores_cold_but_keeps_all_warm(self):
        a = [{"repeat": i, "event_span_ns": n * 1_000_000} for i, n in enumerate((1000, 1, 2, 100))]
        b = [{"repeat": i, "event_span_ns": n * 1_000_000} for i, n in enumerate((1, 2, 3, 4))]
        result = summarize(a, b)
        self.assertEqual(result["current_over_reference"], 1.5)
        self.assertFalse(result["at_most_15_percent_slower"])
        with self.assertRaises(ValueError):
            summarize(a[:3], b)

    def test_single_run_gate_does_not_select_or_average(self):
        a = [{"repeat": 0, "event_span_ns": 100}]
        self.assertTrue(summarize(a, [{"repeat": 0, "event_span_ns": 115}], repetitions=1)[
            "at_most_15_percent_slower"])
        self.assertFalse(summarize(a, [{"repeat": 0, "event_span_ns": 116}], repetitions=1)[
            "at_most_15_percent_slower"])
        with self.assertRaises(ValueError):
            summarize(a * 2, a, repetitions=1)
        with self.assertRaises(ValueError):
            summarize(a, a, repetitions=2)

    def test_single_reference_requires_pinned_successful_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout, stderr, result = root / "out", root / "err", root / "result.json"
            stdout.write_text("ORIGINAL_R_GUARDED_BOARD_CONTROL_PASS\n")
            stderr.write_text("")
            result.write_text(json.dumps({"status": "ORIGINAL_R_GUARDED_BOARD_CONTROL_PASS",
                "iterations": 1, "topology": "a4", "binding": "csr_degree",
                "hardware_timing_measured": True, "event_span_ns": 10,
                "little": 4, "big": 0, "tasks": 1,
                "enqueue_to_completion_ms": 0.5, "events": [
                    {"role": role, "ordinal": 0, "lane": 0, "start_ns": 1, "end_ns": 11}
                    for role in ("little", "apply", "hbm_wrapper")]}))
            row = {"stage": "R", "arm": "reference", "repetitions": 1,
                   "stdout": identity(stdout), "stderr": identity(stderr),
                   "result_directory": str(root), "result_json": identity(result)}
            self.assertEqual(profiled_runs(row)[0]["event_span_ns"], 10)
            result.write_text(result.read_text() + "\n")
            with self.assertRaises(ValueError):
                profiled_runs(row)
            incomplete = json.loads(result.read_text())
            incomplete["events"].pop()
            result.write_text(json.dumps(incomplete))
            row["result_json"] = identity(result)
            with self.assertRaises(ValueError):
                profiled_runs(row)

    def test_duplicate_preflight_does_not_modify_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            offsets, edges = root / "csr_offsets.u32le", root / "csr_destinations.u32le"
            offsets.write_bytes(array("I", [0, 3, 4]).tobytes())
            edges.write_bytes(array("I", [1, 1, 0, 0]).tobytes())
            before = (offsets.read_bytes(), edges.read_bytes())
            self.assertEqual(duplicate_edges(root), 1)
            self.assertEqual(before, (offsets.read_bytes(), edges.read_bytes()))
            offsets.write_bytes(array("I", [0, 5, 4]).tobytes())
            with self.assertRaises(ValueError):
                duplicate_edges(root)

    def test_raw_replay_requires_all_events_and_unchanged_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stdout, stderr = root / "out", root / "err"
            stderr.write_text("")
            lines = ['G_CONTROL_CONFIG {"shards":1}']
            for repeat in range(4):
                for cu in range(9):
                    lines.append("G_CONTROL_EVENT " + json.dumps({"repeat": repeat, "shard": 0, "cu": cu,
                                                                  "start_ns": cu, "end_ns": 10 + cu}))
                lines.append("G_CONTROL_RESULT " + json.dumps({"repeat": repeat, "full_pma_pass": True,
                                                               "event_span_ns": 18}))
            stdout.write_text("\n".join(lines))
            row = {"stage": "G", "arm": "current", "stdout": identity(stdout), "stderr": identity(stderr)}
            self.assertEqual(len(profiled_runs(row)), 4)
            stdout.write_text(stdout.read_text() + "\n")
            with self.assertRaises(ValueError):
                profiled_runs(row)
            stdout.write_text("\n".join(line for line in lines if '"cu": 8' not in line))
            row["stdout"] = identity(stdout)
            with self.assertRaises(ValueError):
                profiled_runs(row)

    def test_candidate_matches_production_packet_width(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "cpp/tests/publication_sources/source_retention/device.hpp").read_text()
        self.assertIn("#else\n            const unsigned packets = 65536u / 2;", source)
        self.assertIn("const unsigned packets = ((dst_vertices + 15u) / 16u) * 8u;", source)
        self.assertIn('g.setArg(5, packets), "bind gather publication rows"', source)
        self.assertIn('m.setArg(5, packets), "bind mux packets"', source)
        self.assertIn("const unsigned bursts = (vertices + 15u) / 16u;", source)


if __name__ == "__main__":
    unittest.main()
