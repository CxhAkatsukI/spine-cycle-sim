"""Directory buffering must preserve old controls and pay bounded read-ahead."""

from copy import deepcopy
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import directory_overlap as study
from tests.test_regraph_apply_ports import fixture as apply_fixture


def fixture():
    before, reference, _ = apply_fixture()
    indexed = {study.elastic_analysis.identity(row): row for row in before}
    rows = []
    for latency, reverse, arm in study.MATRIX:
        prior_arm = study.ARMS[1] if arm == study.ARMS[2] else arm
        row = deepcopy(indexed[(latency, reverse, prior_arm)])
        row["arm"] = row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]:
            part["arm"] = arm
        rows.append(row)
    return rows, reference, before


class DirectoryOverlapTests(unittest.TestCase):
    def test_paid_prefetch_is_bounded_and_resources_explicit(self):
        rows, reference, before = fixture()
        for row in rows:
            if row["arm"] == study.ARMS[2]: row["observations"]["result"]["read_bytes"] += 64
        result = study.summarize(rows, reference, before=before)
        self.assertEqual(result["added_directory_value_bytes"], 32768)
        self.assertEqual(result["physical_masters"], dict(zip(study.ARMS, (13, 16, 16))))
        self.assertEqual(result["pre_edit_controls_replayed_exactly"], 8)
        self.assertEqual(result["comparisons"][0]["extra_directory_read_bytes"], 64)
        self.assertIs(result["strict_resource_match_admitted"], False)

    def test_bad_traffic_is_rejected(self):
        before = dict(read_bytes=100, write_bytes=64)
        for extra, writes in ((-64, 64), (1, 64), (32768 + 64, 64), (0, 128), (True, 64)):
            with self.subTest(extra=extra, writes=writes), self.assertRaises(ValueError):
                study.check_traffic(dict(read_bytes=100 + extra if type(extra) is int else True,
                                         write_bytes=writes, rounds=1), before)

    def test_incomplete_changed_old_or_order_dependent_results_rejected(self):
        rows, reference, before = fixture()
        for changed, old in ((rows[:-1], before), (rows[::-1], before), (rows, before[:-1])):
            with self.subTest(), self.assertRaises(ValueError):
                study.summarize(changed, reference, before=old)
        for index in (1, 2):
            changed = deepcopy(rows)
            changed[index]["observations"]["result"]["cycles"] += 1
            with self.subTest(index=index), self.assertRaises(ValueError):
                study.summarize(changed, reference, before=before)

    def test_changed_full_state_or_active_trajectory_rejected(self):
        for field in ("state", "active"):
            rows, reference, before = fixture()
            for row in rows:
                if row["arm"] != study.ARMS[2]: continue
                if field == "state":
                    for output in row["outputs"]: output["sha256"] = "changed"
                else: row["observations"]["trajectory"][0]["active"] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                study.summarize(rows, reference, before=before)


if __name__ == "__main__":
    unittest.main()
