import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import comparison, delivery
import test_original_regraph_board_delivery as fixtures


class BoardComparisonTests(unittest.TestCase):
    def fixture(self, root, topology):
        root.mkdir()
        attempt, supervisor, board = fixtures.BoardDeliveryTests().fixture(root, topology)
        plan = json.loads((attempt / "manifest.json").read_text())
        pins = []
        for case in plan["cases"]:
            for name in comparison.INPUTS:
                path = Path(case["input"]) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
                pins.append(artifact.identity(path))
        plan["host"] = {"path": "/frozen/host", "sha256": "a" * 64}
        board["pins"] = pins
        board["runtime"].update(platform={"static_region": {"vbnv": "u55c"}}, pins=[
            {"path": "/lib/libxrt.so", "sha256": "b" * 64},
            {"path": str(root / "spine_cycle_sim/runner.py"), "sha256": "c" * 64}])
        for item in board["attempts"]:
            item["command"] = ["/usr/bin/taskset", "-c", "124,125", "/frozen/host"]
        atomic_write_json(attempt / "manifest.json", plan)
        atomic_write_json(attempt / "board/results.json", board)
        supervisor["child"] = artifact.identity(attempt / "board/results.json")
        atomic_write_json(attempt / "results.json", supervisor)
        return attempt

    def controls(self, root):
        paths = [self.fixture(root / name, name) for name in ("original_example", "a4")]
        with patch.object(delivery.gates, "inspect_routed", return_value={"clock": [("DATA", "DATA_CLK", 150)]}):
            controls = [comparison.load(path, name) for path, name in zip(paths, ("original_example", "a4"))]
        return paths, controls

    def test_replays_complete_controls_without_claiming_k4_or_publication_match(self):
        with tempfile.TemporaryDirectory() as directory:
            _, controls = self.controls(Path(directory))
            result = comparison.compare(*controls)
            self.assertEqual(len(result["rows"]), 6)
            self.assertTrue(result["hardware_timing_measured"])
            self.assertTrue(result["raw_outputs_independently_replayed"])
            self.assertTrue(all(result[name] is False for name in comparison.CLAIMS))
            self.assertEqual(result["latest_adapter_k4"]["status"], "NOT_INCLUDED_NO_MATCHED_BOARD_RESULT")
            text = comparison.markdown(result)
            self.assertIn("not interchangeable", text)
            self.assertIn("nine-bank", text)

    def test_ratios_keep_wall_span_and_union_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            _, controls = self.controls(Path(directory))
            factors = dict(zip(comparison.METRICS, (.5, 1.2, 1.1)))
            for metric, factor in factors.items():
                controls[1]["board"]["summaries"][0][metric]["median"] *= factor
            result = comparison.compare(*controls)
            for metric, factor in factors.items():
                self.assertAlmostEqual(result["rows"][0]["a4_over_original_ratio_of_medians"][metric], factor)

    def test_mismatched_inputs_runtime_host_affinity_or_logical_output_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, controls = self.controls(Path(directory))
            for field in ("runtime", "cases", "host", "affinity"):
                changed = copy.deepcopy(controls)
                changed[1][field] = None
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, "matched " + field):
                    comparison.compare(*changed)
            changed = copy.deepcopy(controls)
            changed[1]["board"]["rows"][0]["analysis"]["independent_oracle"]["logical_sha256"] = "f" * 64
            with self.assertRaisesRegex(ValueError, "logical fixed-point"):
                comparison.compare(*changed)

    def test_missing_cases_and_repeats_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            _, controls = self.controls(Path(directory))
            for missing in (True, False):
                changed = copy.deepcopy(controls)
                if missing:
                    changed[1]["board"]["summaries"].pop()
                else:
                    changed[1]["board"]["summaries"][0]["repeats"] = 2
                with self.subTest(missing=missing), self.assertRaises(ValueError):
                    comparison.compare(*changed)

    def test_load_rejects_wrong_topology_unpinned_inputs_affinity_and_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, controls = self.controls(Path(directory))
            supervisor, board = controls[0]["reports"], controls[0]["board"]
            supervisor = json.loads(Path(supervisor[0]["path"]).read_text())
            for change in ("topology", "pins", "affinity", "clock"):
                changed = copy.deepcopy(board)
                topology = "original_example"
                if change == "topology":
                    topology = "a4"
                elif change == "pins":
                    changed["pins"] = []
                elif change == "affinity":
                    changed["attempts"][0]["command"][2] = "1"
                else:
                    changed["rows"][0]["analysis"]["clock_mhz"] = 151
                with self.subTest(change=change), patch.object(delivery, "recheck", return_value=(supervisor, changed)):
                    with self.assertRaises(ValueError):
                        comparison.load(paths[0], topology)

    def test_run_writes_fresh_report_and_checks_frozen_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            paths, controls = self.controls(Path(directory))
            output = Path(directory) / "comparison"
            with patch.object(comparison, "load", side_effect=controls):
                result = comparison.run(*paths, output)
            self.assertEqual(json.loads((output / "results.json").read_text()), result)
            self.assertIn("Span ratio", (output / "README.md").read_text())
            with patch.object(comparison, "load", side_effect=controls):
                with self.assertRaises(FileExistsError):
                    comparison.run(*paths, output)
            (paths[0] / "results.json").write_text("changed")
            with patch.object(comparison, "load", side_effect=controls):
                with self.assertRaises(ValueError):
                    comparison.run(*paths, Path(directory) / "changed")


if __name__ == "__main__":
    unittest.main()
