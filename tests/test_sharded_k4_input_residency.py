"""Residency scope and repetitions cannot be silently widened or dropped."""

import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.input_residency import residency_record, summarize


class InputResidencyTests(unittest.TestCase):
    def test_strict_default_off_and_initial_setup_record(self):
        line = ("SHARDED_INPUT_RESIDENCY policy=premigrate buffers=180 bytes=1024 "
                "wall_ms=1.2 event_ms=1.1 boundary=initial_setup_before_updates")
        self.assertIsNone(residency_record("", enabled=False, partitions=18))
        self.assertEqual(residency_record(line, enabled=True, partitions=18)["buffers"], 180)
        for text, enabled in ((line, False), ("", True), (line + "\n" + line, True),
                              (line.replace("180", "179"), True),
                              (line.replace("1.2", "nan"), True),
                              (line.replace("initial_setup_before_updates", "after_updates"), True)):
            with self.subTest(text=text), self.assertRaises(ValueError):
                residency_record(text, enabled=enabled, partitions=18)

    def test_complete_rotating_matrix_excludes_profile_from_medians(self):
        arms = ("frozen", "off", "on")
        rows = [dict(repeat=r, arm=arms[(r + i) % 3], profiled=False,
                     analysis=dict(compute_span_ms=r + 10), residency=None)
                for r in range(3) for i in range(3)]
        rows.append(dict(repeat=3, arm="on", profiled=True,
                         analysis=dict(compute_span_ms=999), residency=None))
        report = summarize(rows)
        self.assertEqual([m["compute_span_ms"] for m in report["medians"]], [11, 11, 11])
        self.assertFalse(report["hardware_timing_admitted"])
        with self.assertRaises(ValueError):
            summarize(rows[:-1])
        with self.assertRaises(ValueError):
            summarize(rows[::-1])


if __name__ == "__main__":
    unittest.main()
