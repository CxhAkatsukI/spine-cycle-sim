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
        out = {"stage_ratios": {"r_ratios": {}}, "stage_receipts": {}}
        figure.record_cc_topology(out, matrix, gate)
        self.assertEqual(out["cc_topology_stage"], pin)
        self.assertEqual(out["stage_receipts"]["r_au_slice"], pin)
        self.assertEqual(out["stage_ratios"]["r_ratios"]["au_slice"], 1.1)
        with self.assertRaisesRegex(ValueError, "resident admission"):
            figure.record_cc_topology(out, matrix, dict(gate, image={"sha256": "different"}))

    def pair(self, algorithm, dataset):
        gr = {"binary": {"sha256": "gr"}, "driver_reported_mhz": [150], "bdf": "bdf"}
        spine = {"binary": {"path": "/spine.xclbin", "sha256": "spine"},
                 "driver_reported_mhz": [145], "bdf": "bdf"}
        arms = {arm: dict(stdout=self.receipt(f"{algorithm}-{dataset}-{arm}-out", {}),
                          stderr=self.receipt(f"{algorithm}-{dataset}-{arm}-err", {}),
                          clock=clock, clock_evidence=clock)
                for arm, clock in (("spine", spine), ("gr", gr))}
        b = figure.BOUNDARIES[algorithm]
        r = {"retention_gate_pass": True, "candidate_over_reference": 1.15}
        g = {"retention_gate_pass": True, "current_over_reference": 1.12}

        def stage(role, comparison):
            pin = self.receipt(f"{algorithm}-{dataset}-{role}",
                               {"algorithm": algorithm, "comparison": comparison})
            return dict(report=pin, comparison=comparison, candidate_clock=gr)

        if algorithm == "cc":
            pair = dict(boundary=b, gr_ms=5, spine_ms=10, gr_over_spine=0.5, gr_supersteps=2, spine_rounds=2)
        else:
            pair = dict(boundary=b, gr_wall_ms=5, spine_wall_ms=10, speedup_gr_over_spine=0.5,
                        gr_rounds=0, spine_rounds=0)
        gates = dict(status="BASELINE_STAGES_ADMITTED_NOT_CONVERGENCE", algorithm=algorithm,
                     g=dict(stage("g", g), reference=self.receipt("g-reference", {})),
                     r=stage("r", r), resident_mhz=[150], image=gr["binary"])
        graph = self.root / f"{algorithm}-{dataset}.graph"
        graph.write_text("2 1 1\n0 1 1\n1 0 1\n")
        case = dict(dataset=dataset, spine_binary=spine["binary"]["path"], graph=str(graph),
                    vertices=2, edges=1, updates=1, source=0)
        child = dict(status=figure.MEASURED, bdf="bdf", dataset=dataset, algorithm=algorithm, boundary=b,
                     repetitions_per_arm=1, warmups=0, stage_gates=gates, attempts=["spine", "gr"],
                     arms=arms, case=case, pins=[dict(spine["binary"]), identity(graph)], pair=pair,
                     comparison_log=self.receipt(f"{algorithm}-{dataset}-pair", pair))
        return child, gates, stage("odd", r)

    def test_waiting_failures_and_all_rows_retained(self):
        save(self.paths["cc_matrix"], {"status": "MATRIX_NEEDS_REVIEW",
                                       "cases": {"SU": {"status": "FAILED_RETAINED", "error": "timeout"}}})
        result = figure.export(self.paths)
        self.assertEqual(len(result["rows"]), 24)
        self.assertTrue(all("gr_over_spine" not in row for row in result["rows"]))
        self.assertIn("timeout", {row.get("error") for row in result["rows"]})

    def test_diagnostic_keeps_losses_and_missing_rows_separate_from_parity(self):
        paths = []
        for algorithm in ("weighted_sssp", "cc"):
            path = self.root / f"diagnostic-{algorithm}.json"
            cases = {dataset: {"status": "NOT_REQUESTED"} for dataset in figure.DATASETS}
            if algorithm == "cc":
                cases["AU"] = {"status": figure.MEASURED, "result": self.receipt("cc-au-child", {})}
                cases["SU"] = {"status": "FAILED_RETAINED", "error": "row overflow"}
            save(path, dict(algorithm=algorithm, r_retention_all_controls_pass=False, cases=cases,
                            baseline={"image": "exact"}, additional_r_gates={
                                "amazon_odd": "passing", "au_slice": "diagnostic miss"}))
            paths.append(path)
        with patch.object(figure, "measured", return_value={"winner": "G+R", "gr_over_spine": 0.3}) as check:
            result = figure.export_diagnostic(paths)
        self.assertEqual(len(result["rows"]), 24)
        by_case = {(row["algorithm"], row["dataset"]): row for row in result["rows"]}
        loss = by_case["cc", "AU"]
        self.assertEqual((loss["status"], loss["winner"], loss["gr_over_spine"]), (figure.MEASURED, "G+R", 0.3))
        self.assertEqual(loss["r_validation_scope"], "amazon_pass_au_outside_15_percent")
        self.assertEqual(check.call_args.kwargs, {"topology_miss": "diagnostic miss"})
        self.assertEqual(by_case["cc", "SU"]["error"], "row overflow")
        self.assertNotIn("gr_over_spine", by_case["cc", "SU"])
        self.assertEqual(by_case["respr", "AU"]["status"], "NOT_RECORDED")

    def test_terminal_parent_blocks_unmeasured_rows_but_not_attempted_rows(self):
        save(self.paths["respr_screen"], dict(status="NOT_ADMITTED", error="R above 15%", cases=[
            {"status": "PREDECLARED", "case": {"dataset": dataset}} for dataset in ("R19", "Flickr")
        ]))
        save(self.paths["respr_matrix"], dict(status="NOT_ADMITTED", error="resident screen failed", cases=[
            {"status": "PREDECLARED", "case": {"dataset": "AU"}},
            {"status": "FAILED_RETAINED", "error": "device timeout", "case": {"dataset": "SU"}},
        ]))
        result = figure.export(self.paths)
        rows = {row["dataset"]: row for row in result["rows"] if row["algorithm"] == "respr"}
        self.assertEqual(rows["R19"]["error"], "NOT_ADMITTED: R above 15%")
        self.assertEqual(rows["AU"]["blocked_by"], "respr_matrix")
        self.assertEqual(rows["SU"]["error"], "device timeout")
        self.assertEqual(result["respr_propagation_screen"]["blocked_by"], "respr_screen")
        self.assertEqual(result["rows"][0]["status"], "WAITING")
        output = self.root / "blocked.csv"
        figure.write_csv(output, result["rows"])
        with output.open(newline="") as stream:
            (au,) = [row for row in csv.DictReader(stream)
                     if (row["algorithm"], row["dataset"]) == ("respr", "AU")]
        self.assertEqual((au["status"], au["blocked_by"], au["gr_over_spine"]),
                         ("BLOCKED_BY_TERMINAL_JOURNAL", "respr_matrix", ""))

    def test_cc_special_pair_retains_loss_and_boundary(self):
        child, gates, odd = self.pair("cc", "R19")
        save(self.paths["cc_matrix"], dict(status="MEASURED", cases={}, baseline=gates, odd_r=odd))
        save(self.paths["cc_r19"], dict(status=figure.MEASURED, requested_pair=True,
                                       result=self.receipt("child", child)))
        result = figure.export(self.paths)
        (row,) = [r for r in result["rows"] if r["status"] == figure.MEASURED]
        self.assertEqual((row["winner"], row["gr_over_spine"], row["boundary"]),
                         ("G+R", 0.5, figure.cc_resident_wall.BOUNDARY))
        self.assertEqual(row["r_validation_scope"], "amazon_only_diagnostic")
        self.assertIs(row["same_driver_clocks"], False)
        self.assertEqual(row["stage_receipts"], {
            "g": gates["g"]["report"], "g_reference": gates["g"]["reference"],
            "r_amazon": gates["r"]["report"], "r_amazon_odd": odd["report"],
        })
        save(Path(child["arms"]["gr"]["stdout"]["path"]), {"changed": True})
        result = figure.export(self.paths)
        (rejected,) = [r for r in result["rows"] if r["status"] == "RECEIPT_REJECTED"]
        self.assertNotIn("gr_over_spine", rejected)

    def test_changed_independent_stage_receipt_rejects_pair(self):
        child, gates, odd = self.pair("weighted_sssp", "AU")
        pin = self.receipt("child", child)
        save(self.paths["sssp_au"], dict(status=figure.MEASURED, requested_pair=True, result=pin))
        save(self.paths["sssp_matrix"], dict(status="MEASURED", cases={}, baseline=gates,
                                            odd_r=odd, au_result=pin))
        self.assertEqual(figure.export(self.paths)["rows"][0]["status"], figure.MEASURED)
        save(Path(gates["g"]["report"]["path"]), {"changed": True})
        row = figure.export(self.paths)["rows"][0]
        self.assertEqual(row["status"], "RECEIPT_REJECTED")
        self.assertNotIn("gr_over_spine", row)

    def test_cc_au_retains_spine_receipt_without_fabricating_a_second_launch(self):
        child, gates, odd = self.pair("cc", "AU")
        pin = self.receipt("retained-spine", {})
        child.update(attempts=["gr"], retained_spine=pin, cpu_affinity=[124, 125],
                     additional_r_gates={"amazon_odd": odd, "au_slice": {}})
        child["pins"].append(pin)
        with patch.object(figure.spine_cc_warm_receipt, "replay", return_value=(child["arms"]["spine"], [])):
            result = figure.measured("cc", "AU", child, child, gates, odd, gates["image"])
            self.assertEqual(result["retained_spine"], pin)
            self.assertEqual(result["winner"], "G+R")
            child["attempts"].insert(0, "spine")
            with self.assertRaisesRegex(ValueError, "exactly one Spine run"):
                figure.measured("cc", "AU", child, child, gates, odd, gates["image"])
            child["attempts"] = ["gr"]
            child["additional_r_gates"].pop("au_slice")
            with self.assertRaisesRegex(ValueError, "cross-topology baseline"):
                figure.measured("cc", "AU", child, child, gates, odd, gates["image"])

    def test_warm_cc_export_replays_layout_route_and_raw_wall_results(self):
        child, gates, odd = self.pair("cc", "SU")
        wall = figure.cc_resident_wall
        warm = figure.spine_cc_warm_receipt
        case, arms = child["case"], child["arms"]
        child.update(bdf=warm.BDF, cpu_affinity=list(warm.AFFINITY))
        gates["image"]["path"] = "/gr.xclbin"
        for arm in arms.values():
            arm["clock"]["bdf"] = warm.BDF
        for key in ("spine_host", "gr_host", "graph_slice", "update_slice"):
            case[key] = self.receipt(key, {})["path"]
        inputs = self.receipt("inputs", {key: {"path": case[key + "_slice"]} for key in ("graph", "update")})
        layout, route = self.receipt("layout", {}), self.receipt("route", {})
        packet = self.receipt("packet", dict(inputs=inputs["path"], **{
            key: case[key] for key in ("spine_binary", "spine_host", "gr_host")}))
        child["pins"] += [inputs, layout, route, packet, identity(case["spine_host"])]
        child.update(warm_layout=layout, wall_packet=packet, commands=wall.commands(case, gates, self.root))
        for name, command in child["commands"].items():
            arms[name]["command"] = command
        comparison = {"retention_gate_pass": True, "candidate_over_reference": 1.1}
        au_r = self.receipt("au-cc-r", {"algorithm": "cc", "comparison": comparison})
        au = dict(report=au_r, comparison=comparison, candidate_clock=arms["gr"]["clock"])
        child["additional_r_gates"] = {"amazon_odd": odd, "au_slice": au}
        matrix = dict(status="MEASURED", baseline=gates, odd_r=odd, au_slice_r=au, stages={
            "au_slice": {"ready": True, "receipt": au_r}}, cases={"R19": {"status": "NOT_REQUESTED"}})
        paths = dict(self.paths)
        paths.pop("cc_r19")

        def row():
            matrix["cases"]["SU"] = {"status": figure.MEASURED, "result": self.receipt("warm-child", child)}
            save(paths["cc_matrix"], matrix)
            return next(row for row in figure.export(paths)["rows"]
                        if (row["algorithm"], row["dataset"]) == ("cc", "SU"))

        with (patch.object(warm, "BALANCED_HOST_SHA256", identity(case["spine_host"])["sha256"]),
              patch.object(wall, "GR_HOST", identity(case["gr_host"])["sha256"]),
              patch.object(warm, "route_pins", return_value=[route]),
              patch.object(wall.spine_cc_layout, "replay", return_value=({}, [layout, inputs])) as replay,
              patch.object(wall.cc_resident_results, "analyze", return_value=child["pair"]) as analyze):
            result = row()
            self.assertEqual((result["status"], result["warm_layout"], result["winner"]),
                             (figure.MEASURED, layout, "G+R"))
            replay.assert_called_once_with(layout["path"], "SU", host=identity(case["spine_host"]),
                                           inputs=inputs["path"], frozen=identity(case["graph"]))
            analyze.assert_called_once()
            analyze.return_value = dict(child["pair"], spine_ms=11)
            self.assertIn("raw logs", row()["error"])
            analyze.return_value = child["pair"]
            child["pins"].remove(route)
            self.assertIn("pre-measurement pins", row()["error"])
            child["pins"].append(route)
            child["additional_r_gates"]["au_slice"] = dict(au, report=route)
            rejected = row()
            self.assertIn("matrix R controls", rejected["error"])
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
        self.assertEqual(result["rows"][0]["status"], "BLOCKED_BY_TERMINAL_JOURNAL")
        self.assertEqual(result["rows"][0]["blocked_by"], "sssp_matrix")

    def respr_screen(self, dataset, rounds, status="MEASURED"):
        child, _, _ = self.pair("respr", dataset)
        decision = {"retention_gate_pass": True, "current_over_reference": 1.15}
        board = self.root / "board-once/results.json"
        board.parent.mkdir(exist_ok=True)
        save(board, {})
        gates = dict(g_control=decision, r_controls={key: decision for key in ("amazon", "skewed_sources")},
                     resident_mhz=[150], pins=[identity(board)])
        pair = dict(child["pair"], gr_rounds=rounds[0], spine_rounds=rounds[1])
        requires_propagation = dataset == "Flickr"
        row = dict(status=status, case=dict(child["case"], algorithm="residual_pagerank",
                                           requires_propagation=requires_propagation),
                   rows=child["arms"], attempts=[{"arm": arm} for arm in ("spine", "gr")],
                   pair=dict(pair, meets_propagation_screen=not requires_propagation or min(rounds) > 0,
                             positive_propagation_on_both=min(rounds) > 0),
                   comparison_log=self.receipt(f"respr-{dataset}-comparator", pair))
        screen = dict(status="PAIRED_SCREEN_MEASURED", cases=[row], bdf="bdf", repetitions_per_arm=1,
                      warmups=0, stage_gates=gates,
                      pins={"spine_image": child["pins"][0], dataset.lower(): child["pins"][1]})
        image = child["arms"]["gr"]["clock"]["binary"]
        self.save_respr_screen(screen, image)
        return screen, image

    def save_respr_screen(self, screen, image):
        save(self.paths["respr_screen"], screen)
        save(self.paths["respr_matrix"], dict(status="MEASURED", cases=[], stage_gates=screen["stage_gates"],
                                            image=image, parent=identity(self.paths["respr_screen"])))

    def test_respr_correction_only_is_labeled_and_requires_both_r_gates(self):
        screen, _ = self.respr_screen("R19", (0, 0))
        result = figure.export(self.paths)["rows"][-1]
        self.assertEqual(result["status"], figure.MEASURED)
        self.assertIs(result["respr_propagated_on_both"], False)
        gates = screen["stage_gates"]
        self.assertEqual(result["stage_receipts"]["admission"], gates["pins"])
        with self.assertRaises(ValueError):
            figure.summarize_gates("respr", dict(gates, r_controls={"amazon": gates["g_control"]}), None)
        save(Path(gates["pins"][0]["path"]), {"changed": True})
        result = figure.export(self.paths)["rows"][-1]
        self.assertEqual(result["status"], "RECEIPT_REJECTED")
        self.assertNotIn("gr_over_spine", result)

    def test_respr_flickr_propagation_is_pinned_and_outside_figure_rows(self):
        screen, image = self.respr_screen("Flickr", (1, 2))
        result = figure.export(self.paths)
        self.assertEqual(len(result["rows"]), 24)
        self.assertNotIn("Flickr", {row["dataset"] for row in result["rows"]})
        propagation = result["respr_propagation_screen"]
        self.assertEqual((propagation["status"], propagation["winner"], propagation["gr_rounds"],
                          propagation["spine_rounds"]), (figure.MEASURED, "G+R", 1, 2))
        save(self.paths["respr_screen"], dict(screen, note="replaced"))
        propagation = figure.export(self.paths)["respr_propagation_screen"]
        self.assertEqual(propagation["status"], "RECEIPT_REJECTED")
        self.assertNotIn("gr_over_spine", propagation)

    def test_respr_flickr_without_propagation_cannot_publish_speedup(self):
        status = "RETAINED_WITHOUT_REQUIRED_PROPAGATION"
        screen, image = self.respr_screen("Flickr", (0, 2), status)
        propagation = figure.export(self.paths)["respr_propagation_screen"]
        self.assertEqual(propagation["status"], status)
        self.assertNotIn("gr_over_spine", propagation)
        row = screen["cases"][0]
        row.update(status="MEASURED", pair=dict(row["pair"], positive_propagation_on_both=True,
                                                meets_propagation_screen=True))
        self.save_respr_screen(screen, image)
        propagation = figure.export(self.paths)["respr_propagation_screen"]
        self.assertEqual(propagation["status"], "RECEIPT_REJECTED")
        self.assertNotIn("gr_over_spine", propagation)

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
