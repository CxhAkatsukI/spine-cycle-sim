from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.run_hls_pagerank_real_comparison import (
    PROFILE_SETS as TIMING_PROFILE_SETS,
)
from scripts.run_spine_dense_capacity_cliff import (
    PROFILE_SETS as CAPACITY_PROFILE_SETS,
)
from spine_cycle_sim.experiments.shared_workloads import sha256_file


ROOT = Path(__file__).resolve().parents[1]


class Candidate10DenseProfileSetTests(unittest.TestCase):
    def test_timing_and_capacity_runners_share_exact_profile_set(self) -> None:
        timing = TIMING_PROFILE_SETS["candidate10_hls_v3"]
        capacity = CAPACITY_PROFILE_SETS["candidate10_hls_v3"]
        self.assertEqual(timing, capacity)
        self.assertEqual(
            timing["spine_profile_id"], "spine_candidate10_normalized_v1"
        )
        self.assertEqual(
            timing["grasu_profile_id"],
            "grasu_regraph_candidate10_normalized_hls_pagerank_v3",
        )

    def test_candidate10_profile_is_hash_pinned_by_capability_catalog(self) -> None:
        profile_set = TIMING_PROFILE_SETS["candidate10_hls_v3"]
        profile_path = Path(profile_set["grasu_profile"])
        catalog = json.loads(
            Path(profile_set["capability_catalog"]).read_text(encoding="utf-8")
        )
        capability = next(
            item
            for item in catalog["profiles"]
            if item["profile_id"] == profile_set["grasu_profile_id"]
        )
        self.assertEqual(capability["profile_sha256"], sha256_file(profile_path))
        self.assertIn("full_pagerank", capability["supported_algorithms"])

    def test_legacy_profile_set_remains_the_default_contract(self) -> None:
        legacy = TIMING_PROFILE_SETS["legacy"]
        self.assertEqual(legacy["spine_profile_id"], "spine_shared_engine_9c08763")
        self.assertEqual(
            legacy["grasu_profile_id"],
            "grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67",
        )


if __name__ == "__main__":
    unittest.main()
