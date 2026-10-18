"""Spine host contract tests use fabricated records, never a real board."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.spine_resident import analysis, preparation
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.spine_resident.__main__ import experiment, main
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.board_analysis import BOUNDARY
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import preparation as common


class SpineContractTests(unittest.TestCase):
    def row(self, algorithm="weighted_sssp"):
        return {"dataset": "AU", "algorithm": algorithm, "vertices": 5, "source": 0,
                "updates": 16 if algorithm == "connected_components" else 8,
                "graph": "/frozen/au.graph"}

    def log(self, row):
        return ("SPINE_DEVICE bdf=0000:01:00.1\n"
                "KERNEL_PAIR_RESULT algorithm=resident_benchmark iteration=0 overflow=0 task_error=0 "
                "source_status=0 owner_status=0 owner_created=3 owner_retired=1\n"
                f"SPINE_RESIDENT_BENCHMARK_PASS algorithm={common.ALGORITHMS.index(row['algorithm'])} "
                f"case={row['graph']}:final vertices=5 source=0 iterations=1 "
                f"logical_updates={row['updates']} physical_updates={row['updates']} boundary={BOUNDARY} "
                "wall_ms=12.5 final_validation=outside_wall full_state_readback=each_round "
                f"host_correction_included={int(row['algorithm'] == 'residual_pagerank')}\n")

    def test_three_algorithms_explicit_wall_and_counted_pr_host_work(self):
        for algorithm in common.ALGORITHMS:
            row = self.row(algorithm)
            report = analysis.analyze(row, self.log(row), "", bdf="0000:01:00.1")
            self.assertEqual(report["resident_wall_ms"], 12.5)
            self.assertEqual(report["boundary"], BOUNDARY)
            self.assertFalse(experiment().writes_result_file)
            argv = preparation.command({"binary": "host", "candidate": {"path": "fixed.xclbin"}}, row, None)
            self.assertIn("--resident-benchmark", argv)
            self.assertNotIn("--one-step", argv)

    def test_malformed_wrong_scope_or_failed_ledgers_rejected(self):
        row = self.row()
        log = self.log(row)
        for old, new in (("wall_ms=12.5", "wall_ms=nan"), ("iterations=1", "iterations=257"),
                         ("vertices=5", "vertices=6"), ("host_correction_included=0", "host_correction_included=1"),
                         ("outside_wall", "inside_wall"), ("task_error=0", "task_error=1"),
                         ("iteration=0", "iteration=1"), ("physical_updates=8", "physical_updates=9"),
                         ("0000:01:00.1", "0000:02:00.1"), (BOUNDARY, "legacy_sum")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                analysis.analyze(row, log.replace(old, new), "", bdf="0000:01:00.1")
        for altered, stderr in ((log + log, ""), (log, "driver warning"),
                                ("\n".join(line for line in log.splitlines() if not line.startswith("KERNEL_PAIR")), "")):
            with self.assertRaises(ValueError):
                analysis.analyze(row, altered, stderr, bdf="0000:01:00.1")

    def test_exact_xcl2_selection_notice_is_retained_not_a_driver_warning(self):
        row = self.row()
        log = self.log(row)
        for index in (0, 1):
            notice = f"Using XCL_DEVICE_INDEX={index}"
            report = analysis.analyze(row, log, notice + "\n", bdf="0000:01:00.1")
            self.assertEqual(report["runtime_notices"], [notice])
        for stderr in ("Using XCL_DEVICE_INDEX=2\n", "Using XCL_DEVICE_INDEX=1\nwarning\n",
                       "Using XCL_DEVICE_INDEX=1\nUsing XCL_DEVICE_INDEX=1\n", " \n"):
            with self.subTest(stderr=stderr), self.assertRaises(ValueError):
                analysis.analyze(row, log, stderr, bdf="0000:01:00.1")
        with self.assertRaisesRegex(ValueError, "leased board mismatch"):
            analysis.analyze(row, log, "Using XCL_DEVICE_INDEX=1\n", bdf="0000:02:00.1")

    def test_legacy_smoke_is_correctness_not_continuous_timing(self):
        row = {**self.row(), "legacy": True}
        log = ("SPINE_DEVICE bdf=0000:01:00.1\nPARTITIONED_ALGORITHM_PASS algorithm=weighted_sssp "
               "vertices=5 source=0 case=/frozen/au.graph:final dynamic_run=1 resident_update=1 "
               "logical_updates=8 physical_updates=8 coverage=converged\n")
        result = analysis.analyze(row, log, "", bdf="0000:01:00.1")
        self.assertNotIn("resident_wall_ms", result)
        self.assertNotIn("--resident-benchmark", preparation.command(
            {"binary": "host", "candidate": {"path": "fixed.xclbin"}}, row, None))
        with self.assertRaises(ValueError):
            analysis.analyze(row, log.replace("converged", "one_step"), "", bdf="0000:01:00.1")

    def test_no_active_propagation_still_requires_validated_final_readback(self):
        row = self.row("residual_pagerank")
        log = "\n".join(line.replace("iterations=1", "iterations=0") for line in self.log(row).splitlines()
                        if not line.startswith("KERNEL_PAIR_RESULT "))
        result = analysis.analyze(row, log, "", bdf="0000:01:00.1")
        self.assertEqual(result["iterations"], 0)
        self.assertEqual(result["resident_wall_ms"], 12.5)

    def test_old_or_dirty_compile_is_not_admitted_and_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build = root / "build"
            build.mkdir()
            (build / "source-commit.txt").write_text("old")
            with patch.object(preparation.subprocess, "check_output", side_effect=["new\n", b""]):
                with self.assertRaisesRegex(ValueError, "same clean committed revision"):
                    preparation.freeze(root, build, root, root / "attempt")
            with patch.object(preparation.subprocess, "check_output", side_effect=["new\n", b"dirty"]):
                with self.assertRaisesRegex(ValueError, "committed"):
                    preparation.freeze(root, build, root, root / "dirty-attempt")
            with self.assertRaises(FileExistsError):
                preparation.freeze(root, build, root, root / "attempt")

    def test_complete_plan_reuses_all_eight_graphs_and_separate_legacy_smoke(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            preflight = root / "offline"
            preflight.mkdir()
            rows = [{**self.row(), "dataset": dataset} for dataset in common.DATASETS]
            (preflight / "results.json").write_text(json.dumps({
                "status": preparation.offline_analysis.PASS, "matrix": rows, "pins": []}))
            pin = root / "input"
            pin.write_text("fixed")
            admission = root / "admission.json"
            admission.write_text(json.dumps({"status": preparation.FROZEN,
                "board_programmed": False, "stage_calibration": False, "host_revision": "frozen",
                "plans": {"weighted_sssp": {"binary": "host", "candidate": {"path": "fixed.xclbin"}}},
                "pins": [common.identity(pin)]}))
            smoke = {**rows[0], "dataset": "SMOKE"}
            with patch.object(preparation.recheck, "recheck") as recheck, \
                    patch.object(preparation.recheck, "smoke_rows", return_value=[smoke]):
                result = preparation.prepare(preflight, admission, "weighted_sssp")
                recheck.assert_called_once()
                self.assertEqual(result["rows"], rows)
                self.assertEqual([row["dataset"] for row in result["smokes"]], ["SMOKE_LEGACY", "SMOKE"])
                self.assertTrue(result["smokes"][0]["legacy"])
                pin.write_text("drifted")
                with self.assertRaisesRegex(ValueError, "changed"):
                    preparation.prepare(preflight, admission, "weighted_sssp")

    def test_cli_does_not_promote_memory_failure_to_success_exit(self):
        argv = ["run", "--preflight", "/offline", "--admission", "/freeze.json",
                "--algorithm", "weighted_sssp", "--output", "/unused"]
        owner = "spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.spine_resident.__main__.board_study.run"
        for status, expected in (("FAILED_RETAINED", 1), (analysis.PASS, 0), ("BOARD_PREPARED_NOT_EXECUTED", 0)):
            with patch(owner, return_value={"status": status}):
                self.assertEqual(main(argv), expected)


if __name__ == "__main__":
    unittest.main()
