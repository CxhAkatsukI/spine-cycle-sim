import csv
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.wait_overlap_analysis import NAMES, summarize


class WaitOverlapTests(unittest.TestCase):
    def fixture(self, directory, rows=None, drift=0):
        rows = rows if rows is not None else [(0, 2), (1, 3), (49, 5)]
        with (directory / "wait_overlap.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("mask", "cycles"))
            writer.writerows(rows)
        with (directory / "backend_waits.csv").open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(NAMES[:6])
            values = [sum(count for mask, count in rows if mask & (1 << bit)) for bit in range(6)]
            values[0] += drift
            writer.writerow(values)

    def test_overlap_not_added_as_time(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            self.fixture(directory)
            result = summarize(directory, 10)
            self.assertEqual(result["marginal_cycles"]["apply_output_stalls"], 8)
            self.assertEqual(result["joint_cycles"]["apply_output_stalls & writeback_write_stalls"], 5)
            self.assertGreater(sum(result["marginal_cycles"].values()), 10)

    def test_missing_duplicate_invalid_mask_or_counter_drift_rejected(self):
        for rows, cycles, drift in (([(0, 2)], 3, 0), ([(0, 2), (0, 2)], 4, 0),
                                   ([(256, 2)], 2, 0), ([(0, 0)], 1, 0),
                                   (None, 10, 1)):
            with self.subTest(rows=rows, drift=drift), tempfile.TemporaryDirectory() as name:
                directory = Path(name)
                self.fixture(directory, rows, drift)
                with self.assertRaises(ValueError): summarize(directory, cycles)


if __name__ == "__main__": unittest.main()
