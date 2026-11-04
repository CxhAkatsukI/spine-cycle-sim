"""Check that the Figure 7 index cannot turn incomplete receipts into speedups."""

import csv
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

    def test_cc_topology_export_requires_exact_stage_receipt_and_image(self):
        comparison = {"retention_gate_pass": True, "candidate_over_reference": 1.1}
        pin = self.receipt("au-r", {"algorithm": "cc", "comparison": comparison})
        image = {"sha256": "gr"}
        clocks = [150, 500, 450, 0]
        gate = {"image": image, "resident_mhz": clocks}
        matrix = {"stages": {"au_slice": {"ready": True, "receipt": pin}},
                  "au_slice_r": {"report": pin, "comparison": comparison, "candidate_clock": {
                      "binary": image, "driver_reported_mhz": clocks}}}
        out = {"stage_ratios": {"r_ratios": {}}}
        figure.record_cc_topology(out, matrix, gate)
        self.assertEqual(out["cc_topology_stage"], pin)
        self.assertEqual(out["stage_ratios"]["r_ratios"]["au_slice"], 1.1)
        with self.assertRaisesRegex(ValueError, "resident admission"):
            figure.record_cc_topology(out, matrix, dict(gate, image={"sha256": "different"}))

    def pair(self, algorithm, dataset):
        gr = {"binary": {"sha256": "gr"}, "driver_reported_mhz": [150], "bdf": "bdf"}
        spine = {"binary": {"path": "/spine.xclbin", "sha256": "spine"},
                 "driver_reported_mhz": [145], "bdf": "bdf"}
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
        graph = self.root / f"{algorithm}-{dataset}.graph"
        graph.write_text("2 1 1\n0 1 1\n1 0 1\n")
        case = dict(dataset=dataset, spine_binary=spine["binary"]["path"], graph=str(graph),
                    vertices=2, edges=1, updates=1, source=0)
        child = dict(status=figure.MEASURED, bdf="bdf", dataset=dataset, algorithm=algorithm, boundary=b,
                     repetitions_per_arm=1, warmups=0, stage_gates=gates, attempts=["spine", "gr"],
                     arms=arms, case=case, pins=[dict(spine["binary"]), identity(graph)], pair=pair,
                     comparison_log=self.receipt(f"{algorithm}-{dataset}-pair", pair))
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
        self.assertIs(row["same_driver_clocks"], False)
        save(Path(child["arms"]["gr"]["stdout"]["path"]), {"changed": True})
        result = figure.export(self.paths)
        (rejected,) = [r for r in result["rows"] if r["status"] == "RECEIPT_REJECTED"]
        self.assertNotIn("gr_over_spine", rejected)

    def test_board_observed_spine_must_match_the_predeclared_image(self):
        child, gates, odd = self.pair("weighted_sssp", "AU")
        child["pins"][0]["sha256"] = "different-spine"
        pin = self.receipt("child", child)
        save(self.paths["sssp_au"], dict(status=figure.MEASURED, requested_pair=True, result=pin))
        save(self.paths["sssp_matrix"], dict(status="MEASURED", cases={}, baseline=gates,
                                            odd_r=odd, au_result=pin))
        row = figure.export(self.paths)["rows"][0]
        self.assertEqual(row["status"], "RECEIPT_REJECTED")
        self.assertIn("measured Spine image", row["error"])
        self.assertNotIn("gr_over_spine", row)

    def test_sssp_au_requires_matrix_to_pin_screen(self):
        child, gates, odd = self.pair("weighted_sssp", "AU")
        save(self.paths["sssp_au"], dict(status=figure.MEASURED, requested_pair=True,
                                        result=self.receipt("child", child)))
        save(self.paths["sssp_matrix"], dict(status="MEASURED", cases={}, baseline=gates, odd_r=odd,
                                            au_result={"sha256": "other"}))
        row = figure.export(self.paths)["rows"][0]
        self.assertEqual(row["status"], "RECEIPT_REJECTED")
        self.assertNotIn("gr_over_spine", row)

    def test_sssp_cross_topology_evidence_is_exported_for_the_au_screen(self):
        child, gates, odd = self.pair("weighted_sssp", "AU")
        comparison = {"retention_gate_pass": True, "candidate_over_reference": 1.1}
        au_r = self.receipt("au-r", {"algorithm": "weighted_sssp", "comparison": comparison})
        stage = dict(report=au_r, comparison=comparison, candidate_clock=child["arms"]["gr"]["clock"])
        child["additional_r_gates"] = {"au_slice": stage}
        pin = self.receipt("child", child)
        save(self.paths["sssp_au"], dict(status=figure.MEASURED, requested_pair=True, result=pin,
                                        stages={"au_slice": {"ready": True, "receipt": au_r}}))
        matrix = dict(status="MEASURED", cases={}, baseline=gates, odd_r=odd, au_result=pin,
                      require_au_topology=True, au_slice_r=stage)
        save(self.paths["sssp_matrix"], matrix)
        row = figure.export(self.paths)["rows"][0]
        self.assertEqual(row["r_validation_scope"], "amazon_and_askubuntu")
        self.assertEqual(row["au_topology_stage"], au_r)
        self.assertEqual(row["stage_ratios"]["r_ratios"]["au_slice"], 1.1)
        save(self.paths["sssp_matrix"], dict(matrix, au_slice_r=dict(stage, report=pin)))
        row = figure.export(self.paths)["rows"][0]
        self.assertEqual(row["status"], "RECEIPT_REJECTED")
        self.assertNotIn("gr_over_spine", row)

    def test_complete_matrices_replace_separate_au_and_r19_screens(self):
        paths = {key: path for key, path in self.paths.items() if key not in figure.OPTIONAL_SCREENS}
        for role, algorithm, dataset in (("sssp_matrix", "weighted_sssp", "AU"), ("cc_matrix", "cc", "R19")):
            child, gates, odd = self.pair(algorithm, dataset)
            save(paths[role], dict(status="MEASURED", baseline=gates, odd_r=odd, cases={
                dataset: {"status": figure.MEASURED, "result": self.receipt(f"{role}-child", child)},
            }))
        result = figure.export(paths)
        self.assertEqual(len(result["rows"]), 24)
        self.assertEqual([(row["algorithm"], row["dataset"]) for row in result["rows"]
                          if row["status"] == figure.MEASURED], [("weighted_sssp", "AU"), ("cc", "R19")])
        with self.assertRaisesRegex(ValueError, "exactly one journal source"):
            figure.export(self.paths)
        save(paths["sssp_matrix"], {"status": "FAILED_RETAINED", "error": "odd gate", "cases": {
            "AU": {"status": "NOT_REQUESTED"},
        }})
        result = figure.export(paths)
        self.assertEqual(result["journal_errors"], {"sssp_matrix": "odd gate"})
        self.assertEqual(result["rows"][0]["status"], "NOT_REQUESTED")

    def test_respr_correction_only_is_labeled_and_requires_both_r_gates(self):
        child, _, _ = self.pair("respr", "R19")
        decision = {"retention_gate_pass": True, "current_over_reference": 1.15}
        gates = dict(g_control=decision, r_controls={key: decision for key in ("amazon", "skewed_sources")},
                     resident_mhz=[150])
        row = dict(status="MEASURED", case=dict(child["case"], algorithm="residual_pagerank"),
                   rows=child["arms"], attempts=[{"arm": arm} for arm in ("spine", "gr")],
                   pair=dict(child["pair"], meets_propagation_screen=True, positive_propagation_on_both=False),
                   comparison_log=child["comparison_log"])
        save(self.paths["respr_screen"], dict(status="PAIRED_SCREEN_MEASURED", cases=[row], bdf="bdf",
                                             repetitions_per_arm=1, warmups=0, stage_gates=gates,
                                             pins={"spine_image": child["pins"][0], "r19": child["pins"][1]}))
        image = child["arms"]["gr"]["clock"]["binary"]
        save(self.paths["respr_matrix"], dict(status="MEASURED", cases=[], stage_gates=gates, image=image))
        result = figure.export(self.paths)["rows"][-1]
        self.assertEqual(result["status"], figure.MEASURED)
        self.assertIs(result["respr_propagated_on_both"], False)
        with self.assertRaises(ValueError):
            figure.summarize_gates("respr", dict(gates, r_controls={"amazon": decision}), None)

    def test_csv_keeps_unmeasured_cases_blank_and_pins_measured_workload(self):
        child, gates, odd = self.pair("cc", "SU")
        pin = self.receipt("cc-su-child", child)
        save(self.paths["cc_matrix"], dict(status="MATRIX_NEEDS_REVIEW", baseline=gates, odd_r=odd, cases={
            "SU": {"status": figure.MEASURED, "result": pin},
            "WK": {"status": "FAILED_RETAINED", "error": "timeout"},
        }))
        result = figure.export(self.paths)
        output = self.root / "figure7.csv"
        figure.write_csv(output, result["rows"])
        with output.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 24)
        measured = next(row for row in rows if row["status"] == figure.MEASURED)
        self.assertEqual((measured["winner"], measured["graph_sha256"], measured["comparison_sha256"]),
                         ("G+R", child["pins"][1]["sha256"], child["comparison_log"]["sha256"]))
        failed = next(row for row in rows if row["status"] == "FAILED_RETAINED")
        self.assertEqual((failed["error"], failed["gr_over_spine"]), ("timeout", ""))
        Path(child["case"]["graph"]).write_text("2 1 1\n0 1 1\n1 0 2\n")
        changed = next(row for row in figure.export(self.paths)["rows"] if row["status"] == "RECEIPT_REJECTED")
        self.assertNotIn("gr_over_spine", changed)
        self.assertIn("raw log changed", changed["error"])


if __name__ == "__main__":
    unittest.main()
