"""Reject incomplete or numerically inconsistent FPGA paired evidence."""

import copy
import csv
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.affected_fraction.review import check_point, review


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


class ContinuationReviewTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "data").mkdir()
        self.write_json("delivery.json", dict(status="COMPLETED_WITH_FAILURES", files={}, studies=[
            dict(algorithm="fixture", dataset="AU"), dict(algorithm="fixture", dataset="AU")]))
        for index, names, cases in ((0, ["a", "b"], [dict(name="a", status="FAILED_RETAINED",
                samples=[dict(status="FAILED_RETAINED", error="overflow")])]),
                (1, ["b"], [dict(name="b", status="MEASURED", speedup=2)])):
            self.write_json(f"data/campaign-{index}.json", dict(status="FAILED_RETAINED" if index == 0
                else "COMPLETED", cases=cases))
            self.write_json(f"data/workloads-{index}.json", dict(algorithm="fixture", dataset="AU",
                points=[dict(name=name) for name in names]))
        self.write_csv("points.csv", [dict(campaign=0, name="a", status="FAILED_RETAINED",
                speedup="", measured_pair_count=0), dict(campaign=1, name="b", status="MEASURED",
                speedup=2, measured_pair_count=3)])
        self.write_csv("samples.csv", [dict(campaign=0, name="a", status="FAILED_RETAINED")] +
            [dict(campaign=1, name="b", status="PASS") for _ in range(4)])
        with tarfile.open(self.root / "data/host-logs.tar.gz", "w:gz") as archive:
            content = b"overflow\n"
            item = tarfile.TarInfo("campaign-0/a/sample-0/spine.stderr.txt")
            item.size = len(content)
            archive.addfile(item, io.BytesIO(content))
        self.check = patch("spine_cycle_sim.experiments.evaluation_impact.affected_fraction.review.check_point",
                           return_value=dict(clocks=[(150,)], peak_memory_bytes=20,
                                             minimum_effective_available_bytes=40))
        self.check.start()
        self.addCleanup(self.check.stop)

    def write_json(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def write_csv(self, name, rows):
        with (self.root / "data" / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_failed_point_and_continuation_are_complete_but_not_all_passed(self):
        result = review(self.root)
        self.assertEqual(result["planned_points"], 2)
        self.assertEqual(result["primary_points"], 1)
        self.assertEqual(result["failed_primary_points"], 1)
        self.assertEqual(result["measured_pairs"], 3)

    def test_reject_missing_continuation(self):
        self.write_json("data/campaign-1.json", dict(status="COMPLETED", cases=[]))
        with self.assertRaisesRegex(ValueError, "every planned"):
            review(self.root)

    def test_reject_hidden_failure(self):
        self.write_json("delivery.json", dict(status="COMPLETED", files={}, studies=[
            dict(algorithm="fixture", dataset="AU"), dict(algorithm="fixture", dataset="AU")]))
        with self.assertRaisesRegex(ValueError, "hides"):
            review(self.root)

    def test_reject_failed_point_with_a_speedup(self):
        self.write_csv("points.csv", [dict(campaign=0, name="a", status="FAILED_RETAINED",
                speedup=10, measured_pair_count=0), dict(campaign=1, name="b", status="MEASURED",
                speedup=2, measured_pair_count=3)])
        with self.assertRaisesRegex(ValueError, "speedup"):
            review(self.root)


if __name__ == "__main__":
    unittest.main()
