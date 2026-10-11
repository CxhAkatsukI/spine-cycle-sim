import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.route_recovery import RECOVERED, recover_route


class RouteRecoveryTests(unittest.TestCase):
    def fixture(self, root):
        binary = root / "candidate.hw.xclbin"
        binary.write_bytes(b"test artifact")
        source = root / "input.xo"
        source.write_bytes(b"frozen input")
        (root / "manifest.json").write_text(json.dumps({"pins": [identity(source)], "timeout_seconds": 14400}))
        (root / "route.progress.json").write_text(json.dumps({"pid": 10, "stop_reason": "process_exit"}))
        (root / "route.stdout.txt").write_text(
            f"INFO: Created {binary}\nINFO: [v++ 60-1307] Run completed.\n"
            "INFO: Total elapsed time: 4h 22m 55s\n")
        (root / "route.stderr.txt").write_text("")
        (root / "logs/link").mkdir(parents=True)
        (root / "logs/link/link.steps.log").write_text(
            "vpl status: success\nrtdgen status: success\nxclbinutil status: success\n"
            "xclbinutilinfo status: success\nhw completed\nsystem estimate report task completed\n")

    @patch("spine_cycle_sim.experiments.sharded_k4_stages.route_recovery.subprocess.check_output",
           return_value="20 1 20 100\n")
    def test_completed_artifact_does_not_invent_resource_or_exit_success(self, _):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = recover_route(root)
            self.assertEqual(result["status"], RECOVERED)
            self.assertIsNone(result["resources"])
            self.assertIsNone(result["recovery"]["process_exit_code"])
            self.assertFalse(result["recovery"]["continuous_resource_monitoring_verified"])
            self.assertTrue(result["recovery"]["vendor_duration_exceeded_configured_timeout"])
            with self.assertRaises(FileExistsError):
                recover_route(root)

    def test_live_workers_changed_input_incomplete_and_failed_logs_rejected(self):
        for failure in ("live", "input", "incomplete", "error", "timeout", "resources"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                processes = "11 1 10 100\n" if failure == "live" else "20 1 20 100\n"
                if failure == "input":
                    (root / "input.xo").write_bytes(b"changed")
                elif failure == "incomplete":
                    (root / "logs/link/link.steps.log").write_text("vpl status: success\n")
                elif failure == "error":
                    (root / "route.stderr.txt").write_text("ERROR: failed\n")
                elif failure == "timeout":
                    (root / "route.progress.json").write_text(json.dumps({"pid": 10, "stop_reason": "timeout"}))
                elif failure == "resources":
                    (root / "route.resources.json").write_text("{}")
                with patch("spine_cycle_sim.experiments.sharded_k4_stages.route_recovery.subprocess.check_output",
                           return_value=processes):
                    with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
                        recover_route(root)
                self.assertFalse((root / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
