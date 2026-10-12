import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.analysis import MATRIX, parse_demo, summarize
from spine_cycle_sim.experiments.evaluation_impact.common_g.preparation import base, prepare, selected, source
from spine_cycle_sim.experiments.evaluation_impact.delivery import load_completed, source_reference
from spine_cycle_sim.experiments.evaluation_impact.r_execution import run_case, run_matrix


class DemoAdmissionTests(unittest.TestCase):
    def observation(self, arm="a4", cycles=2):
        return parse_demo("DEMO_ROUND " + json.dumps({"arm": arm, "round": 0, "cycles": cycles, "active": 0})
            + "\nDEMO_RESULT " + json.dumps({"arm": arm, "cycles": cycles, "rounds": 1,
                                            "read_bytes": 64, "write_bytes": 64, "passed": True}))

    def matrix(self):
        return [{"latency": latency, "reverse": reverse, "arm": arm,
                 "observations": self.observation(arm, 3 if arm == "cross_row" else 2),
                 "outputs": [{"name": "state", "sha256": "fixed", "bytes": 4}]}
                for latency, reverse, arm in MATRIX]

    def test_complete_diagnostic_not_baseline_admission(self):
        result = summarize(self.matrix())
        self.assertTrue(result["ten_percent_compute_target_met"])
        self.assertFalse(result["publication_match_admitted"])
        self.assertFalse(result["complete_spine_gr_comparison"])

    def test_missing_case_rejected(self):
        with self.assertRaises(ValueError):
            summarize(self.matrix()[:-1])

    def test_large_speedup_not_called_within_ten_percent(self):
        rows = self.matrix()
        for row in rows:
            row["observations"] = self.observation(row["arm"], 1 if row["arm"] == "candidate" else 2)
        self.assertFalse(summarize(rows)["ten_percent_compute_target_met"])

    def test_changed_order_state_rejected(self):
        rows = self.matrix()
        rows[3]["outputs"][0]["sha256"] = "changed"
        with self.assertRaises(ValueError):
            summarize(rows)

    def test_unclosed_cycles_rejected(self):
        text = 'DEMO_ROUND {"arm":"a4","round":0,"cycles":1,"active":0}\n'
        text += 'DEMO_RESULT {"arm":"a4","cycles":2,"rounds":1,"passed":true}'
        with self.assertRaises(ValueError):
            parse_demo(text)

    def test_nonconvergence_rejected(self):
        text = 'DEMO_ROUND {"arm":"a4","round":0,"cycles":1,"active":1}\n'
        text += 'DEMO_RESULT {"arm":"a4","cycles":1,"rounds":1,"passed":true}'
        with self.assertRaises(ValueError):
            parse_demo(text)

    def test_failed_execution_never_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = {"exit_code": 1, "timed_out": False}
            with patch("spine_cycle_sim.experiments.evaluation_impact.r_execution.run_bounded", return_value=failed):
                result = run_case(root, root, root / "unused", 0, 1, 1, (64, 0, "a4"))
            self.assertIn("error", result)
            self.assertNotIn("row", result)

    def test_parallel_launch_reserves_all_process_limits(self):
        with patch("spine_cycle_sim.experiments.evaluation_impact.r_execution.available_memory_bytes", return_value=39 * 1024**3):
            with self.assertRaisesRegex(RuntimeError, "insufficient memory"):
                run_matrix(None, None, None, [0, 1, 2, 3], 1, 1, None)


class CommonGFixtureTests(unittest.TestCase):
    def test_unique_encoded_keys_in_both_paths(self):
        for count, expected_cold in ((0, 0), (64, 32), (4096, 64)):
            segments = selected(count)
            self.assertEqual(len(set(segments)), count)
            self.assertEqual(sum(source(segment) for segment in segments), expected_cold)
            self.assertTrue(all((base(segment) + 1) >> 19 == 1 for segment in segments))
            self.assertTrue(all((base(segment) + 1) & ((1 << 19) - 1) < 524288 for segment in segments))

    def test_undeclared_case_rejected(self):
        with self.assertRaisesRegex(ValueError, "undeclared"):
            selected(65)

    def test_empty_input_is_control_not_update_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixture"
            prepare(root, 0)
            self.assertEqual(struct.unpack("<III", (root / "batches.bin").read_bytes()), (1, 0, 0))
            with self.assertRaises(FileExistsError):
                prepare(root, 0)


class DeliveryGateTests(unittest.TestCase):
    def test_running_report_cannot_be_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "running.json"
            path.write_text(json.dumps({"status": "RUNNING"}))
            with self.assertRaisesRegex(ValueError, "complete matched-G"):
                load_completed(path, path)

    def test_missing_build_flag_not_inferred_from_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build.log"
            path.write_text("a normal build line\n")
            with self.assertRaisesRegex(ValueError, "missing inspected"):
                source_reference(path, ("GRASU_COMPACT_HBM_PORTS",))

    def test_build_reference_retains_line_and_file_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "build.log"
            path.write_text("header\ncompile -DGRASU_COMPACT_HBM_PORTS\n")
            result = source_reference(path, ("GRASU_COMPACT_HBM_PORTS",))
            self.assertEqual(result["excerpts"][0]["line"], 2)
            self.assertEqual(len(result["sha256"]), 64)


class CommittedEvidenceTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1] / (
        "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/evidence")

    def test_capsule_preserves_full_reports_and_failed_attempt(self):
        index = json.loads((self.root / "index.json").read_text())
        self.assertEqual({row["file"] for row in index["reports"]},
                         {"matched_g.json", "r_convergence.json", "failed_attempt_v1.json"})
        for row in index["reports"]:
            path = self.root / row["file"]
            self.assertEqual(path.stat().st_size, row["bytes"])
            self.assertEqual(sha256_file(path), row["sha256"])
        failed = json.loads((self.root / "failed_attempt_v1.json").read_text())
        self.assertEqual(failed["status"], "FAILED_RETAINED")

    def test_capsule_does_not_promote_passing_r_to_baseline_admission(self):
        g, r = load_completed(self.root / "matched_g.json", self.root / "r_convergence.json")
        index = json.loads((self.root / "index.json").read_text())
        self.assertEqual(len(g["rows"]), 12)
        self.assertEqual(len(r["r_rows"]), 12)
        self.assertEqual(index["r"], r["r"])
        for row in r["r_rows"]:
            observation = row["observations"]
            records = ["DEMO_ROUND " + json.dumps(part) for part in observation["trajectory"]]
            records.append("DEMO_RESULT " + json.dumps(observation["result"]))
            self.assertEqual(parse_demo("\n".join(records)), observation)
            self.assertEqual(observation["result"]["rounds"], 46)
        comparisons = index["g_nonempty_comparisons"]
        self.assertEqual({(row["latency"], row["updates"]) for row in comparisons},
                         {(64, 64), (64, 4096), (128, 64), (128, 4096)})
        for row in comparisons:
            self.assertEqual(row["current_over_original"],
                             row["cycles"]["current"] / row["cycles"]["original"])
        self.assertFalse(index["g_ten_percent_prediction_target_met"])
        self.assertTrue(index["r"]["ten_percent_compute_target_met"])
        for gate in ("baseline_admitted", "publication_match_admitted", "new_spine_comparison_executed"):
            self.assertFalse(index[gate])


if __name__ == "__main__":
    unittest.main()
