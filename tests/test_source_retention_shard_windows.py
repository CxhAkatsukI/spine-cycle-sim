import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.shard_layout import (
    slot_counts,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.shard_windows import (
    publication_windows, replay_derated_respr,
)


class PublicationWindowsTest(unittest.TestCase):
    def test_replays_archived_430_mhz_pair_without_a_board(self):
        archive = (Path(__file__).resolve().parents[1] / "docs/experiments/comparisons"
                   / "grasu_regraph_stage_validation/evaluation_impact/hardware_validation"
                   / "r_retention_repair_20261103/respr-apply-off-430-raw.tar.gz")
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            with tarfile.open(archive) as packed:
                packed.extractall(root, filter="data")
            receipt = root / "derated-respr-tail-bursts-apply-off-430-v1/results.json"
            result = replay_derated_respr(receipt, root)
            self.assertEqual(result["driver_reported_mhz"], [150, 500, 430, 0])
            self.assertFalse(result["gate_pass"])
            self.assertEqual(result["excess_over_gate_ns"], 224118.75)
            self.assertEqual(result["after_last_adapter_ns"], 329700)
            self.assertEqual(result["budget_after_last_adapter_ns"], 105581.25)
            self.assertEqual(result["candidate_milestones_from_first_start_ns"]["last_gather_end_ns"], 723441)

            tampered = json.loads(receipt.read_text())
            tampered["comparison"]["current_ms"] = 0.6
            receipt.write_text(json.dumps(tampered))
            with self.assertRaisesRegex(ValueError, "saved comparison differs"):
                replay_derated_respr(receipt, root)

    def test_layout_remaps_nonempty_sources_and_keeps_leading_guard(self):
        self.assertEqual(slot_counts([0, 0, 1, 1, 2], [0, 1], 2), ([1, 1], [32, 16]))
        self.assertEqual(slot_counts([0, 0, 0], [], 1), ([0, 0], [16, 16]))
        with self.assertRaisesRegex(ValueError, "unique"):
            slot_counts([0, 2, 2], [1, 1], 1)

    def test_preserves_envelope_and_does_not_add_overlapping_frontends(self):
        config = {"shards": 5, "pma_slots": 320, "edges": 100}
        intervals = [(10, 100), (11, 99)] + [
            (11 + s, 46 + s) if role == 0 else (12 + s, 53 + s) if role == 1
            else (20 + 10 * s, 28 + 10 * s)
            for s in range(5) for role in range(3)
        ]
        events = [{"ordinal": i, "start_ns": a, "end_ns": b}
                  for i, (a, b) in enumerate(intervals)]
        result = publication_windows(config, events, 90)
        self.assertEqual(result["mux_span_by_worker_ns"], [16, 8, 8, 8])
        self.assertEqual(result["fraction_of_elapsed_by_worker"][0], 16 / 90)
        self.assertEqual(result["windows"][4]["mux_start_ns"], 50)
        events[7]["start_ns"] = 25
        with self.assertRaisesRegex(ValueError, "ordered publication"):
            publication_windows(config, events, 90)
