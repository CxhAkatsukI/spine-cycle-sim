"""Do not request an FPGA for a failed, replaced or incomplete route."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import follow
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity, save


class SourceRetentionFollowTest(unittest.TestCase):
    def test_build_pins_without_size_still_require_matching_sha256(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.write_bytes(b"source")
            pin = identity(source)
            del pin["bytes"]
            follow.unchanged([pin])
            source.write_bytes(b"SOURCE")
            with self.assertRaises(ValueError):
                follow.unchanged([pin])
            with self.assertRaises(ValueError):
                follow.unchanged([{"path": str(source)}])

    def fixture(self, root):
        before, route, g, hosts, production, output = [root / name for name in
                                                     ("before.json", "route", "g.json", "hosts", "production", "output")]
        route.mkdir()
        hosts.mkdir()
        save(hosts / "manifest.json", {})
        save(g, {})
        save(route / "manifest.json", {"pins": []})
        inputs = {}
        for case in ("boundary_ring", "skewed_sources", "amazon"):
            path = root / "inputs" / case / "data.u32le"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"input")
            inputs[case] = [identity(path)]
        host = root / "host"
        host.write_bytes(b"host")
        rows = [{"case": case, "arm": arm, "repetitions": 1, "stdout": {}} for case in
                ("skewed_sources", "amazon") for arm in ("reference", "current")]
        save(before, {"status": "BOARD_EXECUTION_PASS_PENDING_ANALYSIS", "matrix": {"stages": ["R"]},
                      "rows": rows, "pins": {"r_current": identity(host)}, "input_pins": inputs,
                      "device": 1, "bdf": "0000:c1:00.1"})
        state = {"LoadState": "loaded", "ActiveState": "inactive", "SubState": "dead",
                 "InvocationID": "a" * 32, "Result": "success", "MainPID": "0", "ExecMainStatus": "0"}
        return (before, route, g, hosts, production, output), state

    def test_control_preserves_inputs_and_requires_one_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            args, _ = self.fixture(Path(temporary))
            plan, pins = follow.control(args[0], args[1], args[-1])
            self.assertEqual(plan.r_current, args[1] / "candidate.hw.xclbin")
            self.assertTrue(plan.r_single_run)
            follow.unchanged(pins)
            report = json.loads(args[0].read_text())
            report["rows"][0]["repetitions"] = 4
            save(args[0], report)
            with self.assertRaises(ValueError):
                follow.control(args[0], args[1], args[-1])

    def test_changed_invocation_and_failed_link_never_request_board(self):
        for wrong_invocation in (True, False):
            with self.subTest(wrong_invocation=wrong_invocation), tempfile.TemporaryDirectory() as temporary:
                args, state = self.fixture(Path(temporary))
                if wrong_invocation:
                    state["InvocationID"] = "b" * 32
                else:
                    path = args[1] / "execution/execution.json"
                    path.parent.mkdir()
                    save(path, {"status": "FAILED_RETAINED"})
                with patch.object(follow, "check_memory"), patch.object(follow, "runner_pins", return_value=[]), \
                        patch.object(follow, "service_state", return_value=state), patch.object(follow.study, "run") as board:
                    with self.assertRaises(ValueError):
                        follow.run(*args, unit="route.service", invocation="a" * 32)
                    board.assert_not_called()
                result = json.loads((args[-1] / "results.json").read_text())
                self.assertEqual(result["status"], "FAILED_RETAINED")
                self.assertFalse(result["board_requested"])

    def test_support_gate_requires_both_rows_and_clock_records(self):
        for passed in (True, False):
            with self.subTest(passed=passed), tempfile.TemporaryDirectory() as temporary:
                args, state = self.fixture(Path(temporary))
                binary = args[1] / "candidate.hw.xclbin"
                binary.write_bytes(b"bitstream")
                path = args[1] / "execution/execution.json"
                path.parent.mkdir()
                pin = identity(binary)
                del pin["bytes"]
                save(path, {"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD", "xclbin": pin})

                def analyze(g, r, output):
                    output.mkdir()
                    save(output / "summary.json", {"pairs": [
                        {"stage": "R", "at_most_15_percent_slower": True, "clock_evidence_recorded": True},
                        {"stage": "R", "at_most_15_percent_slower": True, "clock_evidence_recorded": passed}]})

                def package(*values):
                    values[-1].mkdir()
                    save(values[-1] / "manifest.json", {})

                with patch.object(follow, "check_memory"), patch.object(follow, "runner_pins", return_value=[]), \
                        patch.object(follow, "service_state", return_value=state), patch.object(follow.study, "run"), \
                        patch.object(follow.analysis, "analyze", side_effect=analyze), \
                        patch.object(follow.checkpoint, "checkpoint", side_effect=package):
                    result = follow.run(*args, unit="route.service", invocation="a" * 32)
                self.assertEqual(result["supported_r_gate_pass"], passed)
                self.assertFalse(result["full_evaluation_started"])


if __name__ == "__main__":
    unittest.main()
