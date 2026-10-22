"""Reader-only speed cannot be promoted to integrated-R or hardware admission."""

from copy import deepcopy
import json
import unittest
from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import prefetch_analysis as analysis


def observation():
    counts = (848130, 370883, 170898, 60988)
    workers = [dict(worker=i, sink_done=100, read_bytes=640, requests=10,
        live_edges=count, packets=(count + 7) // 8, physical_slots=(count + 15) // 16 * 16,
        input_dummy=(-count) % 16, output_dummy=(-count) % 8,
        max_parents=16, max_bank_lines=256, max_lanes=24,
        reader_output_stalls=0, publisher_output_stalls=0) for i, count in enumerate(counts)]
    return dict(cycles=100, read_bytes=2560, requests=40, live_edges=1450899,
                packets=sum(w["packets"] for w in workers), workers=workers, passed=True)


def cases():
    return [dict(latency=latency, reverse=reverse, observations=observation())
            for latency in (64, 128) for reverse in (0, 1)]


def with_transport():
    row = observation()
    row["schema_version"] = 2
    for worker in row["workers"]:
        worker.update(read_beats=10, backend_submit_stalls=12, selector_wait=5,
                      reader_pipeline_peak=2, publisher_pipeline_peak=2)
    row["transport"] = dict(accepted_beats=40, intents=40, grants=40, consumed_grants=40,
                            request_waits=48, contended_cycles=0, capacity_blocked_cycles=0, max_contenders=1)
    return row


def probes():
    return [dict(registered=registered, beats=512, cycles=2000, first_issue=5,
        last_issue=5 + 511 * (2 if registered else 1), one_cycle_gaps=0 if registered else 511,
        two_cycle_gaps=511 if registered else 0, backend_submit_stalls=512 if registered else 0)
        for registered in (False, True)]


def reference():
    return [dict(latency=latency, reverse=reverse, arm="a4_io16",
        observations=dict(result=dict(cycles=10000, rounds=46)))
        for latency in (64, 128) for reverse in (0, 1)]


class PrefetchCompactTests(unittest.TestCase):
    def test_complete_conserved_finite_record(self):
        for row in (observation(), with_transport()):
            self.assertEqual(analysis.parse("PREFETCH_COMPACT " + json.dumps(row)), row)

    def test_transport_and_pipeline_ledgers_cannot_be_invented(self):
        for target, key, value in (("worker", "read_beats", 9), ("worker", "reader_pipeline_peak", 3),
                ("worker", "publisher_pipeline_peak", 3), ("worker", "backend_submit_stalls", 0.5),
                ("transport", "grants", 41), ("transport", "request_waits", 47),
                ("transport", "accepted_beats", 39)):
            row = with_transport()
            (row["workers"][0] if target == "worker" else row["transport"])[key] = value
            with self.subTest(target=target, key=key), self.assertRaises(ValueError):
                analysis.parse("PREFETCH_COMPACT " + json.dumps(row))
        for version in (True, 0, 3):
            row = with_transport()
            row["schema_version"] = version
            with self.assertRaises(ValueError):
                analysis.parse("PREFETCH_COMPACT " + json.dumps(row))

    def test_transport_probe_controls_and_issue_intervals(self):
        def stdout(rows):
            return "\n".join("TRANSPORT_PROBE " + json.dumps(r) for r in rows)
        self.assertEqual(analysis.transport_probes(stdout(probes())), probes())
        for rows in ([], probes()[:1], [probes()[0]] * 2):
            with self.assertRaises(ValueError):
                analysis.transport_probes(stdout(rows))
        for key, value in (("one_cycle_gaps", 1), ("last_issue", 100), ("backend_submit_stalls", 0),
                           ("beats", 511), ("cycles", 1), ("registered", 1)):
            rows = probes()
            rows[1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.transport_probes(stdout(rows))

    def test_missing_or_multiple_observation_rejected(self):
        for value in ("", "PREFETCH_COMPACT {}\nPREFETCH_COMPACT {}"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                analysis.parse(value)

    def test_bad_counter_storage_window_or_ledger_rejected(self):
        for key, value in (("max_parents", 17), ("max_bank_lines", 257), ("max_lanes", 33),
                           ("physical_slots", 0), ("output_dummy", 10), ("packets", 0),
                           ("requests", 1), ("sink_done", 101), ("read_bytes", -1),
                           ("publisher_output_stalls", 0.5)):
            row = observation()
            row["workers"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.parse("PREFETCH_COMPACT " + json.dumps(row))

    def test_registration_and_matrix_required(self):
        with self.assertRaisesRegex(ValueError, "matrix"):
            analysis.summarize(cases()[:-1], reference())
        changed = cases()
        changed[1]["observations"]["cycles"] += 1
        with self.assertRaisesRegex(ValueError, "registration"):
            analysis.summarize(changed, reference())

    def test_fast_floor_is_not_full_r_retention(self):
        result = analysis.summarize(cases(), reference())
        for row in result["rows"]:
            self.assertEqual(row["reader_floor_over_a4"], 0.46)
            self.assertFalse(row["integrated_r_retention_passed"])
            self.assertFalse(row["hardware_calibrated"])

    def test_strong_a4_and_same_round_count_required(self):
        with self.assertRaisesRegex(ValueError, "strong"):
            analysis.summarize(cases(), reference()[:-1])
        changed = deepcopy(reference())
        for row in changed:
            row["observations"]["result"]["rounds"] = 45
        with self.assertRaisesRegex(ValueError, "scope"):
            analysis.summarize(cases(), changed)


if __name__ == "__main__":
    unittest.main()
