"""Fail-closed external-port transport, replay and admission; no actual XRT."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import original_grasu_external_return_fixture as fixture
import original_grasu_return_fixture as original
from test_original_grasu_routed import fixture as topology, metadata
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import configuration as config, records
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import follow as driver
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import execution as board
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.physical_port import admission, delivery, follow, replay, route_inputs


class ExternalReturnTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.packet, self.compiled, hashes = original.build(self.root)
        patcher = patch.object(config, "SOURCE_HASHES", hashes)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bd, self.outer = fixture.chain(self.root, self.packet, self.compiled)
        self.route = self.outer / "link_attempt"

    def seal(self):
        returned = self.root / "returned"
        with patch.object(route_inputs, "service_state", side_effect=fixture.state):
            pin = delivery.seal(self.packet, self.outer, returned, unit=original.UNIT, invocation=original.INVOCATION)
        return returned, pin["sha256"]

    def resign(self, root, member):
        receipt = records.read(root, "receipt.json")
        for row in receipt["files"]:
            if row["member"] == member:
                row["sha256"] = row["source"]["sha256"] = sha256_file(root / member)
        original.write(root, "receipt.json", receipt)
        return sha256_file(root / "receipt.json")

    def test_relocated_return_admits_distinct_profile_not_board(self):
        returned, digest = self.seal()
        relocated = self.root / "relocated"
        returned.rename(relocated)
        receipt = delivery.verify(relocated, digest)
        self.assertEqual(len(receipt["files"]), len(delivery.members()))
        self.assertTrue(receipt["physical_interconnect_changed"])
        with patch.object(admission.bitstream, "_dump", side_effect=lambda binary, path: metadata(path, topology())):
            result = admission.review(relocated, self.root / "admitted", receipt_sha256=digest)
        self.assertEqual(result["status"], admission.PASS)
        self.assertEqual(board.control_profile(result), (route_inputs.PROFILE, board.EXTERNAL_PASS))
        self.assertTrue(all(result[flag] is False for flag in config.FLAGS))

    def test_running_or_replaced_full_link_never_seals(self):
        for changes in (dict(SubState="running", MainPID="3"), dict(InvocationID="3" * 32), dict(Result="timeout")):
            with self.subTest(changes=changes), patch.object(route_inputs, "service_state",
                    return_value=dict(original.STATE, **changes)), self.assertRaises(ValueError):
                delivery.seal(self.packet, self.outer, self.root / "forbidden", unit=original.UNIT, invocation=original.INVOCATION)
        self.assertFalse((self.root / "forbidden").exists())

    def test_changed_child_identity_stops_before_export(self):
        path = self.route / "results.json"
        path.write_text(path.read_text() + " ")
        with patch.object(route_inputs, "service_state", side_effect=fixture.state), self.assertRaises(ValueError):
            delivery.seal(self.packet, self.outer, self.root / "forbidden", unit=original.UNIT, invocation=original.INVOCATION)
        self.assertFalse((self.root / "forbidden").exists())

    def test_bad_raw_compile_is_not_accepted_as_reused_xo(self):
        built = records.read(self.compiled, "results.json")
        built["steps"][0]["reserve_gib"] = 0
        original.write(self.compiled, "results.json", built)
        with self.assertRaises(ValueError):
            records.compilations(self.compiled, remote_route=self.compiled, remote_packet=self.packet)

    def test_transport_digest_extra_file_and_corruption_rejected(self):
        returned, digest = self.seal()
        with self.assertRaises(ValueError):
            delivery.verify(returned, "0" * 64)
        (returned / "extra.txt").write_text("unrecorded")
        with self.assertRaisesRegex(ValueError, "scope"):
            delivery.verify(returned, digest)
        (returned / "extra.txt").unlink()
        (returned / "route/hooks/post_link.tcl").write_text("changed hook")
        with self.assertRaisesRegex(ValueError, "changed"):
            delivery.verify(returned, digest)

    def test_raw_link_execution_independently_replayed(self):
        returned, _ = self.seal()
        value = records.read(returned / "route", "link.resources.json")
        value["timeout_seconds"] = 1
        original.write(returned / "route", "link.resources.json", value)
        digest = self.resign(returned, "route/link.resources.json")
        with self.assertRaisesRegex(ValueError, "raw link"):
            delivery.verify(returned, digest)

    def test_unsafe_receipt_duplicate_and_false_profile_rejected(self):
        returned, _ = self.seal()
        pristine = records.read(returned, "receipt.json")
        for damage in ("member", "duplicate", "source", "profile", "claim"):
            value = json.loads(json.dumps(pristine))
            if damage == "member":
                value["files"][0]["member"] = "../outside"
            elif damage == "duplicate":
                value["files"].append(value["files"][0])
            elif damage == "source":
                value["files"][0]["source"]["path"] = "/wrong/origin"
            elif damage == "profile":
                value["profile"] = "direct_46_ports"
            else:
                value["publication_performance_match"] = True
            original.write(returned, "receipt.json", value)
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                delivery.verify(returned, sha256_file(returned / "receipt.json"))

    def test_bad_containment_and_oom_records_rejected(self):
        for damage in ("oom", "max", "group", "admitted"):
            result = records.read(self.route, "results.json")
            if damage == "oom":
                result["memory_events_after"] = "oom 0\noom_kill 1\noom_group_kill 0\n"
            elif damage == "max":
                result["containment"]["limits"]["memory.max"] = "max"
            elif damage == "group":
                result["containment"]["limits"]["memory.oom.group"] = "0"
            else:
                result["admission"]["admitted"] = False
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                replay.bounded(result)

    def test_downclock_keeps_claims_false(self):
        returned, digest = self.seal()
        data = topology()
        data["clock"][0] = ("DATA", "DATA_CLK", 147)
        with patch.object(admission.bitstream, "_dump", side_effect=lambda binary, path: metadata(path, data)), \
                self.assertRaises(ValueError):
            admission.review(returned, self.root / "bad_clock", receipt_sha256=digest)
        result = records.read(self.root / "bad_clock", "summary.json")
        self.assertEqual(result["status"], "FAILED_RETAINED")
        self.assertTrue(all(result[flag] is False for flag in config.FLAGS))

    def test_failed_routed_timing_keeps_claims_false(self):
        returned, _ = self.seal()
        member = "route/" + delivery.direct.TIMING
        path = returned / member
        path.write_text(path.read_text().replace("0.002", "-0.002"))
        digest = self.resign(returned, member)
        with patch.object(admission.bitstream, "_dump", side_effect=lambda binary, path: metadata(path, topology())), \
                self.assertRaises(ValueError):
            admission.review(returned, self.root / "bad_timing", receipt_sha256=digest)
        result = records.read(self.root / "bad_timing", "summary.json")
        self.assertEqual(result["status"], "FAILED_RETAINED")
        self.assertTrue(all(result[flag] is False for flag in config.FLAGS))

    def test_shared_follow_uses_external_replay_and_never_requests_board(self):
        returned, digest = self.seal()
        remote = Mock(unit=original.UNIT, invocation=original.INVOCATION, capsule=self.packet, attempt=self.outer)
        remote.state.return_value = original.STATE
        remote.seal.return_value = digest
        remote.transfer.side_effect = lambda output: shutil.copytree(returned, output)
        output = self.root / "followed"
        with patch.object(driver, "current"), patch.object(driver, "verify", return_value={}), \
                patch.object(driver, "runner_pins", return_value=[]), \
                patch.object(admission.bitstream, "_dump", side_effect=lambda binary, path: metadata(path, topology())), \
                patch.object(driver.board, "run") as run_board:
            result = driver.run(remote, output, reviewer=admission, board_pass=board.EXTERNAL_PASS)
        self.assertEqual(result["status"], driver.PASS)
        self.assertEqual(result["profile"], route_inputs.PROFILE)
        self.assertFalse(result["board_requested"])
        self.assertTrue(all(result[flag] is False for flag in config.FLAGS))
        self.assertEqual(records.read(output / "admission", "summary.json")["status"], admission.PASS)
        run_board.assert_not_called()

    def test_sealer_command_is_bounded_and_names_physical_module(self):
        remote = follow.ExternalPortRemote("u@host", 23333, Path("/runner"), Path("/packet"), Path("/outer"),
            Path("/returned"), original.UNIT, original.INVOCATION)
        with patch.object(follow.ExternalPortRemote, "command", return_value="a" * 64) as command:
            self.assertEqual(remote.seal(), "a" * 64)
        argv = command.call_args.args[0]
        self.assertIn("--property=MemoryMax=4G", argv)
        self.assertEqual(argv[argv.index("-m") + 1], delivery.__name__)
        self.assertEqual(argv[argv.index("--continuation") + 1], Path("/outer"))

    def test_board_profile_rejects_a_hidden_or_incomplete_adaptation(self):
        checked = dict(status=admission.PASS, errors=[], profile=route_inputs.PROFILE,
            source_modified=False, physical_interconnect_changed=True, **dict.fromkeys(config.FLAGS, False))
        self.assertEqual(board.control_profile(checked)[1], board.EXTERNAL_PASS)
        for changes in (dict(profile="direct"), dict(physical_interconnect_changed=False),
                        dict(source_modified=True), dict(errors=["failed"]), dict(final_figures_admitted=True)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                board.control_profile(dict(checked, **changes))
        with self.assertRaises(ValueError):
            board.control_profile(dict(checked, status=board.admission.PASS))


if __name__ == "__main__":
    unittest.main()
