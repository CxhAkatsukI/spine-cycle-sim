import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    cc_direct_matrix as direct, cc_resident_wall as wall,
)


class DirectCCMatrixTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.graph = self.root / "graph"
        self.graph.write_text("10 20 16\n")
        self.inputs = self.root / "inputs.json"
        self.split = dict(source=dict(path=str(self.graph)), vertices=10, edges=20, updates=16,
                          graph=dict(path="graph.slice"), update=dict(path="update.slice"))
        self.inputs.write_text(json.dumps(self.split))
        (self.root / "cc-wk.json").write_text(json.dumps(
            dict(dataset="WK", graph=str(self.graph), source=0)))

    def configure(self):
        return direct.configure(self.root, "WK", self.inputs, Path("host"), Path("image"), Path("gr-host"))

    def test_original_workload_and_balanced_single_sample_commands(self):
        case = self.configure()
        self.assertEqual((case["vertices"], case["edges"], case["updates"]), (10, 20, 16))
        commands = wall.commands(case, dict(image=dict(path="gr-image")), self.root)
        self.assertEqual(commands["spine"], [
            "host", "--xclbin", "image", "--hot", "balanced", "--mode", "partial", "--samples", "1",
            "--slice", "graph.slice", "--update", "update.slice"])
        self.assertEqual(commands["gr"][0:3], ["gr-host", "gr-image", str(self.graph)])
        self.assertEqual(commands["gr"][-2:], ["0", "256"])

    def test_mismatched_source_is_rejected(self):
        self.split["source"]["path"] = "different-graph"
        self.inputs.write_text(json.dumps(self.split))
        with self.assertRaisesRegex(ValueError, "original CC workload"):
            self.configure()

    def test_mismatched_dimensions_are_rejected(self):
        self.split["updates"] = 8
        self.inputs.write_text(json.dumps(self.split))
        with self.assertRaisesRegex(ValueError, "original CC workload"):
            self.configure()

    def test_wrong_dataset_is_rejected(self):
        (self.root / "cc-wk.json").write_text(json.dumps(dict(dataset="SU", graph=str(self.graph))))
        with self.assertRaisesRegex(ValueError, "original CC workload"):
            self.configure()

    @patch.object(direct, "run")
    def test_duplicate_dataset_does_not_launch(self, run):
        argv = ["direct", "--previous", "p", "--spine-host", "s", "--spine-image", "si",
                "--gr-host", "g", "--gr-image", "gi", "--output", "out",
                "--inputs", "WK", "i", "--inputs", "WK", "j"]
        with patch("sys.argv", argv), self.assertRaises(SystemExit):
            direct.main()
        run.assert_not_called()

    @patch.object(direct, "run")
    def test_long_startup_timeout_is_explicit_and_bounded(self, run):
        argv = ["direct", "--previous", "p", "--spine-host", "s", "--spine-image", "si",
                "--gr-host", "g", "--gr-image", "gi", "--output", "out", "--inputs", "LJ", "i"]
        with patch("sys.argv", argv):
            direct.main()
        self.assertEqual(run.call_args.args[0].arm_timeout_seconds, 1800)
        with patch("sys.argv", argv + ["--arm-timeout-seconds", "7200"]):
            direct.main()
        self.assertEqual(run.call_args.args[0].arm_timeout_seconds, 7200)
        for value in ("0", "7201"):
            run.reset_mock()
            with patch("sys.argv", argv + ["--arm-timeout-seconds", value]), self.assertRaises(SystemExit):
                direct.main()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
