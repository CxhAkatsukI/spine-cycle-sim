"""Synthetic paired-matrix replay tests; these never operate FPGA hardware."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import board_protocol, preparation
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.paired_board import analysis, study
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.spine_resident.__main__ import experiment as spine_experiment
from test_fullgraph_board_analysis import BDF, fixture
import test_spine_resident_board as spine_fixtures


def matrix(algorithm, spine=False, output=Path("/frozen/attempt")):
    experiment = spine_experiment() if spine else board_protocol.gr_experiment()
    vertices = 327681
    updates = 16 if algorithm == "connected_components" else 8
    rows = [{"dataset": d, "algorithm": algorithm, "vertices": vertices, "initial_edges": 3,
             "updates": updates, "source": 0, "graph": "/frozen/" + d + ".graph", "sha256": d,
             "input_identity": {"path": "/frozen/" + d + ".graph", "sha256": d}}
            for d in preparation.DATASETS]
    smoke = {**rows[0], "dataset": "SMOKE"}
    plan = {"algorithm": algorithm, "binary": "/frozen/host", "candidate": {"path": "/frozen/fixed.xclbin"},
            "rows": rows, "smoke": smoke, "pins": []}
    topology = {"clock": [["DATA", "DATA_CLK", 150]]}
    plan.update({"topology": topology} if spine else {"artifact_admission": {"topology": topology}})
    report = {"status": experiment.pass_status, "errors": [], "experiment": experiment.name,
              "algorithm": algorithm, "boundary": analysis.BOUNDARY, "plan": plan, "pins": [],
              "repeats": 3, "cpu_affinity": [118, 119], "device_index": 1,
              "execution_requested": True, "board_requested": True, "hardware_convergence_measured": True,
              **{key: False for key in analysis.CLAIMS}, "attempts": [],
              "containment": {"limits": {"memory.max": str(24 * 1024**3),
                              "memory.high": str(22 * 1024**3), "memory.swap.max": "0", "memory.oom.group": "1"}},
              "memory_events_after": "max 0\noom 0\noom_kill 0\noom_group_kill 0\n",
              "runtime": {"device": {"bdf": BDF, "driver_version": "fixed", "driver_srcversion": "fixed",
                                      "kernel_release": "fixed"},
                          "platform": {"static_region": {"vbnv": "u55c"}, "status": {"mig_calibrated": "true"}},
                          "pins": [{"path": "/frozen/libxrt_core.so", "sha256": "fixed"}]},
              "environment": experiment.environment(1, BDF)}
    raw = {}
    for scope, row, repeat in [("smoke", smoke, 0)] + [
            ("matrix", row, repeat) for repeat in range(3) for row in rows]:
        if spine:
            log = spine_fixtures.SpineContractTests().log(row).replace("vertices=5", f"vertices={vertices}")
            stderr = "Using XCL_DEVICE_INDEX=1\n"
        else:
            _, log = fixture(algorithm)
            log = log.replace("logical_updates=1", f"logical_updates={updates}").replace(
                "physical_updates=1", f"physical_updates={updates}")
            stderr = ""
        name = f"{scope}_r{repeat}_{row['dataset']}"
        resource = {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None,
                    "host_affinity": [118, 119], "tree_memory_gib": 24, "reserve_gib": 32,
                    "timeout_seconds": 600 if scope == "smoke" else 1800,
                    "command": experiment.command(plan, row, output / (name + ".result.txt")), "cwd": str(output)}
        attempt = {"scope": scope, "dataset": row["dataset"], "repeat": repeat, "status": "PASS",
                   "resources": resource, "analysis": experiment.analyze(row, log, stderr, bdf=BDF)}
        if experiment.writes_result_file:
            attempt["result_identity"] = {"path": str(output / (name + ".result.txt")), "sha256": "fixed"}
        report["attempts"].append(attempt)
        raw["raw/" + name + ".resources.json"] = json.dumps(resource)
        raw["raw/" + name + ".stdout.txt"] = log
        raw["raw/" + name + ".stderr.txt"] = stderr
    return report, raw, experiment


class PairedBoardTests(unittest.TestCase):
    def test_all_six_complete_raw_matrices_replayed_and_aggregated(self):
        arms = []
        for spine in (False, True):
            arm = []
            for algorithm in preparation.ALGORITHMS:
                report, raw, experiment = matrix(algorithm, spine)
                analysis.replay(report, report["plan"], experiment, Path("/frozen/attempt"), raw.__getitem__)
                arm.append(report)
            arms.append(arm)
        result = analysis.aggregate(*arms)
        self.assertEqual(result["status"], analysis.PASS)
        self.assertEqual(len(result["rows"]), 24)
        self.assertAlmostEqual(result["rows"][0]["speedup_gr_over_spine"], .004 / 12.5)
        for key in ("final_figures_admitted", "production_baseline_admitted", "stage_calibration", "service_exit_attested"):
            self.assertIs(result[key], False)

    def test_raw_log_and_stored_analysis_must_agree(self):
        report, raw, experiment = matrix("weighted_sssp")
        raw["raw/matrix_r0_AU.stdout.txt"] = raw["raw/matrix_r0_AU.stdout.txt"].replace(
            "setup_inclusive_ms=0.004", "setup_inclusive_ms=0.005")
        with self.assertRaisesRegex(ValueError, "raw board output"):
            analysis.replay(report, report["plan"], experiment, Path("/frozen/attempt"), raw.__getitem__)

    def test_incomplete_or_failed_execution_changed_scope_and_promoted_claim_rejected(self):
        report, raw, experiment = matrix("weighted_sssp", True)
        changes = [lambda r: r.update(status="RUNNING_matrix_r2_R19"),
                   lambda r: r["attempts"].pop(),
                   lambda r: r["attempts"].reverse(),
                   lambda r: r.update(publication_match=True),
                   lambda r: r.update(memory_events_after=r["memory_events_after"].replace("max 0", "max 1")),
                   lambda r: r.update(boundary="device_only"),
                   lambda r: r["environment"].update(SPINE_EXPECT_BDF="wrong"),
                   lambda r: r["plan"].update(binary="/changed/host"),
                   lambda r: r["containment"]["limits"].update({"memory.swap.max": "1"}),
                   lambda r: r["attempts"][1]["resources"].update(command=["host", "--one-hop"])]
        for change in changes:
            altered = deepcopy(report)
            change(altered)
            with self.subTest(change=change), self.assertRaises(ValueError):
                analysis.replay(altered, report["plan"], experiment, Path("/frozen/attempt"), raw.__getitem__)

    def test_matching_resources_file_cannot_hide_a_changed_command(self):
        report, raw, experiment = matrix("weighted_sssp")
        resource = report["attempts"][1]["resources"]
        resource["command"].append("--cold-start")
        raw["raw/matrix_r0_AU.resources.json"] = json.dumps(resource)
        with self.assertRaisesRegex(ValueError, "command differs"):
            analysis.replay(report, report["plan"], experiment, Path("/frozen/attempt"), raw.__getitem__)

    def test_mismatched_inputs_clock_runtime_affinity_or_repeats_rejected(self):
        gr = [matrix(a)[0] for a in preparation.ALGORITHMS]
        spine = [matrix(a, True)[0] for a in preparation.ALGORITHMS]
        changes = [lambda r: r["plan"]["rows"][0].update(source=1),
                   lambda r: r["plan"]["rows"][0].update(sha256="different"),
                   lambda r: r["plan"]["rows"][0]["input_identity"].update(sha256="different"),
                   lambda r: r["plan"]["topology"].update(clock=[["DATA", "DATA_CLK", 200]]),
                   lambda r: r["runtime"]["device"].update(driver_version="changed"),
                   lambda r: r.update(cpu_affinity=[116, 117]),
                   lambda r: r.update(repeats=4),
                   lambda r: r["attempts"].pop(),
                   lambda r: r["attempts"][1]["analysis"].update(resident_wall_ms=float("nan"))]
        for change in changes:
            altered = deepcopy(spine)
            change(altered[0])
            with self.subTest(change=change), self.assertRaises(ValueError):
                analysis.aggregate(gr, altered)

    def test_median_ratio_not_average_of_pairwise_ratios(self):
        gr = [matrix(a)[0] for a in preparation.ALGORITHMS]
        spine = [matrix(a, True)[0] for a in preparation.ALGORITHMS]
        for arm, times in ((gr, [1., 2., 100.]), (spine, [10., 1., 2.])):
            for report in arm:
                for attempt in report["attempts"]:
                    if attempt["scope"] == "matrix":
                        attempt["analysis"]["resident_wall_ms"] = times[attempt["repeat"]]
        row = analysis.aggregate(gr, spine)["rows"][0]
        self.assertEqual(row["gr_wall_ms"], [1., 2., 100.])
        self.assertEqual(row["speedup_gr_over_spine"], 1.)

    def test_reports_and_raw_files_are_hash_pinned_before_and_after_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            report, raw, experiment = matrix("weighted_sssp", True, output)
            report_path = output / "results.json"
            report_path.write_text(json.dumps(report))
            for name, data in raw.items():
                path = output / name
                path.parent.mkdir(exist_ok=True)
                path.write_text(data)
            with patch(
                    "spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.spine_resident.preparation.prepare",
                    return_value=report["plan"]):
                checked, pins = study.read_arm(output, {"report": str(report_path), "admission": "/fixed/freeze"},
                                              "weighted_sssp", spine_experiment())
            self.assertEqual(checked, report)
            preparation.unchanged(pins, full=True)
            (output / "raw/matrix_r0_AU.stdout.txt").write_text("changed")
            with self.assertRaises(ValueError):
                preparation.unchanged(pins, full=True)

    def test_saved_plan_cannot_omit_a_revalidated_source_pin(self):
        report, raw, experiment = matrix("weighted_sssp")
        expected = deepcopy(report["plan"])
        expected["pins"] = [{"path": "/source/host.cpp", "sha256": "required"}]
        with self.assertRaisesRegex(ValueError, "pin closure"):
            analysis.replay(report, expected, experiment, Path("/frozen/attempt"), raw.__getitem__)

    def test_complete_study_writes_all_rows_but_does_not_admit_final_figures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requests = [{"algorithm": a,
                         "gr": {"report": f"/gr/{a}/results.json", "admission": "/gr/admission.json"},
                         "spine": {"report": f"/spine/{a}/results.json", "admission": "/spine/freeze.json"}}
                        for a in preparation.ALGORITHMS]
            path = root / "requests.json"
            path.write_text(json.dumps(requests))
            reports = []
            for algorithm in preparation.ALGORITHMS:
                reports += [(matrix(algorithm)[0], []), (matrix(algorithm, True)[0], [])]
            with patch.object(study, "read_arm", side_effect=reports):
                result = study.run(root, path, root / "output")
            self.assertEqual(result["status"], analysis.PASS)
            self.assertFalse(result["final_figures_admitted"])
            self.assertEqual(len((root / "output/paired_wall.csv").read_text().splitlines()), 25)

    def test_bad_request_and_incomplete_report_retain_failure_without_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = root / "requests.json"
            request.write_text("[]")
            output = root / "attempt"
            with self.assertRaises(ValueError):
                study.run(root, request, output)
            result = json.loads((output / "results.json").read_text())
            self.assertEqual(result["status"], "FAILED_RETAINED")
            self.assertFalse((output / "paired_wall.csv").exists())
            with self.assertRaises(FileExistsError):
                study.run(root, request, output)


if __name__ == "__main__":
    unittest.main()
