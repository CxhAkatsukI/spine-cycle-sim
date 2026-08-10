from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LargeRealManifestTests(unittest.TestCase):
    def _load(self, name: str) -> dict[str, object]:
        path = ROOT / "configs/experiments" / name
        return json.loads(path.read_text(encoding="utf-8"))

    def test_gate_and_full_manifests_declare_their_actual_scope(self) -> None:
        gate = self._load("askubuntu_reciprocal_large_v1.json")
        full = self._load("askubuntu_reciprocal_full_v1.json")

        self.assertEqual(
            gate["claim_class"], "derived_real_topology_large_reciprocal_gate"
        )
        self.assertEqual(
            full["claim_class"],
            "derived_real_topology_full_reciprocal_projection",
        )
        self.assertTrue(
            all(
                run["dataset_id"] == "sx_askubuntu_reciprocal_gate"
                for run in gate["runs"]
            )
        )
        self.assertTrue(
            all(
                run["dataset_id"] == "sx_askubuntu_reciprocal_full"
                for run in full["runs"]
            )
        )

        for manifest in (gate, full):
            records = manifest["transformation"]["output_reciprocal_records"]
            pairs = manifest["transformation"]["selected_undirected_pairs"]
            self.assertEqual(records, 2 * pairs)
            self.assertIn(
                f"The {records} reciprocal records represent {pairs} unique undirected pairs.",
                manifest["limitations"],
            )


if __name__ == "__main__":
    unittest.main()
