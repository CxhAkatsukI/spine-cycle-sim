from __future__ import annotations

from pathlib import Path
import unittest

from spine_cycle_sim.evidence.area_projection import analyze_area_projection_manifest


ROOT = Path(__file__).resolve().parents[1]


class AreaProjectionTests(unittest.TestCase):
    def test_repository_projection_is_explicitly_partial(self) -> None:
        result = analyze_area_projection_manifest(
            ROOT / "configs/evidence/candidate10_area_projection_v1.json"
        )
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["full_asic_area_available"])
        self.assertEqual(len(result["builds"]), 4)
        self.assertTrue(
            all(row["projected_32nm_sram_capacity_area_mm2"] > 0 for row in result["builds"])
        )
        self.assertTrue(all(not row["full_asic_area_available"] for row in result["builds"]))


if __name__ == "__main__":
    unittest.main()
