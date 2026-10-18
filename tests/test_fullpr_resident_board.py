"""FullPR protocol tests fabricate records and do not program an FPGA."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import preparation as common
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.board_analysis import BOUNDARY
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.fullpr_resident import inputs, spine
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.fullpr_resident.__main__ import main


class FullPRContractTests(unittest.TestCase):
    def row(self):
        return {"dataset": "SMOKE", "algorithm": "full_pagerank", "vertices": 4,
                "initial_edges": 3, "updates": 1, "source": 0, "graph": "/frozen/dangling.graph"}

    def log(self):
        ledgers = "\n".join(f"KERNEL_PAIR_RESULT algorithm=fullpr_resident iteration={i} "
            "overflow=0 task_error=0 source_status=0 owner_status=0" for i in range(4))
        return ("SPINE_DEVICE bdf=0000:c1:00.1\n" + ledgers + "\n"
                "SPINE_RESIDENT_BENCHMARK_PASS algorithm=3 case=/frozen/dangling.graph:final "
                "vertices=4 source=0 iterations=4 logical_updates=1 physical_updates=1 "
                f"boundary={BOUNDARY} wall_ms=20 final_validation=outside_wall "
                "full_state_readback=each_round host_correction_included=0 warm_sweeps=128 "
                "warm_residual_checked=1 convergence=global_l1 epsilon=1e-6 final_l1_error=9e-7 "
                "degree_preparation=host_inside_wall\n")

    def test_convergence_not_fixed_rounds_and_explicit_host_degree_cost(self):
        report = spine.analyze(self.row(), self.log(), "Using XCL_DEVICE_INDEX=1\n", bdf="0000:c1:00.1")
        self.assertEqual(report["resident_wall_ms"], 20)
        self.assertEqual(report["iterations"], 4)
        self.assertEqual(report["last_iteration_l1_delta"], 9e-7)
        self.assertFalse(spine.experiment().writes_result_file)
        command = spine.experiment().command({"binary": "host", "candidate": {"path": "fixed.xclbin"}},
                                              self.row(), None)
        self.assertIn("--resident-benchmark", command)
        self.assertNotIn("--one-step", command)

    def test_boundary_state_or_ledger_failures_are_not_admitted(self):
        for old, new in (("iterations=4", "iterations=3"), ("iterations=4", "iterations=257"),
                         ("final_l1_error=9e-7", "final_l1_error=nan"),
                         ("final_l1_error=9e-7", "final_l1_error=1.1e-6"),
                         ("final_l1_error=9e-7", "final_l1_error=-1"),
                         ("wall_ms=20", "wall_ms=inf"), ("wall_ms=20", "wall_ms=0"),
                         ("host_inside_wall", "outside_wall"), ("global_l1", "fixed_rounds"),
                         ("epsilon=1e-6", "epsilon=1e-5"), ("warm_residual_checked=1", "warm_residual_checked=0"),
                         ("warm_sweeps=128", "warm_sweeps=3"), ("algorithm=3", "algorithm=2"),
                         ("physical_updates=1", "physical_updates=2"), ("task_error=0", "task_error=1"),
                         ("fullpr_resident", "resident_benchmark"), ("each_round", "one_step"),
                         ("0000:c1:00.1", "0000:41:00.1")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                spine.analyze(self.row(), self.log().replace(old, new), "", bdf="0000:c1:00.1")
        for log, stderr in ((self.log() + self.log(), ""), (self.log(), "driver warning\n"),
                            (self.log().replace("KERNEL_PAIR_RESULT algorithm=fullpr_resident iteration=3",
                                                "IGNORED algorithm=fullpr_resident iteration=3"), "")):
            with self.assertRaises(ValueError):
                spine.analyze(self.row(), log, stderr, bdf="0000:c1:00.1")

    def test_freeze_cohort_requires_all_three_and_preserves_old_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text("frozen source")
            graph = root / "input.graph"
            graph.write_text("4 3 1\n0 1 1\n1 2 1\n2 0 1\n0 2 1 1\n")
            rows = [{**self.row(), "dataset": dataset, "graph": str(graph),
                     "algorithm": "weighted_sssp", "input_identity": common.identity(graph)}
                    for dataset in inputs.DATASETS]
            with patch.object(common, "matrix", return_value=rows):
                result = inputs.freeze(manifest, root / "cohort")
            self.assertEqual(result["status"], inputs.FROZEN)
            self.assertEqual([row["dataset"] for row in result["rows"]], ["AU", "SU", "WK"])
            self.assertEqual(result["semantics"]["vertex_id_transform"], "none")
            self.assertEqual(inputs.load(root / "cohort")[0], result)
            with self.assertRaises(FileExistsError):
                inputs.freeze(manifest, root / "cohort")
            graph.write_text("drifted")
            with self.assertRaisesRegex(ValueError, "changed"):
                inputs.load(root / "cohort")
            with patch.object(common, "matrix", return_value=rows[:2]):
                with self.assertRaisesRegex(ValueError, "AU/SU/WK"):
                    inputs.freeze(manifest, root / "missing-cohort")

    def test_incompatible_freeze_or_algorithm_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "admission.json"
            path.write_text(json.dumps({"status": "OLD_FIXED_THREE_ROUNDS"}))
            with patch.object(inputs, "load", return_value=({}, [])):
                with self.assertRaisesRegex(ValueError, "isolated FullPR"):
                    spine.prepare(Path(directory), path, "full_pagerank")
            with self.assertRaisesRegex(ValueError, "FullPR-only"):
                spine.prepare(Path(directory), path, "residual_pagerank")

    def test_cli_cannot_promote_failed_matrix(self):
        argv = ["run-spine", "--preflight", "/cohort", "--admission", "/freeze.json", "--output", "/unused"]
        owner = "spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.fullpr_resident.__main__.board_study.run"
        for status, expected in (("FAILED_RETAINED", 1), (spine.PASS, 0), ("BOARD_PREPARED_NOT_EXECUTED", 0)):
            with patch(owner, return_value={"status": status}) as run:
                self.assertEqual(main(argv), expected)
                self.assertEqual(run.call_args.args[2], "full_pagerank")

    def test_cpu_cli_forwards_explicit_budget_without_altering_cohort(self):
        owner = "spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.fullpr_resident.__main__"
        argv = ["prepare-gr", "--source", "/source", "--cohort", "/cohort", "--xrt", "/xrt",
                "--hls", "/hls", "--output", "/output", "--memory-gib", "4"]
        with patch(owner + ".gr_preparation.protocol", return_value="mock protocol"), \
                patch(owner + ".study.run", return_value={"status": "FAILED_RETAINED"}) as run:
            self.assertEqual(main(argv), 1)
            self.assertEqual(run.call_args.kwargs["memory_gib"], 4)
            self.assertEqual(run.call_args.args, tuple(map(Path, ("/source", "/cohort", "/output", "/xrt", "/hls"))))


if __name__ == "__main__":
    unittest.main()
