from __future__ import annotations

import math
from pathlib import Path
import unittest

from scripts.run_sst_grasu_regraph_hls_pagerank import (
    DEFAULT_CAPABILITY_CATALOG,
    DEFAULT_PROFILE,
    full_pagerank_oracle,
    require_hls_pagerank_capability,
)
from scripts.run_sst_grasu_regraph_hls_weighted import build_hls_weighted_oracle
from spine_cycle_sim.experiments.shared_workloads import load_slice


ROOT = Path(__file__).resolve().parents[1]


class GraSuHlsPageRankRunnerTests(unittest.TestCase):
    def test_pinned_capability_is_executable_but_not_hardware_evidence(self) -> None:
        _catalog, capability = require_hls_pagerank_capability(
            DEFAULT_PROFILE.resolve(), DEFAULT_CAPABILITY_CATALOG.resolve()
        )
        self.assertEqual(capability.evidence_tier, "simulation_only")
        self.assertEqual(capability.convergence, "host_fixed_iterations")

    def test_external_oracle_uses_final_dynamic_graph(self) -> None:
        initial = load_slice(
            ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_initial.slice"
        )
        update = load_slice(
            ROOT / "tests" / "data" / "grasu_regraph_weighted_dynamic_update.slice"
        )
        prepared = build_hls_weighted_oracle(initial, update, 0)
        ranks = full_pagerank_oracle(
            initial.vertices, prepared.final_external_edges, 0.85, 3
        )
        self.assertEqual(len(ranks), initial.vertices)
        self.assertTrue(math.isclose(math.fsum(ranks), 1.0, abs_tol=1.0e-12))
        self.assertGreater(prepared.physical_updates, prepared.logical_updates)

    def test_dangling_mass_is_redistributed(self) -> None:
        ranks = full_pagerank_oracle(3, ((0, 1, 1),), 0.85, 2)
        self.assertTrue(math.isclose(math.fsum(ranks), 1.0, abs_tol=1.0e-12))
        self.assertGreater(ranks[1], ranks[0])

    def test_invalid_iteration_count_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid PageRank"):
            full_pagerank_oracle(3, ((0, 1, 1),), 0.85, 0)


if __name__ == "__main__":
    unittest.main()
