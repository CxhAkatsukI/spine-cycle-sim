"""Explicit preflight receipts retain schema, dependency and producer checks."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import configuration as config
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import execution as original, preflight
from spine_cycle_sim.experiments.upstream_controls.grasu.host.fixtures import NAMES
from spine_cycle_sim.experiments.evaluation_impact.common_g.matched_original import analysis
from spine_cycle_sim.experiments.evaluation_impact.common_g.matched_original.board import inputs, execution, follow


def capture(root):
    directory = root / "original"
    (directory / "inputs").mkdir(parents=True)
    binary = directory / "probe"
    binary.write_bytes(b"frozen host")
    cases = [{"id": name, "facts": {"vertices": 3, "segments": 1, "updates": 2,
              "route_updates": [2, 0, 0, 0]}} for name in NAMES]
    manifest = directory / "inputs/manifest.json"
    manifest.write_text(json.dumps({"status": "ORIGINAL_G_CAPTURE_REPLAY_PASS_NOT_BOARD",
        "baseline_sha256": original.preparation.BASELINE_SHA256, "cases": cases, "pins": []}))
    report = {"status": preflight.STATUS, "errors": [], **dict.fromkeys(config.FLAGS, False),
        "steps": [None] * 21, "cases": [{"variant": v, "id": name} for v in ("release", "ubsan") for name in NAMES],
        "binaries": [{"variant": "release", **identity(binary)}],
        "pins": [identity(binary), identity(manifest)], "runtime_libraries": []}
    result = directory / "results.json"
    result.write_text(json.dumps(report))
    return directory, identity(result)["sha256"], cases


def matched_capture(root, prerequisite, cases):
    directory = root / "matched"
    directory.mkdir()
    binary = directory / "probe"
    binary.write_bytes(b"frozen matched host")
    report = {"status": analysis.STATUS, "errors": [], **dict.fromkeys(analysis.CLAIMS, False),
        "original_preflight": identity(prerequisite / "results.json"), "steps": [None] * 22,
        "cases": [{"variant": v, "id": case["id"], **analysis.expected(case)}
                  for v in ("release", "ubsan") for case in cases],
        "binaries": [{"variant": "release", **identity(binary)}],
        "pins": [identity(binary)], "runtime_libraries": []}
    result = directory / "results.json"
    result.write_text(json.dumps(report))
    return directory, identity(result)["sha256"]


class PreflightIdentityTests(unittest.TestCase):
    def test_new_original_receipt_requires_explicit_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, digest, cases = capture(Path(temporary))
            with self.assertRaises(ValueError):
                original.inputs(root)
            host, actual, pins = original.inputs(root, expected_sha256=digest)
            self.assertEqual(host, root / "probe")
            self.assertEqual(actual, cases)
            self.assertIn(identity(root / "results.json"), pins)
            (root / "probe").write_bytes(b"changed host")
            with self.assertRaises(ValueError):
                original.inputs(root, expected_sha256=digest)

    def test_digest_does_not_waive_original_schema_or_claims(self):
        for changes in ({"errors": ["failed"]}, {"publication_performance_match": True},
                        {"steps": []}, {"status": "RUNNING"}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                root, _, _ = capture(Path(temporary))
                path = root / "results.json"
                report = json.loads(path.read_text())
                report.update(changes)
                path.write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    original.inputs(root, expected_sha256=identity(path)["sha256"])

    def test_both_matched_and_original_receipts_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prerequisite, digest, cases = capture(root)
            matched, matched_digest = matched_capture(root, prerequisite, cases)
            for kwargs in ({}, {"preflight_sha256": matched_digest},
                           {"original_preflight_sha256": digest}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    inputs.load(matched, prerequisite, **kwargs)
            host, actual, _ = inputs.load(matched, prerequisite, preflight_sha256=matched_digest,
                                          original_preflight_sha256=digest)
            self.assertEqual(host, matched / "probe")
            self.assertEqual(actual, cases)
            (matched / "probe").write_bytes(b"changed matched host")
            with self.assertRaises(ValueError):
                inputs.load(matched, prerequisite, preflight_sha256=matched_digest,
                            original_preflight_sha256=digest)

    def test_malformed_digests_are_not_auto_discovered(self):
        for digest in (None, True, "latest", "A" * 64, "a" * 63):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                original.inputs(Path("/absent"), expected_sha256=digest)
            with self.subTest(matched=digest), self.assertRaises(ValueError):
                inputs.load(Path("/absent"), Path("/absent"), preflight_sha256=digest)

    def test_execution_forwards_both_reviewed_receipts_before_admission(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(execution, "current"), patch.object(execution, "verify", return_value={}), \
                    patch.object(inputs, "load", side_effect=ValueError("stop before board")) as load:
                with self.assertRaisesRegex(ValueError, "stop before board"):
                    execution.run(*([root] * 5), root / "output", receipt_sha256="a" * 64,
                                  preflight_sha256="b" * 64, original_preflight_sha256="c" * 64)
            load.assert_called_once_with(root, root, preflight_sha256="b" * 64,
                                         original_preflight_sha256="c" * 64)

    def test_follow_reuses_same_receipts_at_board_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text('{"pins": []}')
            (root / "results.json").write_text(json.dumps({"status": follow.qualification.PASS,
                "board_correctness_measured": True, "board_started": True, "errors": [],
                "device_index": 0, "receipt_sha256": "a" * 64}))
            with patch.object(follow, "current"), patch.object(follow, "verify", return_value={}), \
                    patch.object(inputs, "load", return_value=(root, [None] * 8, [])) as load, \
                    patch.object(follow, "runner_pins", return_value=[]), patch.object(follow, "unchanged"), \
                    patch.object(follow, "service_state", return_value={}), \
                    patch.object(follow, "route_finished", return_value=True), \
                    patch.object(execution, "run", side_effect=ValueError("stop at handoff")) as execute:
                with self.assertRaisesRegex(ValueError, "stop at handoff"):
                    follow.run(*([root] * 4), root / "results.json", root / "output",
                               unit="producer.service", invocation="d" * 32,
                               preflight_sha256="b" * 64, original_preflight_sha256="c" * 64)
            load.assert_called_once_with(root, root, preflight_sha256="b" * 64,
                                         original_preflight_sha256="c" * 64)
            self.assertEqual(execute.call_args.kwargs["preflight_sha256"], "b" * 64)
            self.assertEqual(execute.call_args.kwargs["original_preflight_sha256"], "c" * 64)


if __name__ == "__main__":
    unittest.main()
