from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.temporal_dense_analysis import _dense_paper_rows


class TemporalDenseAnalysisTest(unittest.TestCase):
    def test_dense_rows_preserve_topologies_and_geomean(self) -> None:
        abbreviations = {"a": "AU", "w": "WK", "b": "BC"}
        pairs = [
            {
                "dataset_id": dataset,
                "user_mutations": batch,
                "spine_speedup_over_grasu_e2e": speedup,
                "spine_e2e_ms": 4.0,
                "grasu_e2e_ms": 4.0 * speedup,
            }
            for batch in (64, 512, 4096)
            for dataset, speedup in (("a", 0.5), ("w", 1.0), ("b", 2.0))
        ]
        rows = _dense_paper_rows(pairs, abbreviations)
        self.assertEqual([row["batch"] for row in rows], [64, 512, 4096])
        self.assertAlmostEqual(rows[0]["geomean_speedup"], 1.0)
        self.assertEqual(rows[-1]["update_ratio"], 0.5)

        with self.assertRaisesRegex(ValueError, "lacks three topology pairs"):
            _dense_paper_rows(pairs[:-1], abbreviations)
