import gzip
from pathlib import Path
import random
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.publication_admission.analysis import (
    analyze_order, compare_denominator, equal_count_batch, publication_numerator, rounded_interval,
)
from spine_cycle_sim.experiments.publication_admission.temporal import connect, ingest, materialize_order
from spine_cycle_sim.experiments.publication_admission.denominators import residual_event_hypothesis


class TemporalAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source.gz"
        self.database = self.root / "events.sqlite3"

    def load(self, text, limit=100):
        with gzip.open(self.source, "wb") as stream:
            stream.write(text.encode("ascii"))
        return ingest(self.source, sha256_file(self.source), self.database, limit)

    def test_bad_field_count_rejected(self):
        with self.assertRaisesRegex(ValueError, "expected src"):
            self.load("1 2\n")

    def test_out_of_range_and_negative_values_rejected(self):
        for text in ("-1 2 3\n", "1 2147483648 3\n", "1 2 -1\n", "2147483648 2 3\n"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "signed-ABI"):
                self.load(text)
            self.database.unlink()

    def test_source_hash_and_database_reuse_rejected(self):
        self.load("1 2 3\n")
        with self.assertRaisesRegex(ValueError, "identity"):
            ingest(self.source, "0" * 64, self.database, 100)
        with self.assertRaises(FileExistsError):
            ingest(self.source, sha256_file(self.source), self.database, 100)

    def test_empty_input_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            self.load("# comment\n\n")

    def test_event_limit_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "event limit"):
            self.load("1 2 3\n2 3 4\n", limit=1)

    def test_timestamp_inversions_and_loop_events_counted(self):
        stats = self.load("# header\n1 1 30\n1 1 20\n1 2 20\n2 3 40\n")
        self.assertEqual(stats["events"], 4)
        self.assertEqual(stats["self_loop_events"], 2)
        self.assertEqual(stats["timestamp_inversions"], 1)
        self.assertEqual((stats["first_timestamp"], stats["min_timestamp"], stats["max_timestamp"]), (30, 20, 40))

    def oracle(self, events, ordering, base, batches):
        order = list(range(len(events)))
        if ordering == "timestamp_then_file_order":
            order.sort(key=lambda i: (events[i][2], i))
        seen = set()
        counts = [dict(id=i, raw_events=0, new_edges=0, new_nonself_edges=0) for i in range(batches)]
        time_counts = [dict(row) for row in counts]
        minimum = min(events[index][2] for index in order[base:])
        span = max(events[index][2] for index in order[base:]) - minimum + 1
        for position, index in enumerate(order):
            src, dst, timestamp = events[index]
            fresh = (src, dst) not in seen
            seen.add((src, dst))
            if position >= base:
                count = (position - base) * batches // (len(order) - base)
                time = (timestamp - minimum) * batches // span
                for row in (counts[count], time_counts[time]):
                    row["raw_events"] += 1
                    row["new_edges"] += fresh
                    row["new_nonself_edges"] += fresh and src != dst
        return counts, time_counts, len(seen)

    def test_sql_counts_match_independent_sequential_set_oracle(self):
        generator = random.Random(42)
        events = [(generator.randrange(10), generator.randrange(10), generator.randrange(7)) for _ in range(100)]
        self.load("".join(f"{src} {dst} {timestamp}\n" for src, dst, timestamp in events))
        with connect(self.database) as connection:
            for ordering in ("file_order", "timestamp_then_file_order"):
                actual = analyze_order(connection, ordering, 100, 41, 10, 3)
                counts, time_counts, unique = self.oracle(events, ordering, 41, 10)
                self.assertEqual(actual["equal_event_count"], counts)
                self.assertEqual(actual["final_unique_edges"], unique)
                if ordering != "file_order":
                    self.assertEqual(actual["equal_timestamp_span"], time_counts)
                for cut, field in ((38, "successful_new_edges_max"), (43, "successful_new_edges_min")):
                    expected, _, _ = self.oracle(events, ordering, cut, 10)
                    self.assertEqual(actual["base_rounding_sensitivity"][field], sum(row["new_edges"] for row in expected))

    def test_timestamp_ties_use_file_order_not_edge_sort(self):
        self.load("9 8 0\n1 2 0\n3 4 0\n1 2 1\n3 4 2\n")
        with connect(self.database) as connection:
            actual = analyze_order(connection, "timestamp_then_file_order", 5, 2, 10, 0)
        self.assertEqual(actual["base_unique_edges"], 2)
        self.assertEqual(actual["successful_new_edges"], 1)
        self.assertEqual(actual["base_rounding_sensitivity"]["successful_new_edges_min"], 1)

    def test_invalid_order_and_base_rejected(self):
        self.load("1 2 3\n2 3 4\n")
        with connect(self.database) as connection:
            with self.assertRaisesRegex(ValueError, "ordering"):
                materialize_order(connection, "invented")
            for base, half in ((0, 0), (2, 0), (1, 2), (1, -1)):
                with self.subTest(base=base, half=half), self.assertRaises(ValueError):
                    analyze_order(connection, "file_order", 2, base, 10, half)

    def test_loops_consume_raw_base_positions_even_when_not_successes(self):
        self.load("1 1 0\n1 2 1\n2 2 2\n2 3 3\n")
        with connect(self.database) as connection:
            actual = analyze_order(connection, "file_order", 4, 2, 10, 0)
        self.assertEqual((actual["update_raw_events"], actual["successful_new_edges"], actual["successful_new_nonself_edges"]), (2, 2, 1))


