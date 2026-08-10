import unittest
from pathlib import Path

from scripts.analyze_candidate10_optimization_robustness import (
    build_ablation_rows,
    build_sensitivity_rows,
)


ROOT = Path(__file__).resolve().parents[1]


class Candidate10OptimizationRobustnessTest(unittest.TestCase):
    def test_committed_ablation_evidence(self) -> None:
        rows = build_ablation_rows(
            ROOT / "docs/evidence/spine_opt_v1_fallback_level_cache_20260728.json",
            ROOT / "docs/evidence/spine_opt_v2_reader_working_set_20260728.json",
        )
        self.assertEqual(len(rows), 5)
        self.assertAlmostEqual(rows[0]["speedup"], 2.5346389953)
        self.assertAlmostEqual(rows[-1]["speedup"], 6.7132185311)
        self.assertTrue(all(row["speedup"] > 1.0 for row in rows))

    def test_committed_hbm_sensitivity_evidence(self) -> None:
        evidence = ROOT / "docs/evidence/candidate10_hbm_sensitivity_v1_20260727"
        rows = build_sensitivity_rows(
            evidence / "sensitivity_details.csv",
            evidence / "sensitivity_summary.csv",
        )
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["profile_id"], "baseline")
        self.assertTrue(all(row["strict_rank_inversions"] == 0 for row in rows))
        self.assertTrue(all(row["spine_speedup_geomean"] > 1.0 for row in rows))


if __name__ == "__main__":
    unittest.main()
