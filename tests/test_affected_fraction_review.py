"""Reject incomplete or numerically inconsistent FPGA paired evidence."""

import copy
import unittest

from spine_cycle_sim.experiments.evaluation_impact.affected_fraction.review import check_point


class PointReviewTest(unittest.TestCase):
    def setUp(self):
        self.hashes = {}
        self.point = dict(name="fixture", status="MEASURED", speedup=2,
                          medians_ms=dict(spine=3, gr=6), samples=[])
        for index in range(4):
            arms = {}
            for arm in ("spine", "gr"):
                arms[arm] = dict(clock=dict(driver_reported_mhz=[150, 500]),
                                 memory_guard=dict(status="COMPLETED", minimum_effective_available_bytes=40),
                                 cgroup_before={"memory.events": "oom 0\noom_kill 0\noom_group_kill 0\n"},
                                 cgroup_after={"memory.events": "oom 0\noom_kill 0\noom_group_kill 0\n",
                                               "memory.peak": "16"})
                for stream in ("stdout", "stderr"):
                    arms[arm][stream] = dict(sha256="fixture-digest")
                    self.hashes[f"campaign-0/fixture/sample-{index}/{arm}.{stream}.txt"] = "fixture-digest"
            self.point["samples"].append(dict(
                sample_index=index, status="PASS", warmup=index == 0, arms=arms,
                order=["spine", "gr"] if index % 2 == 0 else ["gr", "spine"],
                pair=dict(spine_wall_ms=3, gr_wall_ms=6)))

    def test_complete_point(self):
        self.assertEqual(check_point(self.point, self.hashes, 0)["clocks"], [(150, 500)])

    def test_reject_bad_speedup(self):
        self.point["speedup"] = 9
        with self.assertRaisesRegex(ValueError, "speedup"):
            check_point(self.point, self.hashes, 0)

    def test_reject_missing_sample(self):
        self.point["samples"].pop()
        with self.assertRaisesRegex(ValueError, "three measured"):
            check_point(self.point, self.hashes, 0)

    def test_reject_clock_mismatch_and_oom(self):
        for field in ("clock", "oom"):
            point = copy.deepcopy(self.point)
            result = point["samples"][1]["arms"]["gr"]
            if field == "clock":
                result["clock"]["driver_reported_mhz"][0] = 140
            else:
                result["cgroup_after"]["memory.events"] = "oom 1\noom_kill 1\noom_group_kill 0\n"
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_point(point, self.hashes, 0)

    def test_reject_lost_raw_log(self):
        self.hashes.clear()
        with self.assertRaisesRegex(ValueError, "raw log"):
            check_point(self.point, self.hashes, 0)


if __name__ == "__main__":
    unittest.main()
