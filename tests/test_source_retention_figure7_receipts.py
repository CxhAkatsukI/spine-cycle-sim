"""Check that the Figure 7 index cannot turn incomplete receipts into speedups."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    figure7_receipts as figure,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity, save


class Figure7ReceiptsTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.paths = {key: self.root / f"{key}.json" for key in figure.ROLES}
        for path in self.paths.values():
            save(path, {"status": "WAITING"})
        replay = patch.object(figure.clocks, "replay", side_effect=lambda evidence: evidence)
        replay.start()
        self.addCleanup(replay.stop)

    def receipt(self, name, payload):
        path = self.root / f"{name}.json"
        save(path, payload)
        return identity(path)

    def pair(self, algorithm, dataset):
        gr = {"binary": {"sha256": "gr"}, "driver_reported_mhz": [150], "bdf": "bdf"}
        spine = {"binary": {"sha256": "spine"}, "driver_reported_mhz": [145], "bdf": "bdf"}
        arms = {arm: dict(stdout=self.receipt(arm + "-out", {}), stderr=self.receipt(arm + "-err", {}),
                          clock=clock, clock_evidence=clock)
                for arm, clock in (("spine", spine), ("gr", gr))}
        b = figure.BOUNDARIES[algorithm]
        r = {"comparison": {"retention_gate_pass": True, "candidate_over_reference": 1.15}}
        g = {"retention_gate_pass": True, "current_over_reference": 1.12}
        if algorithm == "cc":
            pair = dict(boundary=b, gr_ms=5, spine_ms=10, gr_over_spine=0.5, gr_supersteps=2, spine_rounds=2)
        else:
            pair = dict(boundary=b, gr_wall_ms=5, spine_wall_ms=10, speedup_gr_over_spine=0.5,
                        gr_rounds=0, spine_rounds=0)
        gates = dict(status="BASELINE_STAGES_ADMITTED_NOT_CONVERGENCE", algorithm=algorithm,
                     g={"comparison": g}, r=r, resident_mhz=[150], image=gr["binary"])
        child = dict(status=figure.MEASURED, bdf="bdf", dataset=dataset, algorithm=algorithm, boundary=b,
                     repetitions_per_arm=1, warmups=0, stage_gates=gates, attempts=["spine", "gr"],
                     arms=arms, case={"dataset": dataset}, pair=pair, comparison_log=self.receipt("pair", pair))
        return child, gates, r

    def test_waiting_failures_and_all_rows_retained(self):
        save(self.paths["cc_matrix"], {"status": "MATRIX_NEEDS_REVIEW",
                                       "cases": {"SU": {"status": "FAILED_RETAINED", "error": "timeout"}}})
        result = figure.export(self.paths)
        self.assertEqual(len(result["rows"]), 24)
        self.assertTrue(all("gr_over_spine" not in row for row in result["rows"]))
        self.assertIn("timeout", {row.get("error") for row in result["rows"]})

    def test_cc_special_pair_retains_loss_and_boundary(self):
        child, gates, odd = self.pair("cc", "R19")
        save(self.paths["cc_matrix"], dict(status="MEASURED", cases={}, baseline=gates, odd_r=odd))
        save(self.paths["cc_r19"], dict(status=figure.MEASURED, requested_pair=True,
                                       result=self.receipt("child", child)))
        result = figure.export(self.paths)
        (row,) = [r for r in result["rows"] if r["status"] == figure.MEASURED]
        self.assertEqual((row["winner"], row["gr_over_spine"], row["boundary"]),
                         ("G+R", 0.5, figure.cc_resident_wall.BOUNDARY))
        save(Path(child["arms"]["gr"]["stdout"]["path"]), {"changed": True})
        result = figure.export(self.paths)
        (rejected,) = [r for r in result["rows"] if r["status"] == "RECEIPT_REJECTED"]
        self.assertNotIn("gr_over_spine", rejected)

    def test_sssp_au_requires_matrix_to_pin_screen(self):
        child, gates, odd = self.pair("weighted_sssp", "AU")
        save(self.paths["sssp_au"], dict(status=figure.MEASURED, requested_pair=True,
                                        result=self.receipt("child", child)))
        save(self.paths["sssp_matrix"], dict(status="MEASURED", cases={}, baseline=gates, odd_r=odd,
                                            au_result={"sha256": "other"}))
        row = figure.export(self.paths)["rows"][0]
        self.assertEqual(row["status"], "RECEIPT_REJECTED")
        self.assertNotIn("gr_over_spine", row)

    def test_respr_correction_only_is_labeled_and_requires_both_r_gates(self):
        child, _, _ = self.pair("respr", "R19")
        decision = {"retention_gate_pass": True, "current_over_reference": 1.15}
        gates = dict(g_control=decision, r_controls={key: decision for key in ("amazon", "skewed_sources")},
                     resident_mhz=[150])
        row = dict(status="MEASURED", case={"dataset": "R19", "algorithm": "residual_pagerank"},
                   rows=child["arms"], attempts=[{"arm": arm} for arm in ("spine", "gr")],
                   pair=dict(child["pair"], meets_propagation_screen=True, positive_propagation_on_both=False),
                   comparison_log=child["comparison_log"])
        save(self.paths["respr_screen"], dict(status="PAIRED_SCREEN_MEASURED", cases=[row], bdf="bdf",
                                             repetitions_per_arm=1, warmups=0, stage_gates=gates))
        image = child["arms"]["gr"]["clock"]["binary"]
        save(self.paths["respr_matrix"], dict(status="MEASURED", cases=[], stage_gates=gates, image=image))
        result = figure.export(self.paths)["rows"][-1]
        self.assertEqual(result["status"], figure.MEASURED)
        self.assertIs(result["respr_propagated_on_both"], False)
        with self.assertRaises(ValueError):
            figure.summarize_gates("respr", dict(gates, r_controls={"amazon": decision}), None)


if __name__ == "__main__":
    unittest.main()
