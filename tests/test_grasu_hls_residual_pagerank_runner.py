from __future__ import annotations

from pathlib import Path
import unittest

from scripts.run_sst_grasu_regraph_hls_residual_pagerank import (
    DEFAULT_CAPABILITY_CATALOG,
    DEFAULT_PROFILE,
    require_hls_residual_capability,
)
from scripts.run_sst_grasu_regraph_hls_pagerank import full_pagerank_oracle
from scripts.run_sst_grasu_regraph_hls_weighted import build_hls_weighted_oracle
from spine_cycle_sim.experiments.shared_workloads import load_slice


ROOT = Path(__file__).resolve().parents[1]


class GraSuHlsResidualPageRankRunnerTests(unittest.TestCase):
    def test_pinned_capability_is_thresholded_and_simulation_only(self) -> None:
        _catalog, capability = require_hls_residual_capability(
            DEFAULT_PROFILE.resolve(), DEFAULT_CAPABILITY_CATALOG.resolve()
        )
        self.assertEqual(capability.evidence_tier, "simulation_only")
        self.assertEqual(
            capability.convergence,
            "signed_residual_threshold_or_iteration_limit",
        )

    def test_mathematical_oracle_uses_final_external_graph(self) -> None:
        initial = load_slice(
            ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_initial.slice"
        )
        update = load_slice(
            ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_update.slice"
        )
        prepared = build_hls_weighted_oracle(initial, update, 0)
        ranks = full_pagerank_oracle(
            initial.vertices, prepared.final_external_edges, 0.85, 200
        )
        self.assertEqual(len(ranks), initial.vertices)
        self.assertAlmostEqual(sum(ranks), 1.0, places=12)
        self.assertGreater(prepared.physical_updates, prepared.logical_updates)


if __name__ == "__main__":
    unittest.main()
