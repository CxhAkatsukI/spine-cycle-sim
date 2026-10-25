from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.publication_board_probe.analysis import (
    compare_rates, update_timeline,
)
from spine_cycle_sim.experiments.publication_board_probe.grasu import prepare
from spine_cycle_sim.experiments.publication_board_probe.launch import summarize
from spine_cycle_sim.experiments.publication_board_probe.launch_analysis import package
from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord, write_slice


class PublicationBoardProbeTests(unittest.TestCase):
    def prepare_fixture(self, initial, updates, vertices=100):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        write_slice(root / "g.slice", SliceGraph("initial", vertices, tuple(initial)))
        write_slice(root / "u.slice", SliceGraph("updates", vertices, tuple(updates)))
        report = prepare(root / "g.slice", root / "u.slice", root / "input.graph")
        return report, (root / "input.graph").read_text()

    def test_preserves_external_ids_weights_and_update_numerator(self):
        report, text = self.prepare_fixture([SliceRecord(90, 2, 7)], [SliceRecord(2, 98, 4)])
        self.assertEqual(text, "100 1 1\n90 2 7\n2 98 4 1\n")
        self.assertEqual(report["successful_insertions_expected"], 1)
        self.assertTrue(report["original_ids_preserved"])

    def test_rejects_duplicate_initial_pair_even_with_different_weights(self):
        with self.assertRaises(ValueError):
            self.prepare_fixture([SliceRecord(1, 2, 1), SliceRecord(1, 2, 3)], [SliceRecord(2, 3)])

    def test_rejects_duplicate_or_already_present_insertions(self):
        for updates in ([SliceRecord(1, 2)], [SliceRecord(2, 3), SliceRecord(2, 3)]):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.prepare_fixture([SliceRecord(1, 2)], updates)

    def test_rejects_deletions(self):
        with self.assertRaises(ValueError):
            self.prepare_fixture([SliceRecord(1, 2)], [SliceRecord(2, 3, 1, -1)])

    def timeline(self):
        lines = ["GRASU_SHARDED_UPDATE_EVENTS shard=0 gap_from_previous_ms=0 union_ms=2"]
        lines += [f"GRASU_SHARDED_UPDATE_EVENTS_PHASE shard=0 cu=cu{i} start_offset_ms={i / 10}"
                  for i in range(9)]
        return lines

    def test_timeline_does_not_sum_overlapping_cu_durations(self):
        result = update_timeline(self.timeline(), 2)
        self.assertEqual(result["shard_span_sum_ms"], 2)
        self.assertEqual(result["median_within_shard_cu_start_spread_ms"], 0.8)

    def test_timeline_rejects_missing_or_duplicate_cus_and_nonconservation(self):
        for lines, expected in ((self.timeline()[:-1], 2),
                                (self.timeline() + [self.timeline()[-1]], 2),
                                (self.timeline(), 3)):
            with self.subTest(lines=len(lines), expected=expected), self.assertRaises(ValueError):
                update_timeline(lines, expected)

    def test_an_arithmetic_match_does_not_become_a_publication_match(self):
        result = compare_rates(100, 100)
        self.assertEqual(result["reference_over_measured_rate"], 1)
        self.assertFalse(result["publication_match"])

    def launch_rows(self):
        return [{"mode": mode, "repeat": repeat, "event_span_ms": repeat,
                 "resident_wall_ms": repeat * 2, "first_wave_start_spread_ms": repeat / 10,
                 "gteps": 10 / repeat, "post_enqueue_wait_ms": repeat / 2}
                for mode in ("baseline", "prebound", "author_order") for repeat in (1, 2, 3)]

    def test_launch_summary_reports_median_not_best_and_excludes_cold(self):
        cold = dict(self.launch_rows()[0], repeat=0, event_span_ms=1000)
        summaries = summarize([cold, *self.launch_rows()])
        self.assertEqual(len(summaries), 3)
        self.assertEqual(summaries[0]["event_span_ms"], 2)
        self.assertEqual(summaries[2]["post_enqueue_wait_ms"], 1)

    def test_launch_summary_rejects_missing_or_duplicate_repetitions(self):
        rows = self.launch_rows()
        for selected in (rows[:-1], rows[:-1] + [rows[-2]]):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                summarize(selected)

    def test_launch_packaging_rejects_incomplete_matrix_and_oracle_failure(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "raw.json"
            report = {"status": "HOST_LAUNCH_DIAGNOSTIC_PASS_NOT_PUBLICATION_MATCH",
                      "publication_match": False, "rows": self.launch_rows()}
            path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                package(path, Path(temporary) / "output.json")
            report["rows"] = [dict(row, independent_oracle_pass=False) for row in report["rows"]]
            report["rows"].append(dict(report["rows"][0], repeat=0))
            path.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                package(path, Path(temporary) / "output.json")


if __name__ == "__main__":
    unittest.main()
