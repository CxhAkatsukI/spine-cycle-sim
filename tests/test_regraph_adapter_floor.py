"""Diagnostic floors cannot be presented as full R retention or calibration."""

from copy import deepcopy
import json
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import adapter_floor_analysis as analysis


def observation(cycles=100):
    workers = [dict(worker=i, adapter_done=cycles - i, sink_done=cycles,
                    live_edges=1_450_899 if i == 0 else 1, packets=200_000,
                    read_bytes=640, requests=10, output_stalls=0) for i in range(4)]
    workers[0]["live_edges"] -= 3
    return dict(cycles=cycles, workers=workers, live_edges=1_450_899,
                read_bytes=2560, requests=40, passed=True)


def cases():
    return [dict(latency=latency, reverse=reverse, observations=observation())
            for latency in (64, 128) for reverse in (0, 1)]


def references(a4=1000):
    return [dict(latency=latency, reverse=0, arm=arm,
                 observations=dict(result=dict(cycles=a4 if arm == "a4_io16" else 6000, rounds=46)))
            for latency in (64, 128) for arm in ("a4_io16", "bank_stream")]


class AdapterFloorTests(unittest.TestCase):
    def test_one_complete_conserved_record(self):
        expected = observation()
        self.assertEqual(analysis.parse("ADAPTER_FLOOR " + json.dumps(expected)), expected)

    def test_partial_and_duplicate_records_rejected(self):
        for text in ("", "ADAPTER_FLOOR {}\nADAPTER_FLOOR {}"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                analysis.parse(text)

    def test_invalid_worker_counter_completion_and_traffic_rejected(self):
        for key, value in (("worker", 1), ("sink_done", 101), ("adapter_done", 0),
                           ("output_stalls", 1), ("live_edges", 2_000_000),
                           ("read_bytes", 641), ("requests", -1), ("packets", 0.5)):
            row = observation()
            row["workers"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.parse("ADAPTER_FLOOR " + json.dumps(row))

    def test_complete_registration_invariance_required(self):
        with self.assertRaisesRegex(ValueError, "four-row"):
            analysis.summarize(cases()[:-1], references())
        changed = cases()
        changed[1]["observations"]["cycles"] += 1
        with self.assertRaisesRegex(ValueError, "registration"):
            analysis.summarize(changed, references())

    def test_bound_is_not_new_full_r_result(self):
        result = analysis.summarize(cases(), references())
        self.assertFalse(result["full_r_retention_pass"])
        self.assertFalse(result["hardware_calibrated"])
        self.assertEqual(result["rows"][0]["unchanged_reader_46_scan_floor"], 4600)
        self.assertTrue(result["rows"][0]["downstream_only_cannot_meet_ten_percent"])
        faster = analysis.summarize(cases(), references(a4=5000))
        self.assertFalse(faster["rows"][0]["downstream_only_cannot_meet_ten_percent"])
        self.assertFalse(faster["full_r_retention_pass"])

    def test_same_number_of_convergence_scans_required(self):
        rows = deepcopy(references())
        rows[1]["observations"]["result"]["rounds"] = 45
        with self.assertRaisesRegex(ValueError, "scope"):
            analysis.summarize(cases(), rows)


if __name__ == "__main__":
    unittest.main()
