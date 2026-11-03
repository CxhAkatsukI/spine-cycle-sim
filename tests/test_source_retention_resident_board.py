import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    resident_admission as admission, resident_board as board, resident_results as results,
)


class ResidentAdmissionTest(unittest.TestCase):
    def setUp(self):
        self.host = {"path": "/host", "sha256": admission.HOST_SHA256}
        self.pins = [{"path": "/result", "sha256": "x"}]
        self.comparison = {"current_over_reference": 1.15, "at_most_15_percent_slower": True}
        self.summary = {"pairs": [{"stage": "R", "case": name, "clock_evidence_recorded": True,
                                  **self.comparison} for name in ("skewed_sources", "amazon")]}
        self.g = {"status": admission.G_PASS, "r_status": admission.R_PASS, "r_pins": self.pins,
                  "bdf": admission.BDF, "device": admission.DEVICE, "repetitions": 1,
                  "comparison": dict(self.comparison), "pins": {"host": self.host}}

    def validate(self):
        return admission.validate_gates(self.summary, self.g, self.pins, self.host)

    def test_threshold_inclusive_and_per_stage(self):
        self.assertEqual(len(self.validate()), 2)
        self.summary["pairs"][0]["current_over_reference"] = 1.150001
        with self.assertRaises(admission.NotAdmitted):
            self.validate()

    def test_rejects_other_route_even_when_both_pass(self):
        self.g["r_pins"] = [{"path": "/other", "sha256": "x"}]
        with self.assertRaises(admission.NotAdmitted):
            self.validate()

    def test_rejects_same_pass_with_wrong_native_host_profile(self):
        with self.assertRaises(admission.NotAdmitted):
            admission.validate_gates(self.summary, self.g, self.pins, self.host, host_sha256="wrong profile")

    def test_rejects_missing_or_duplicate_case(self):
        self.summary["pairs"][0]["case"] = "amazon"
        with self.assertRaises(admission.NotAdmitted):
            self.validate()

    def test_rejects_g_numerical_failure(self):
        self.g["comparison"]["current_over_reference"] = float("nan")
        with self.assertRaises(admission.NotAdmitted):
            self.validate()


class ResidentResultTest(unittest.TestCase):
    CASE = {"dataset": "Flickr", "graph": "/tmp/flickr.graph", "algorithm": "residual_pagerank",
            "source": 0, "vertices": 2552, "edges": 8192, "updates": 16, "requires_propagation": True}

    def gr(self, rounds):
        return ("GRASU_REGRAPH_DEVICE bdf=" + admission.BDF + "\n"
                "GRASU_SHARDED_UPDATE_REPEAT_CONFIG repeats=1 restore_pma_between_repeats=1 restore_degree=1\n"
                + results.PREFIX + "_INPUT vertices=2552 static_edges=8192 logical_updates=16 physical_updates=16 "
                "final_edges=8208 damping=0.85 threshold_semantics=direct_per_vertex oracle_converged=1 "
                "epsilon=1e-6 pma_slots_total=10000\n" + results.PREFIX
                + f"_RESULT propagation_rounds={rounds} pipeline_executions={rounds+1} final_edges=8208 "
                "pma_slots_total=10000 processed_edge_slots_per_execution=10000\n")

    def test_wrong_threshold_and_wrong_board(self):
        results.validate_gr(self.CASE, self.gr(12), admission.BDF)
        for corrupted in (self.gr(12).replace("1e-6", "1e-7"),
                          self.gr(12).replace(admission.BDF, "other"),
                          self.gr(12).replace("pipeline_executions=13", "pipeline_executions=12"),
                          self.gr(12).replace("processed_edge_slots_per_execution=10000",
                                              "processed_edge_slots_per_execution=9999")):
            with self.assertRaises(ValueError):
                results.validate_gr(self.CASE, corrupted, admission.BDF)

    def test_zero_rounds_retained_but_flickr_not_admitted(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            rows = {arm: {field: {"path": str(root / f"{arm}.{field}")}
                          for field in ("stdout", "stderr")} for arm in ("gr", "spine")}
            Path(rows["gr"]["stdout"]["path"]).write_text(self.gr(0))
            Path(rows["spine"]["stderr"]["path"]).touch()
            Path(rows["spine"]["stdout"]["path"]).write_text(
                f"SPINE_DEVICE bdf={admission.BDF}\nSPINE_RESIDENT_BENCHMARK_PASS algorithm=2 "
                "case=/tmp/flickr.graph:final source=0 iterations=0 logical_updates=16 physical_updates=16 "
                "vertices=2552 wall_ms=1.0 host_correction_included=1 final_validation=outside_wall "
                "full_state_readback=each_round boundary=resident_update_to_final_readback_wall_including_host_relaunch\n")
            comparator = root / "comparator.py"
            comparator.write_text("import pathlib, sys\npathlib.Path(sys.argv[-1]).write_text("
                                  + repr(json.dumps({"gr_rounds": 0, "spine_rounds": 0})) + ")\n")
            pair = results.analyze(self.CASE, rows, comparator, root, admission.BDF)
            self.assertFalse(pair["meets_propagation_screen"])
            self.assertTrue(pair["equal_propagation_rounds"])

    def test_graph_dimensions_must_match_even_when_pin_matches(self):
        with TemporaryDirectory() as directory:
            graph = Path(directory) / "other.graph"
            graph.write_text("2552 8192 8\n")
            with self.assertRaises(ValueError):
                board.frozen_case("Flickr", graph, {"sha256": board.CASES["Flickr"][-1]})
