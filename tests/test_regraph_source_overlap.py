"""Independent cache loading must not weaken legacy or convergence checks."""

import copy
import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.evaluation_impact.analysis import parse_demo
from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import source_overlap_analysis as analysis
from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.compact_analysis import state_identity
from tests.test_regraph_compact_convergence import fixture as compact_fixture


def fixture():
    before, reference = compact_fixture()
    indexed = {(row["latency"], row["reverse"], row["arm"]): row for row in before}
    rows = []
    for latency, reverse, arm in analysis.MATRIX:
        row = copy.deepcopy(indexed[(latency, reverse, "prefetch_compact" if arm == "prefetch_source" else arm)])
        row["arm"] = row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]:
            part["arm"] = arm
        rows.append(row)
    return rows, reference, before


class SourceOverlapTests(unittest.TestCase):
    def test_portable_result_retains_complete_matrix_and_failed_performance_gate(self):
        capsule = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/"
            "r_bank_stream/prefetch_compact/source_loading.json")
        report = json.loads(capsule.read_text())
        rows = report["rows"]
        self.assertEqual([analysis.identity(row) for row in rows], analysis.MATRIX)
        self.assertEqual(report["gates"]["pre_edit_controls_replayed_exactly"], 12)
        self.assertIs(report["gates"]["retention_pass"], False)
        expected = {64: (10904254, 27465634), 128: (15840606, 34058814)}
        indexed = {analysis.identity(row): row for row in rows}
        for row in rows:
            observation = row["observations"]
            records = ["DEMO_ROUND " + json.dumps(part) for part in observation["trajectory"]]
            parse_demo("\n".join(records + ["DEMO_RESULT " + json.dumps(observation["result"])]))
            self.assertEqual(observation["result"]["rounds"], 46)
            self.assertEqual(state_identity(row), state_identity(rows[0]))
            reverse = indexed[(row["latency"], 1 - row["reverse"], row["arm"])]
            for field in ("observations", "outputs"):
                self.assertEqual(row[field], reverse[field])
        for latency, (a4, candidate) in expected.items():
            self.assertEqual(indexed[(latency, 0, "a4_io16")]["observations"]["result"]["cycles"], a4)
            self.assertEqual(indexed[(latency, 0, "prefetch_source")]["observations"]["result"]["cycles"], candidate)
        for field in ("hardware_timing_admitted", "publication_match_admitted",
                      "strict_resource_match_admitted", "production_baseline_admitted",
                      "new_spine_comparison_executed"):
            self.assertIs(report["gates"][field], False)
        self.assertEqual(report["safety"]["live_final"]["swap_bytes"], 0)

    def test_complete_controls_and_non_admission_flags(self):
        rows, reference, before = fixture()
        result = analysis.summarize(rows, reference, before=before)
        self.assertEqual(result["pre_edit_controls_replayed_exactly"], 12)
        for field in ("hardware_timing_admitted", "publication_match_admitted",
                      "strict_resource_match_admitted", "production_baseline_admitted",
                      "new_spine_comparison_executed"):
            self.assertIs(result[field], False)

    def test_missing_duplicate_or_reordered_rows_rejected(self):
        rows, reference, before = fixture()
        for changed in (rows[:-1], rows[::-1], rows[:-1] + rows[:1]):
            with self.subTest(), self.assertRaisesRegex(ValueError, "sixteen-row"):
                analysis.summarize(changed, reference, before=before)
        with self.assertRaisesRegex(ValueError, "twelve-row"):
            analysis.summarize(rows, reference, before=before[:-1])

    def test_compact_legacy_changes_rejected(self):
        rows, reference, before = fixture()
        for row in rows:
            if row["arm"] == "prefetch_compact":
                row["observations"]["result"]["read_bytes"] += 64
        with self.assertRaisesRegex(ValueError, "pre-edit"):
            analysis.summarize(rows, reference, before=before)

    def test_candidate_drift_and_semantics_rejected(self):
        for kind in ("registration", "state", "active", "read_bytes", "write_bytes", "cycles", "arm"):
            rows, reference, before = fixture()
            for row in rows:
                if row["arm"] != "prefetch_source" or (kind == "registration" and row["reverse"]):
                    continue
                if kind == "state":
                    for output in row["outputs"]: output["sha256"] = "different"
                elif kind == "active": row["observations"]["trajectory"][0]["active"] += 1
                elif kind == "arm": row["observations"]["result"]["arm"] = "prefetch_compact"
                else: row["observations"]["result"]["cycles" if kind == "registration" else kind] += 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                analysis.summarize(rows, reference, before=before)


if __name__ == "__main__":
    unittest.main()
