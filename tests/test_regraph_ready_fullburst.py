"""A refill experiment must retain complete old controls and physical work."""

from copy import deepcopy
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import ready_fullburst as study
from tests.test_regraph_ready_bursts import fixture as ready_fixture


def fixture():
    before, reference, _ = ready_fixture()
    indexed = {study.elastic_analysis.identity(row): row for row in before}
    rows = []
    for latency, reverse, arm in study.MATRIX:
        row = deepcopy(indexed[(latency, reverse, study.ARMS[1] if arm == study.ARMS[2] else arm)])
        row["arm"] = row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]: part["arm"] = arm
        rows.append(row)
    return rows, reference, before


class ReadyFullBurstTests(unittest.TestCase):
    def test_complete_matrix_and_resources(self):
        rows, reference, before = fixture()
        result = study.summarize(rows, reference, before=before)
        self.assertEqual(result["pre_edit_controls_replayed_exactly"], 8)
        self.assertEqual(result["physical_masters"], study.MASTERS)
        self.assertFalse(result["production_baseline_admitted"])
        self.assertFalse(result["publication_match_admitted"])

    def test_missing_changed_old_or_order_dependent_rejected(self):
        for mode in ("missing", "old", "order"):
            rows, reference, before = fixture()
            if mode == "missing": rows.pop()
            else: rows[0 if mode == "old" else 2]["observations"]["result"]["cycles"] += 1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                study.summarize(rows, reference, before=before)

    def test_work_cannot_be_removed_to_pass(self):
        for field in ("read_bytes", "write_bytes", "state", "active"):
            rows, reference, before = fixture()
            for row in rows:
                if row["arm"] != study.ARMS[2]: continue
                if field == "state":
                    for output in row["outputs"]: output["sha256"] = "changed"
                elif field == "active": row["observations"]["trajectory"][0]["active"] += 1
                else: row["observations"]["result"][field] -= 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                study.summarize(rows, reference, before=before)


if __name__ == "__main__": unittest.main()
