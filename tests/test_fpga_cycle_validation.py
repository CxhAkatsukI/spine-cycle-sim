"""Fast checks of workload, timing boundary and independent validation roles."""

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.fpga_cycles import inputs, analysis, calibration


class FpgaCycleValidationTests(unittest.TestCase):
    def test_predeclared_inputs_match_native_and_simulator(self):
        with tempfile.TemporaryDirectory() as root:
            plan = inputs.prepare(Path(root) / "inputs")
            self.assertEqual(sum(row["split"] == "development" for row in plan["cases"]), 2)
            self.assertEqual(sum(row["split"] == "holdout" for row in plan["cases"]), 4)
            for row in plan["cases"]:
                board = Path(row["graph"]).read_text().splitlines()
                v, e, u = map(int, board[0].split())
                self.assertEqual((v, e, u), (row["vertices"], row["initial_edges"], 1))
                edges = [tuple(map(int, line.split())) for line in board[1:-1]]
                self.assertEqual(edges, sorted(edges))
                self.assertEqual(len(edges), len(set(edges)))
                self.assertNotIn((0, 1, 1), edges)
                sim = [tuple(map(int, line.split())) for line in Path(row["initial"]).read_text().splitlines()
                       if not line.startswith("#")]
                self.assertEqual(sim, [(*edge, 1) for edge in edges])
                self.assertTrue(all(0 <= s < v and 0 <= d < v for s, d, _ in edges))

    def test_event_window_uses_union_not_sum_and_excludes_round_gaps(self):
        result = dict(maintenance_start_cycle=2, maintenance_end_cycle=12,
                      reader_start_cycles_per_round=[20, 100], compute_start_cycles_per_round=[25, 105],
                      reader_end_cycles_per_round=[40, 120], compute_end_cycles_per_round=[50, 130])
        self.assertEqual(analysis.simulation_window(result), 70)
        result["compute_end_cycles_per_round"].pop()
        with self.assertRaises(ValueError):
            analysis.simulation_window(result)

    def test_equal_rounds_but_different_work_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "board.txt"
            path.write_text("KERNEL_PAIR_RESULT algorithm=weighted SSSP processed_edges=8 source_requests=2 task_count=3\n")
            hw = {"stdout": {"path": str(path)}, "timing": {"iterations": "1"}}
            sim = dict(rounds=1, converged=True, processed_edges_per_round=[8],
                       reader_source_requests_per_round=[2], reader_range_tasks_per_round=[3])
            analysis.validate_work(hw, sim)
            sim["processed_edges_per_round"] = [7]
            with self.assertRaisesRegex(ValueError, "processed_edges"):
                analysis.validate_work(hw, sim)

    def test_failed_holdout_is_retained_in_summary(self):
        with tempfile.TemporaryDirectory() as root:
            rows = [dict(split="holdout", within_20=False, abs_error_percent=25)]
            analysis.write(rows, Path(root))
            report = json.loads((Path(root) / "summary.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertEqual(report["all_rows"], rows)

    def test_archive_relocation_preserves_source_path(self):
        self.assertEqual(analysis.resolve("/original/run/case.json", ("/original", "/archive")),
                         Path("/archive/run/case.json"))
        self.assertEqual(analysis.resolve("/outside/file", ("/original", "/archive")),
                         Path("/outside/file"))

    def test_holdout_cannot_be_used_for_calibration(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            board = root / "board.json"
            sim = root / "sim.json"
            board.write_text(json.dumps(dict(status="COMPLETE", rows=[
                dict(name="test", split="holdout", status="MEASURED")])))
            sim.write_text(json.dumps(dict(status="COMPLETE", rows=[])))
            with self.assertRaisesRegex(ValueError, "development"):
                calibration.freeze(board, sim, root / "absent.json", root / "out")
