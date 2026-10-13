"""Independent chronological multi-shard preparation invariants."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.resident_real.preparation import facts
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.resident_real.analysis import analyze

FOLDER = (Path(__file__).resolve().parents[1] / "docs/experiments/comparisons/"
          "grasu_regraph_stage_validation/evaluation_impact/sharded_batch/metadata_layout")


def analysis_fixture():
    previous = json.loads((FOLDER / "lifecycle/evidence/matrix.json").read_text())
    source = [r for r in previous["rows"] if r["case"] == "staggered"]
    rows, cases = [], {}
    for name in ("case-a", "case-b", "case-c"):
        cases[name] = {"vertices": 161, "total_shards": 3, "batches": [
            {"physical_updates": n, "updated_shards": n // 64,
             "binary_probes": n, "multi_segment_updates": n} for n in (128, 0, 192)]}
        for item in source:
            row = deepcopy(item)
            row["case"] = row["observation"]["case"] = name
            rows.append(row)
    return rows, {"cases": cases, "matrix": [
        {key: r[key] for key in ("case", "latency", "arm")} for r in rows]}


class ResidentChronologicalInputTests(unittest.TestCase):
    def setUp(self):
        self.graph = SliceGraph("base", 70, (SliceRecord(0, 0),))
        self.updates = SliceGraph("updates", 70, tuple(SliceRecord(0, i) for i in range(1, 41)))

    def test_reserves_union_but_counts_contiguous_batches_separately(self):
        value = facts(self.graph, self.updates, partition=32, first=7)
        self.assertEqual((value["vertices"], value["total_shards"], value["live_edges"], value["final_edges"]),
                         (71, 3, 1, 41))
        self.assertEqual(value["reserved_live_segments"], 3)
        self.assertEqual(value["batches"], [
            {"physical_updates": 7, "updated_shards": 1, "shard_updates": [7, 0, 0],
             "binary_probes": 7, "multi_segment_updates": 7},
            {"physical_updates": 0, "updated_shards": 0, "shard_updates": [0, 0, 0],
             "binary_probes": 0, "multi_segment_updates": 0},
            {"physical_updates": 33, "updated_shards": 2, "shard_updates": [24, 9, 0],
             "binary_probes": 24, "multi_segment_updates": 24}])

    def test_invalid_reservation_or_operations_are_rejected(self):
        for records in ((SliceRecord(0, 0), SliceRecord(0, 1)),
                        (SliceRecord(0, 1), SliceRecord(0, 1)),
                        (SliceRecord(0, 1, diff=-1), SliceRecord(0, 2)),
                        (SliceRecord(0, 70), SliceRecord(0, 2)),
                        (SliceRecord(70, 1), SliceRecord(0, 2)),
                        (SliceRecord(0, 1, weight=4096), SliceRecord(0, 2))):
            with self.subTest(records=records), self.assertRaises(ValueError):
                facts(self.graph, SliceGraph("invalid", 70, records), first=1)

    def test_undeclared_geometry_is_rejected(self):
        for options in ({"partition": 0}, {"partition": 2**19 + 1}, {"first": 0}, {"first": 40}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                facts(self.graph, self.updates, **options)
        with self.assertRaises(ValueError):
            facts(self.graph, SliceGraph("invalid", 71, self.updates.records), first=1)


class ResidentChronologicalAnalysisTests(unittest.TestCase):
    def test_complete_matrix_keeps_admission_boundaries(self):
        rows, contract = analysis_fixture()
        result = analyze(rows, contract=contract)
        self.assertEqual(result["prediction_rows"], 18)
        self.assertEqual(result["batch_observations"], 54)
        self.assertEqual(len(result["comparisons"]), 18)
        self.assertEqual(len(result["sequence_comparisons"]), 6)
        self.assertTrue(result["copies_ten_percent_diagnostic_met"])
        for key in ("production_baseline_admitted", "hardware_timing_admitted",
                    "publication_match_admitted", "host_inclusive_timing_admitted", "production_layout_changed"):
            self.assertFalse(result[key])

    def test_missing_duplicate_or_undeclared_rows_are_rejected(self):
        rows, contract = analysis_fixture()
        for bad in (rows[:-1], rows + rows[:1], rows[:-1] + rows[:1]):
            with self.assertRaises(ValueError):
                analyze(bad, contract=contract)

    def test_work_empty_state_and_table_geometry_are_not_optional(self):
        for kind in ("work", "empty", "state", "table", "upload"):
            rows, contract = analysis_fixture()
            row = rows[-1]
            if kind == "work":
                row["observation"]["batches"][0]["binary_probes"] += 1
            elif kind == "empty":
                row["observation"]["batches"][1]["cycles"] = 1
            elif kind == "state":
                row["batch_states"][2]["sha256"] = row["state_sha256"] = "c" * 64
            elif kind == "table":
                contract["cases"][row["case"]]["vertices"] += 1
                for item in rows:
                    if item["case"] == row["case"]:
                        item["observation"]["vertices"] += 1
            else:
                row["observation"]["resources"]["initial_metadata_upload_bytes"] = 0
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                analyze(rows, contract=contract)

    def test_slow_batch_cannot_be_hidden_by_passing_sequence_total(self):
        rows, contract = analysis_fixture()
        target = rows[-1]
        original = next(r for r in rows if r["case"] == target["case"]
                        and r["latency"] == target["latency"] and r["arm"] == "original-prepared-shards")
        first, _, last = original["observation"]["batches"]
        target["observation"]["batches"][0]["cycles"] = int(first["cycles"] * 1.15)
        target["observation"]["batches"][2]["cycles"] = int(last["cycles"] * 0.9)
        result = analyze(rows, contract=contract)
        self.assertTrue(all(0.9 <= r["copies_over_original"] <= 1.1 for r in result["sequence_comparisons"]))
        self.assertFalse(result["copies_ten_percent_diagnostic_met"])
        self.assertEqual(result["prediction_rows"], 18)


if __name__ == "__main__":
    unittest.main()
