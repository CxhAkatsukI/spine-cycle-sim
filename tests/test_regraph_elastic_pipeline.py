"""Extra finite storage never relaxes old controls or full-state gates."""

from copy import deepcopy
import json
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import elastic_analysis as analysis
from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import prefetch_analysis
from tests.test_regraph_source_overlap import fixture as source_fixture
from tests.test_regraph_reader_ports import cases as reader_cases


def fixture():
    before, reference, _ = source_fixture()
    indexed = {analysis.identity(row): row for row in before}
    rows = []
    for latency, reverse, arm in analysis.MATRIX:
        row = deepcopy(indexed[(latency, reverse, "prefetch_source" if arm == analysis.ARMS[2] else arm)])
        row["arm"] = row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]:
            part["arm"] = arm
        rows.append(row)
    return rows, reference, before


class ElasticPipelineTests(unittest.TestCase):
    def test_complete_matrix_preserves_separate_admission_flags(self):
        rows, reference, before = fixture()
        result = analysis.summarize(rows, reference, before=before)
        self.assertEqual(result["pre_edit_controls_replayed_exactly"], 8)
        self.assertEqual(result["physical_masters"]["prefetch_dual_elastic"], 11)
        for name in ("hardware_timing_admitted", "publication_match_admitted",
                     "strict_resource_match_admitted", "production_baseline_admitted",
                     "new_spine_comparison_executed"):
            self.assertIs(result[name], False)

    def test_missing_or_reordered_matrices_rejected(self):
        rows, reference, before = fixture()
        for changed, old in ((rows[:-1], before), (rows[::-1], before), (rows, before[:-1])):
            with self.subTest(), self.assertRaises(ValueError):
                analysis.summarize(changed, reference, before=old)

    def test_changed_controls_state_active_traffic_or_order_rejected(self):
        for kind in ("control", "state", "active", "read_bytes", "write_bytes", "order", "arm"):
            rows, reference, before = fixture()
            for row in rows:
                if kind == "control" and row["arm"] == "prefetch_source":
                    row["observations"]["result"]["cycles"] += 1
                if row["arm"] != "prefetch_dual_elastic" or (kind == "order" and row["reverse"]):
                    continue
                if kind == "state":
                    for output in row["outputs"]: output["sha256"] = "changed"
                elif kind == "active": row["observations"]["trajectory"][0]["active"] += 1
                elif kind in ("read_bytes", "write_bytes"): row["observations"]["result"][kind] += 64
                elif kind == "order": row["observations"]["result"]["cycles"] += 1
                elif kind == "arm": row["observations"]["result"]["arm"] = "prefetch_source"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                analysis.summarize(rows, reference, before=before)

    def test_extra_slot_requires_named_schema_and_unchanged_latency(self):
        obs = deepcopy(reader_cases()[0]["observations"])
        obs.update(schema_version=5, pipeline_capacity=3, pipeline_latency=2,
                   refill_policy="available-space", physical_masters=4, masters_per_frontend=1)
        obs["workers"][0]["reader_pipeline_peak"] = 3
        parse = lambda row: prefetch_analysis.parse("PREFETCH_COMPACT " + json.dumps(row))
        self.assertEqual(parse(obs), obs)
        for key, value in (("schema_version", 2), ("pipeline_capacity", 4), ("pipeline_capacity", True),
                           ("pipeline_latency", 1), ("refill_policy", "full-burst"),
                           ("physical_masters", 8), ("masters_per_frontend", True)):
            changed = deepcopy(obs); changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): parse(changed)


if __name__ == "__main__":
    unittest.main()
