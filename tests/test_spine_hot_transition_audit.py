from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_spine_hot_transition_successor import audit_transition


def result(plugin: str, cycles: int, hot_edges: int) -> dict:
    return {
        "status": "pass",
        "plugin_sha256": plugin,
        "case": {
            "execution_id": "execution",
            "system": "spine",
            "algorithm": "weighted_sssp",
        },
        "final_state": {"sha256": "f" * 64},
        "scalar_metrics": {"resident_hot_edges": hot_edges},
        "row": {"cycles": cycles},
        "admission": {
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "parent_problems": [],
            "plugin_admission": {
                "classification": "frozen_simulator_baseline",
                "observed_plugin_sha256": plugin,
                "baseline_plugin_sha256": plugin,
            },
        },
    }


class SpineHotTransitionAuditTests(unittest.TestCase):
    def audit(self, old: dict, new: dict) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_path = root / "old.json"
            new_path = root / "new.json"
            old_path.write_text(json.dumps(old), encoding="ascii")
            new_path.write_text(json.dumps(new), encoding="ascii")
            return audit_transition(old_path, new_path)

    def test_accepts_identical_case_and_state_with_lower_hot_work(self) -> None:
        old = result("a" * 64, 100, 20)
        new = result("b" * 64, 90, 12)
        audit = self.audit(old, new)
        self.assertEqual(audit["cycle_delta"], -10)
        self.assertEqual(audit["hot_edge_reduction"], 8)
        self.assertTrue(audit["checks"]["new_hot_edges_lower"])

    def test_rejects_changed_final_state(self) -> None:
        old = result("a" * 64, 100, 20)
        new = result("b" * 64, 90, 12)
        new["final_state"] = {"sha256": "e" * 64}
        with self.assertRaisesRegex(ValueError, "changed final state"):
            self.audit(old, new)

    def test_rejects_increased_hot_work(self) -> None:
        old = result("a" * 64, 100, 20)
        new = result("b" * 64, 90, 21)
        with self.assertRaisesRegex(ValueError, "increased resident hot edges"):
            self.audit(old, new)


if __name__ == "__main__":
    unittest.main()
