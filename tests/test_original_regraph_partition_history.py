"""Preserve negative attempts; require exact state/counter equality for a pass."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.history import (
    archive_prior, numerical_equality, WATCHDOG_SUFFIXES)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prior = self.root / "run-before"
        self.prior.mkdir()
        state = self.prior / "state.u32le"
        state.write_bytes(b"\x00\x00\x00\x00")
        self.report = {"status": "passed", "sources": [], "cases": [
            {"mode": "warm_update", "paths": [{"cycles": 42}],
             "outputs": [{"path": str(state), "sha256": sha256_file(state)}]}]}
        atomic_write_json(self.prior / "results.json", self.report)

    def test_cycle_and_state_change_rejected(self):
        numerical_equality(self.prior, self.report)
        changed = copy.deepcopy(self.report)
        changed["cases"][0]["paths"][0]["cycles"] += 1
        with self.assertRaises(ValueError):
            numerical_equality(self.prior, changed)
        changed = copy.deepcopy(self.report)
        changed["cases"][0]["outputs"][0]["sha256"] = "changed"
        with self.assertRaises(ValueError):
            numerical_equality(self.prior, changed)

    def test_failed_attempt_preserves_raw_and_declares_missing_source_bytes(self):
        self.report["status"], self.report["error"] = "failed", "cycle budget exhausted"
        atomic_write_json(self.prior / "results.json", self.report)
        for suffix in WATCHDOG_SUFFIXES:
            self.prior.with_name(self.prior.name + "_watchdog." + suffix).write_text("{}")
        destination = self.root / "delivery"
        destination.mkdir()
        result = archive_prior([self.prior], {}, destination)
        self.assertEqual(result["attempts"][0]["error"], "cycle budget exhausted")
        self.assertEqual(result["attempts"][0]["source_status"],
                         "historical_source_hashes_only_bytes_not_recoverable")
        self.assertFalse(result["attempts"][0]["numerical_equality_to_current"])
        names = [row["path"] for row in result["files"]]
        self.assertIn("attempts/run-before/run/results.json", names)
        self.assertIn("attempts/run-before/run/state.u32le", names)

    def test_duplicate_prior_rejected_before_archiving(self):
        with self.assertRaises(ValueError):
            archive_prior([self.prior, self.prior], self.report, self.root)


if __name__ == "__main__":
    unittest.main()
