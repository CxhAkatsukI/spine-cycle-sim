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

    def test_lower_clock_sssp_never_reuses_nominal_or_leases_incompatible_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verifier = root / "verify"
            verifier.touch()
            args = argparse.Namespace(output=root / "output", algorithm="weighted_sssp", bdf="0000:82:00.1",
                                      device=0, reference_host=root / "ref", candidate_host=root / "candidate",
                                      derated_hbm=("445", str(verifier)), board_wait_seconds=30,
                                      returned_candidate=("digest", "capsule", "platform", "predecessor"),
                                      retained_reference=("nominal", "digest"))
            with self.assertRaisesRegex(ValueError, "fresh public control"):
                pair.lower_clock_options(args)
            args.retained_reference = None
            (root / "memory.high").write_text(str(7 * 2**30))
            with patch.object(pair, "check_memory", return_value=root), patch.dict(pair.os.environ, {}, clear=True), \
                    patch.object(pair.runtime, "require_clean_environment"), \
                    patch.object(pair, "derated_candidate", return_value=({"vendor_hbm_mhz": None}, [])), \
                    patch.object(pair.pair_resources, "admit") as board:
                result = pair.run(args)
            board.assert_not_called()
            self.assertEqual(result["status"], "NO_COMPATIBLE_DERATING_NO_BOARD_RUN")
            self.assertEqual(result["attempts"], [])
            self.assertFalse(result["matrix_admitted"])

    def test_repackage_reference_checks_runtime_identity_without_requiring_size_in_board_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference, verifier = root / "reference.xclbin", root / "verify"
            reference.write_text("reference")
            verifier.write_text("verifier")

            def pack(source, tool, target, output):
                output.mkdir()
                binary = output / "control.xclbin"
                binary.write_text("clock-only copy")
                identity = pair.clocks.identity
                (output / "package.json").write_text(json.dumps(dict(
                    status="OFFLINE_VERIFIED_NOT_BOARD_QUALIFIED", requested_hbm_mhz=target,
                    original={"binary": identity(source)}, derived={"binary": identity(binary)},
                    verifier=identity(tool))))

            with patch.object(pair.repackage_hbm, "run", side_effect=pack):
                output = root / "output"
                image, receipt, checked = pair.repackage_reference(artifact.identity(reference), 445, verifier, output)
                self.assertEqual((image, receipt, checked), tuple(map(
                    artifact.identity, (output / "control.xclbin", output / "package.json", verifier))))

    def test_retained_reference_requires_exact_receipt_fixture_image_and_oracle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = argparse.Namespace(algorithm="weighted_sssp", bdf="0000:82:00.1", inputs=root,
                                      reference_host=root / "ref", candidate_host=root / "candidate")
            inputs = pair.input_paths(args)
            for path in inputs:
                path.write_bytes(b"original")
            receipt = root / "results.json"
            analysis = {"event_span_ns": 100, "output_pins": []}
            row = {"analysis": analysis, "clock_evidence": {}}
            receipt.write_text(json.dumps({
                "algorithm": args.algorithm, "bdf": args.bdf, "requested_runs_per_arm": 1,
                "attempts": ["reference", "candidate"], "boundary": pair.active_min.BOUNDARY,
                "status": "PAIRED_ACTIVE_MIN_R_GATE_FAILED_RETAINED",
                "pins": [artifact.identity(path) for path in inputs],
                "arms": {"reference": row},
            }))
            pin = artifact.identity(receipt)
            image = {"path": "/ref.xclbin", "sha256": "image"}
            clock = {"binary": {**image, "bytes": 41}, "bdf": args.bdf}
            with patch.object(pair.clocks, "replay", return_value=clock), \
                    patch.object(pair.active_min, "inspect", return_value=analysis) as inspect:
                replay = lambda digest: pair.retained_reference(receipt, digest, args, image, {}, {})
                args.candidate_host.write_bytes(b"new host")
                self.assertEqual(replay(pin["sha256"]), (row, pin))
                with self.assertRaisesRegex(ValueError, "digest"):
                    replay("different")
                clock["binary"]["sha256"] = "different"
                with self.assertRaisesRegex(ValueError, "image"):
                    replay(pin["sha256"])
                clock["binary"]["sha256"] = image["sha256"]
                inspect.return_value = {}
                with self.assertRaisesRegex(ValueError, "analysis"):
                    replay(pin["sha256"])
                inputs[-1].write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "fixture"):
                    replay(pin["sha256"])

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
