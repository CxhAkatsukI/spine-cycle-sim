"""Splitting Apply masters must preserve traffic, state and old controls."""

from copy import deepcopy
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import apply_ports as study
from tests.test_regraph_metadata_ports import fixture as metadata_fixture


def fixture():
    before, reference, _ = metadata_fixture()
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


class ApplyPortsTests(unittest.TestCase):
    def test_added_physical_master_is_not_a_resource_match(self):
        rows, reference, before = fixture()
        result = study.summarize(rows, reference, before=before)
        self.assertEqual(result["physical_masters"], dict(zip(study.ARMS, (13, 15, 16))))
        self.assertEqual(result["pre_edit_controls_replayed_exactly"], 8)
        self.assertIn("cycle_reduction_from_shared_apply", result["comparisons"][0])
        for key in ("strict_resource_match_admitted", "hardware_timing_admitted",
                    "publication_match_admitted", "production_baseline_admitted",
                    "new_spine_comparison_executed"):
            self.assertIs(result[key], False)

    def test_incomplete_matrix_and_changed_old_cycles_rejected(self):
        rows, reference, before = fixture()
        for changed, old in ((rows[:-1], before), (rows[::-1], before), (rows, before[:-1])):
            with self.subTest(), self.assertRaises(ValueError):
                study.summarize(changed, reference, before=old)
        rows[1]["observations"]["result"]["cycles"] += 1
        with self.assertRaises(ValueError): study.summarize(rows, reference, before=before)

    def test_candidate_cannot_drop_work_or_depend_on_order(self):
        for kind in ("state", "active", "read_bytes", "write_bytes", "order", "arm"):
            rows, reference, before = fixture()
            for row in rows:
                if row["arm"] != study.ARMS[2] or (kind == "order" and row["reverse"]):
                    continue
                if kind == "state":
                    for output in row["outputs"]: output["sha256"] = "changed"
                elif kind == "active": row["observations"]["trajectory"][0]["active"] += 1
                elif kind in ("read_bytes", "write_bytes"): row["observations"]["result"][kind] += 64
                elif kind == "order": row["observations"]["result"]["cycles"] += 1
                elif kind == "arm": row["observations"]["result"]["arm"] = study.ARMS[1]
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                study.summarize(rows, reference, before=before)


if __name__ == "__main__":
    unittest.main()
