"""Output reordering cannot buy performance by dropping physical work or state."""

from copy import deepcopy
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import ready_bursts as study
from tests.test_regraph_directory_overlap import fixture as directory_fixture


def fixture():
    before, reference, _ = directory_fixture()
    indexed = {study.elastic_analysis.identity(row): row for row in before}
    rows = []
    for latency, reverse, arm in study.MATRIX:
        row = deepcopy(indexed[(latency, reverse, study.ARMS[1] if arm == study.ARMS[2] else arm)])
        row["arm"] = row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]: part["arm"] = arm
        rows.append(row)
    return rows, reference, before


class ReadyBurstTests(unittest.TestCase):
    def test_resources_and_old_controls_explicit(self):
        rows, reference, before = fixture()
        result = study.summarize(rows, reference, before=before)
        self.assertEqual(result["pre_edit_controls_replayed_exactly"], 8)
        self.assertEqual(result["physical_masters"], dict(zip(study.ARMS, (13, 16, 16))))
        self.assertFalse(result["strict_resource_match_admitted"])
        self.assertFalse(result["hardware_timing_admitted"])

    def test_missing_or_order_dependent_matrix_rejected(self):
        rows, reference, before = fixture()
        for changed in (rows[:-1], rows[::-1]):
            with self.subTest(), self.assertRaises(ValueError):
                study.summarize(changed, reference, before=before)
        rows[2]["observations"]["result"]["cycles"] += 1
        with self.assertRaises(ValueError): study.summarize(rows, reference, before=before)

    def test_physical_traffic_and_state_conserved(self):
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
