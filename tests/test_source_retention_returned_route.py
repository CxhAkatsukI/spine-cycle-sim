"""Bind the returned route and its raw board R evidence before independent G."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import returned_route
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity, save
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import candidate_board


class ReturnedRouteTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.plan = self.root / "plan"
        self.capsule = self.root / "capsule"
        self.returned = self.root / "returned"
        self.output = self.root / "admission"
        self.original = self.root / "original.hw.xclbin"
        self.image = self.returned / "route/candidate.hw.xclbin"
        self.timing = self.returned / "route/timing.rpt"
        self.plan.mkdir()
        self.capsule.mkdir()
        self.image.parent.mkdir(parents=True)
        for path in (self.original, self.image, self.timing, self.returned / "receipt.json"):
            path.write_bytes(b"original evidence")
        self.parent = {"production": str(self.root), "tail_hosts": {}, "pins": []}
        save(self.plan / "manifest.json", self.parent)
        self.plan_pin = artifact.identity(self.plan / "manifest.json")
        save(self.capsule / "capsule.json", {"parent": self.plan_pin})
        save(self.root / "transfer.json", {"status": "REMOTE_REPLACEMENT_LINK_VERIFIED_NOT_BOARD_EVIDENCE",
                                         "candidate": artifact.identity(self.image), "receipt_sha256": "a" * 64})

    def admit(self, *, clock=150):
        with patch.object(returned_route.replacement_return, "verify",
                          return_value=({}, self.parent, [self.plan_pin])), \
                patch.object(returned_route.bitstream, "_dump", return_value={}), \
                patch.object(returned_route.bitstream, "normalized_topology",
                             return_value={"clock": [("DATA", "DATA_CLK", clock)]}), \
                patch.object(returned_route.bitstream, "parse_routed_timing",
                             return_value={"report": identity(self.timing)}):
            return returned_route.admit(self.plan, self.returned, self.capsule, self.root / "platform.xpfm",
                                        self.original, self.output)

    def test_collector_and_local_plan_must_match(self):
        self.image.write_bytes(b"replacement without seal")
        with self.assertRaisesRegex(ValueError, "collector"):
            self.admit()
        self.image.write_bytes(b"original evidence")
        save(self.plan / "manifest.json", {**self.parent, "changed": True})
        with self.assertRaisesRegex(ValueError, "local plan"):
            self.admit()

    def test_150mhz_required(self):
        with self.assertRaisesRegex(ValueError, "150-MHz"):
            self.admit(clock=140)

    def test_integer_metadata_may_truncate_the_nominal_clock(self):
        self.assertEqual(returned_route.comparable_topology({"clock": [("DATA", "DATA_CLK", 149)]}),
                         returned_route.comparable_topology({"clock": [("DATA", "DATA_CLK", 150)]}))

    def test_preserves_pins_from_queued_local_route_g_checker(self):
        image = self.plan / "candidate.hw.xclbin"
        image.write_bytes(b"local image")
        image_pin = identity(image)
        execution = self.plan / "execution/execution.json"
        execution.parent.mkdir()
        save(execution, {"status": "LINK_PASS_AWAITING_TIMING_AND_BOARD", "xclbin": image_pin})
        analysis = self.root / "analysis.json"
        save(analysis, {})
        raw = self.root / "board-once/results.json"
        raw.parent.mkdir()
        save(raw, {"device": candidate_board.DEVICE, "bdf": candidate_board.BDF,
                   "pins": {"r_current": image_pin}})
        screen = self.root / "results.json"
        save(screen, {"status": candidate_board.R_PASS, "analysis": identity(analysis),
                      "pins": [image_pin, identity(execution)]})
        with patch.object(candidate_board, "check_memory"):
            self.assertEqual(candidate_board.wait_for_image(self.plan, screen, 0),
                             (image, candidate_board.R_PASS, [identity(screen), identity(execution),
                                                              identity(raw), image_pin, identity(analysis)]))

    def test_g_requires_same_admission_and_raw_board_image(self):
        image, image_pin, proof = self.admit()
        self.assertEqual(image, self.image)
        analysis = self.root / "analysis.json"
        save(analysis, {})
        raw = self.root / "board-once/results.json"
        raw.parent.mkdir()
        board = {"device": candidate_board.DEVICE, "bdf": candidate_board.BDF,
                 "pins": {"r_current": identity(self.image)}}
        save(raw, board)
        screen = self.root / "results.json"
        report = {"status": candidate_board.R_PASS, "analysis": identity(analysis), "pins": [image_pin, proof],
                  "returned_admission": proof}
        save(screen, report)
        with patch.object(candidate_board, "check_memory"):
            self.assertEqual(candidate_board.wait_for_image(self.plan, screen, 0)[0], self.image)
            board["pins"]["r_current"] = identity(self.original)
            save(raw, board)
            with self.assertRaisesRegex(ValueError, "differs from the R screen"):
                candidate_board.wait_for_image(self.plan, screen, 0)
            self.timing.write_bytes(b"changed after R")
            with self.assertRaisesRegex(ValueError, "changed"):
                candidate_board.wait_for_image(self.plan, screen, 0)
            report["pins"].remove(proof)
            save(screen, report)
            with self.assertRaisesRegex(ValueError, "not pinned"):
                candidate_board.wait_for_image(self.plan, screen, 0)
