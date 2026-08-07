from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.run_hls_pagerank_real_comparison import PROFILE_SETS as PAGERANK_SETS
from scripts.run_hls_residual_pagerank_real_comparison import (
    PROFILE_SETS as RESIDUAL_SETS,
)
from scripts.run_hls_weighted_real_comparison import PROFILE_SETS as WEIGHTED_SETS
from scripts.run_hls_weighted_real_comparison import _display_path
from spine_cycle_sim.experiments.shared_workloads import sha256_file


ROOT = Path(__file__).resolve().parents[1]


class RealComparisonProfileSetTests(unittest.TestCase):
    def test_weighted_evidence_path_supports_external_output_roots(self) -> None:
        self.assertEqual(_display_path(ROOT / "results"), "results")
        self.assertEqual(_display_path(Path("/data/tmp/evidence")), "/data/tmp/evidence")

    def test_all_runners_expose_candidate10_hls_v3(self) -> None:
        for profile_sets in (WEIGHTED_SETS, PAGERANK_SETS, RESIDUAL_SETS):
            with self.subTest(profile_sets=profile_sets):
                self.assertEqual(set(profile_sets), {"legacy", "candidate10_hls_v3"})

    def test_candidate10_profile_and_capability_hashes_close(self) -> None:
        for profile_sets in (WEIGHTED_SETS, PAGERANK_SETS, RESIDUAL_SETS):
            profile_set = profile_sets["candidate10_hls_v3"]
            spine_path = Path(profile_set["spine_profile"])
            grasu_path = Path(profile_set["grasu_profile"])
            capability_path = Path(profile_set["capability_catalog"])
            spine = json.loads(spine_path.read_text(encoding="utf-8"))
            grasu = json.loads(grasu_path.read_text(encoding="utf-8"))
            capabilities = json.loads(capability_path.read_text(encoding="utf-8"))
            with self.subTest(grasu_profile=grasu["profile_id"]):
                self.assertEqual(spine["profile_id"], profile_set["spine_profile_id"])
                self.assertEqual(grasu["profile_id"], profile_set["grasu_profile_id"])
                capability = next(
                    row
                    for row in capabilities["profiles"]
                    if row["profile_id"] == grasu["profile_id"]
                )
                self.assertEqual(capability["profile_sha256"], sha256_file(grasu_path))


if __name__ == "__main__":
    unittest.main()