class PublicationDenominatorTests(unittest.TestCase):
    def test_posthoc_residual_clue_does_not_claim_successful_updates(self):
        result = residual_event_hypothesis({"events": 964437, "self_loop_events": 237776},
            [{"final_unique_edges": 596933}, {"final_unique_edges": 596933}],
            {"paper_seconds": "0.00068", "paper_rate_million": "190.77"})
        self.assertEqual(result["candidate_count"], 129728)
        self.assertTrue(result["within_printed_rounding_interval"])
        self.assertFalse(result["candidate_is_proven_successful_update_count"])
        self.assertFalse(result["actual_original_update_sequence_recovered"])
        self.assertIsNone(result["publication_timing_match"])

    def test_complete_set_disagreement_rejected_by_exploratory_analysis(self):
        with self.assertRaisesRegex(ValueError, "complete edge set"):
            residual_event_hypothesis({"events": 4, "self_loop_events": 0},
                [{"final_unique_edges": 2}, {"final_unique_edges": 3}], {})

    def test_printed_precision_changes_interval(self):
        self.assertNotEqual(rounded_interval("1.0"), rounded_interval("1.00"))
        with self.assertRaises(ValueError):
            rounded_interval("0")

    def test_rounded_numerator_uses_rate_million_and_seconds(self):
        result = publication_numerator("0.00068", "190.77")
        self.assertEqual(result["central"], "129723.6000000")
        self.assertLess(result["integer_min"], 129724)
        self.assertGreater(result["integer_max"], 129724)

    def test_agreeing_denominator_cannot_become_timing_pass(self):
        actual = compare_denominator({"update_raw_events": 374000, "successful_new_edges": 129724,
            "successful_new_nonself_edges": 129700,
            "base_rounding_sensitivity": {"successful_new_edges_min": 129000, "successful_new_edges_max": 130000}},
            "0.00068", "190.77")
        self.assertFalse(actual["raw_update_count_consistent"])
        self.assertTrue(actual["new_edge_count_consistent"])
        self.assertIsNone(actual["publication_timing_match"])
        self.assertEqual(actual["status"], "DENOMINATOR_CONTROL_ONLY_NOT_TIMING_ADMISSION")

    def test_equal_count_boundaries_and_invalid_positions(self):
        self.assertEqual([equal_count_batch(i, 2, 8, 3) for i in range(2, 8)], [0, 0, 1, 1, 2, 2])
        for args in ((1, 2, 8, 3), (8, 2, 8, 3), (1, 1, 1, 3), (2, 2, 8, 0)):
            with self.assertRaises(ValueError):
                equal_count_batch(*args)


if __name__ == "__main__":
    unittest.main()
