"""Synthetic transport/admission negatives, never an FPGA admission claim."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import original_grasu_return_fixture as fixture
from test_original_grasu_routed import fixture as topology, metadata
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import (
    admission, configuration as config, delivery, records)


class OriginalGReturnTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source, self.route, hashes = fixture.build(self.root)
        patcher = patch.object(config, "SOURCE_HASHES", hashes)
        patcher.start()
        self.addCleanup(patcher.stop)
        fixture.finish(self.source, self.route)

    def seal(self):
        returned = self.root / "returned"
        with patch.object(delivery, "service_state", return_value=fixture.STATE):
            pin = delivery.seal(self.source, self.route, returned, unit=fixture.UNIT, invocation=fixture.INVOCATION)
        return returned, pin["sha256"]

    def test_exact_return_relocated_and_admitted_without_board_claims(self):
        returned, digest = self.seal()
        moved = self.root / "relocated"
        returned.rename(moved)
        self.assertEqual(len(delivery.verify(moved, digest)["files"]), len(delivery.MEMBERS))
        with patch.object(admission.bitstream, "_dump", side_effect=lambda binary, path: metadata(path, topology())):
            result = admission.review(moved, self.root / "admission", receipt_sha256=digest)
        self.assertEqual(result["status"], admission.PASS)
        self.assertTrue(all(result[flag] is False for flag in config.FLAGS))

    def test_bad_terminal_or_inflight_service_does_not_seal(self):
        for change in (dict(SubState="running", MainPID="123"), dict(Result="timeout"),
                       dict(InvocationID="2" * 32), dict(ExecMainStatus="1")):
            with self.subTest(change=change), patch.object(delivery, "service_state", return_value=dict(fixture.STATE, **change)), \
                    self.assertRaises(ValueError):
                delivery.seal(self.source, self.route, self.root / "forbidden", unit=fixture.UNIT, invocation=fixture.INVOCATION)
        self.assertFalse((self.root / "forbidden").exists())

    def test_incomplete_oom_or_false_raw_record_rejected(self):
        original = records.read(self.route, "results.json")
        for damage in ("step", "oom", "raw", "claim", "policy", "header", "conflicting_pin"):
            result = json.loads(json.dumps(original))
            manifest = records.read(self.route, "manifest.json")
            pristine = json.loads(json.dumps(manifest))
            if damage == "step":
                result["steps"].pop()
            elif damage == "oom":
                result["memory_events_after"] = "oom 1\noom_kill 0\noom_group_kill 0\n"
            elif damage == "raw":
                result["steps"][0]["reserve_gib"] = 0
            elif damage == "claim":
                result["publication_performance_match"] = True
            elif damage == "policy":
                manifest["policy"] = {**config.POLICY, "tree_memory_gib": 100}
            elif damage == "header":
                manifest["pins"] = [row for row in manifest["pins"] if not row["path"].endswith("ap_utils.h")]
            else:
                manifest["pins"].append(dict(manifest["pins"][0], sha256="0" * 64))
            fixture.write(self.route, "results.json", result)
            fixture.write(self.route, "manifest.json", manifest)
            with self.subTest(damage=damage), self.assertRaises(ValueError):
                records.completed(self.route, remote_route=self.route, remote_packet=self.source)
            fixture.write(self.route, "manifest.json", pristine)
        fixture.write(self.route, "results.json", original)

    def test_changed_source_hls_or_multiple_final_reports_rejected(self):
        path = self.route / "hls/bin_search/bin_search_csynth.xml"
        saved = path.read_bytes()
        path.write_bytes(saved + b" ")
        with patch.object(delivery, "service_state", return_value=fixture.STATE), self.assertRaises(ValueError):
            delivery.seal(self.source, self.route, self.root / "no-hls", unit=fixture.UNIT, invocation=fixture.INVOCATION)
        path.write_bytes(saved)
        extra = self.route / "link/report/extra" / delivery.TIMING
        extra.parent.mkdir()
        extra.write_text("extra")
        with patch.object(delivery, "service_state", return_value=fixture.STATE), self.assertRaises(ValueError):
            delivery.seal(self.source, self.route, self.root / "no-duplicate", unit=fixture.UNIT, invocation=fixture.INVOCATION)

    def test_trusted_digest_member_hash_and_closed_membership_required(self):
        returned, digest = self.seal()
        with self.assertRaises(ValueError):
            delivery.verify(returned, "0" * 64)
        receipt = records.read(returned, "receipt.json")
        receipt["files"].pop()
        fixture.write(returned, "receipt.json", receipt)
        with self.assertRaisesRegex(ValueError, "scope"):
            delivery.verify(returned, sha256_file(returned / "receipt.json"))

    def test_downclocked_artifact_fails_before_any_board_claim(self):
        returned, digest = self.seal()
        data = topology()
        data["clock"][0] = ("DATA", "DATA_CLK", 100)
        with patch.object(admission.bitstream, "_dump", side_effect=lambda binary, path: metadata(path, data)), \
                self.assertRaises(ValueError):
            admission.review(returned, self.root / "rejected", receipt_sha256=digest)
        report = records.read(self.root / "rejected", "summary.json")
        self.assertEqual(report["status"], "FAILED_RETAINED")
        self.assertTrue(all(report[flag] is False for flag in config.FLAGS))

    def test_unrecorded_return_file_is_not_accepted(self):
        returned, digest = self.seal()
        (returned / "unrecorded.txt").write_text("extra")
        with self.assertRaisesRegex(ValueError, "scope"):
            delivery.verify(returned, digest)


if __name__ == "__main__":
    unittest.main()
