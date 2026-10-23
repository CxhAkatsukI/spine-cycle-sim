"""Keep the historical-input follow-up separate and conserve propagation work."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import analysis
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm import (
    matrix, propagation_followup as followup, study,
)


def fixture():
    identity = hashlib.sha256(b"input").hexdigest()
    cases, rows = [], []
    for dataset, _, run_id in matrix.HISTORICAL_RESIDUAL:
        case = dict(dataset=dataset, algorithm="ResPR", updates=8, physical_update_records=16,
            figure=9, vertices=10, initial_edges=20, graph="graph", update_file="update", manifest="manifest",
            historical_run_id=run_id)
        arm = dict(cycles=100, rounds=1, read_bytes=64, write_bytes=64, energy_pj=1,
            state_hashes=dict(old_state="old", expected="oracle", final="final"),
            correction_oracle_directed=True, evidence="case")
        cases.append(case)
        rows.append(analysis.comparison(case, {a: copy.deepcopy(arm) for a in ("spine", "gr")}))
    return dict(status="COMPLETE_SUPPORTED_SCOPE", pins_unchanged=True, failures=[], baseline_admitted=False,
        case_set="historical-residual-u8", model=dict(residual_epsilon=study.residual_threshold(1e-6)),
        matrix=cases, rows=rows, pins=[dict(path=p, sha256=identity) for p in ("graph", "update", "manifest")])


class PropagationFollowupTests(unittest.TestCase):
    def run_summary(self, report, *, nonempty=True, computed_edges=None):
        count = int(nonempty)
        propagation = dict(nonempty_rounds=count, active_vertex_visits=count,
            reader_edges=10 * count, computed_edges=10 * count if computed_edges is None else computed_edges)
        text = "CORRECTION_TRACE " + json.dumps(dict(oracle_directed=True, active_vertices=count))
        text += "\nPROPAGATION_TRACE " + json.dumps(propagation)
        text += "\nR_SCAN_TRACE " + json.dumps(dict(rounds=1, live_edges_scanned=36))
        oracle = dict(maximum_error=0, l1_error=0, l1_error_bound=1)
        def read(name):
            return (f"round,start,end,active_in,reader_sources,active_out\n0,0,100,{count},{count},0\n".encode()
                    if name.endswith("rounds.csv") else b"input")
        with patch.object(followup.validation, "source_snapshot"), \
                patch.object(followup.validation, "core_gates"), \
                patch.object(followup, "check_arm", return_value=(text, oracle, 0)):
            return followup.summarize(report, {}, read)

    def test_complete_nonempty_cases_can_retain_a_spine_loss(self):
        report = fixture()
        for row in report["rows"]:
            row["spine"]["cycles"] = 200
        summary = self.run_summary(report)
        self.assertFalse(summary["baseline_admitted"])
        self.assertEqual([r["speedup_gr_over_spine"] for r in summary["rows"]], [0.5] * 3)
        self.assertTrue(all(r["has_nonempty_propagation"] for r in summary["rows"]))

    def test_zero_work_is_reported_not_relabeled_as_propagation(self):
        summary = self.run_summary(fixture(), nonempty=False)
        self.assertTrue(all(not r["has_nonempty_propagation"] for r in summary["rows"]))

    def test_missing_cases_or_work_mismatch_cannot_be_sealed(self):
        report = fixture()
        report["rows"].pop()
        with self.assertRaisesRegex(ValueError, "all three"):
            self.run_summary(report)
        with self.assertRaisesRegex(ValueError, "work or complete-graph scan"):
            self.run_summary(fixture(), computed_edges=11)

    def test_wrong_threshold_initial_state_or_physical_batch_is_rejected(self):
        report = fixture()
        report["model"]["residual_epsilon"] = study.residual_threshold(1e-7)
        with self.assertRaisesRegex(ValueError, "fixed-threshold"):
            self.run_summary(report)
        report = fixture()
        report["rows"][0]["gr"]["state_hashes"]["old_state"] = "different"
        with self.assertRaisesRegex(ValueError, "shared initial"):
            self.run_summary(report)
        report = fixture()
        report["matrix"][0]["physical_update_records"] = 8
        with self.assertRaisesRegex(ValueError, "reciprocal historical"):
            self.run_summary(report)


if __name__ == "__main__":
    unittest.main()
