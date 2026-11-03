import argparse
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import (
    active_min_candidate as candidate,
    active_min_follow as follow,
    active_min_pair as pair,
)


class ActiveMinCandidateTests(unittest.TestCase):
    def test_replays_candidate_publication_and_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "execution.u32le").write_bytes(
                struct.pack("<16I", 0x3447524F, 1, 2, 1, 65536, 65536, 1, 1, *([0] * 8)))
            words = struct.pack("<2I", 0, 0x80000000) + bytes(4 * (65536 - 2))
            reference = root / "reference.u32le"
            reference.write_bytes(words + struct.pack("<16I", *([0xA55A5AA5] * 16)))
            expected = artifact.identity(reference)
            for name in ("replica0", "replica1", "apply_property"):
                (root / f"{name}.u32le").write_bytes(words)
            stdout = root / "stdout.txt"
            events = [("hbm", -1, 5, 100), ("apply", -1, 6, 80),
                      ("adapter", 0, 9, 71), ("gather", 0, 10, 75), ("mux", 0, 11, 77)]
            lines = [
                f"SHARDED_DEVICE_EVENT stage={role} round=0 shard={shard} worker={shard}"
                f" queued_ns=1 submit_ns=2 start_ns={start} end_ns={end}\n"
                for role, shard, start, end in events
            ]
            lines += ["ACTIVE_MIN_CANDIDATE_BOARD_RESULT status=PASS algorithm=connected_components"
                      " supersteps=1 vertices=2 logical_edges=1 shards=1 active_outputs=1 grasu_launches=0\n"]
            offline = {"tasks": 1, "vertices": 2, "logical_edges": 1, "algorithm": "cc"}
            stdout.write_text("".join(lines))
            args = stdout, root, offline, expected, root
            measured = candidate.inspect(*args)
            self.assertEqual((measured["event_span_ns"], measured["active_outputs"]), (95, 1))
            for broken in (lines + lines[-1:], lines[:-2] + lines[-1:],
                           [line.replace("grasu_launches=0", "grasu_launches=1") for line in lines],
                           [line.replace("start_ns=9", "start_ns=90") for line in lines]):
                stdout.write_text("".join(broken))
                with self.assertRaises(ValueError):
                    candidate.inspect(*args)
            stdout.write_text("".join(lines))
            (root / "replica1.u32le").write_bytes(words[:-1] + b"x")
            with self.assertRaisesRegex(ValueError, "replica1"):
                candidate.inspect(*args)

    def test_uses_span_cutoff_and_actual_clock(self):
        reference = {"event_span_ns": 100, "event_union_ns": 95}
        clock = {"bdf": "0000:c1:00.1", "driver_reported_mhz": [150, 450, 300]}
        for current, candidate_clock, passes in (
                (115, clock, True),
                (116, clock, False),
                (115, {**clock, "driver_reported_mhz": [140, 450, 280]}, False)):
            with self.subTest(current=current, candidate_clock=candidate_clock):
                self.assertEqual(candidate.compare(reference, {"event_span_ns": current, "event_union_ns": 81},
                                                   clock, candidate_clock)["retention_gate_pass"], passes)

    def test_unrouted_candidate_never_leases_a_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "memory.high").write_text(str(7 * 2**30))
            args = argparse.Namespace(output=root / "output", algorithm="cc", bdf="0000:c1:00.1",
                                      device=1, reference_host=root / "ref", candidate_host=root / "candidate",
                                      candidate_route=root / "unrouted")
            with patch.object(pair, "check_memory", return_value=root), patch.dict(pair.os.environ, {}, clear=True), \
                    patch.object(pair, "lease") as lease, self.assertRaises(ValueError):
                pair.run(args)
            lease.assert_not_called()
            record = json.loads((args.output / "results.json").read_text())
            self.assertEqual((record["status"], record["attempts"]), ("FAILED_RETAINED", []))

    def test_candidate_route_replays_terminal_link_and_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            route = Path(tmp)
            (route / "execution").mkdir()
            source = route / "source.cpp"
            source.write_text("source")
            image = route / "candidate.hw.xclbin"
            image.write_bytes(b"image")
            plan_path = route / "manifest.json"
            plan = {"mode": "destination", "clock_mhz": 150, "board_tested": False,
                    "command": ["v++", "--link"], "pins": [artifact.identity(source)]}
            plan_path.write_text(json.dumps(plan))
            executed = {"command": plan["command"], "pins": [artifact.identity(plan_path), *plan["pins"]]}
            (route / "execution/manifest.json").write_text(json.dumps(executed))
            result = {"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD", "xclbin": artifact.identity(image),
                      "kind": "LINK", "board_tested": False, "resources": {"exit_code": 0,
                      "stop_reason": "process_exit", "cleanup_snapshot_error": None}}
            (route / "execution/execution.json").write_text(json.dumps(result))
            self.assertEqual(pair.candidate_route(route, "cc")[0], result["xclbin"])
            with self.assertRaises(ValueError):
                pair.candidate_route(route, "weighted_sssp")
            source.write_text("changed source")
            with self.assertRaises(ValueError):
                pair.candidate_route(route, "cc")

    def test_route_disappearance_requires_observation_and_terminal_artifact(self):
        invocation = "a" * 32
        state = {"LoadState": "not-found", "InvocationID": ""}
        with tempfile.TemporaryDirectory() as tmp:
            route = Path(tmp)
            with self.assertRaisesRegex(ValueError, "never observed"):
                follow.ready("reference", route, state, invocation, False, "cc")
            with self.assertRaisesRegex(ValueError, "artifact evidence"):
                follow.ready("reference", route, state, invocation, True, "cc")
            (route / "results.json").write_text(json.dumps({
                "status": follow.configuration.routed_status("a4", algorithm="cc")}))
            self.assertTrue(follow.ready("reference", route, state, invocation, True, "cc"))
            with self.assertRaisesRegex(ValueError, "invocation changed"):
                follow.ready("reference", route, {"LoadState": "loaded", "InvocationID": "b" * 32},
                             invocation, True, "cc")
