from __future__ import annotations

import json
import math
from pathlib import Path
import unittest

from scripts.run_sst_grasu_regraph_hls_pagerank import (
    DEFAULT_CAPABILITY_CATALOG,
    DEFAULT_PROFILE,
    expected_source_cache_ledger,
    full_pagerank_oracle,
    require_hls_pagerank_capability,
)
from scripts.run_sst_grasu_regraph_hls_weighted import (
    HlsWeightedOracle,
    build_hls_weighted_oracle,
)
from spine_cycle_sim.experiments.shared_workloads import load_slice


ROOT = Path(__file__).resolve().parents[1]
MULTIPART_PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_candidate10_k2_multipart_pagerank_packed_v5.json"
)


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

    def test_sparse_multipart_source_cache_ledger_tracks_window_gaps(self) -> None:
        profile = json.loads(MULTIPART_PROFILE.read_text(encoding="utf-8"))
        vertices = 65_537
        oracle = HlsWeightedOracle(
            logical_updates=0,
            physical_updates=0,
            external_to_internal=tuple(range(vertices)),
            internal_to_external=tuple(range(vertices)),
            final_external_edges=((0, 1, 1), (12_288, 2, 1), (8_192, 65_536, 1)),
            final_internal_edges=((0, 1, 1), (12_288, 2, 1), (8_192, 65_536, 1)),
            external_distances=(),
            source_internal=0,
            minimum_supersteps=1,
        )
        requests, lines, lane_writes = expected_source_cache_ledger(
            profile, oracle
        )
        self.assertEqual(requests, 24)
        self.assertEqual(lines, 6_144)
        self.assertEqual(lane_writes, 49_152)


if __name__ == "__main__":
    unittest.main()
