from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "configs"
    / "contracts"
    / "candidate10_normalized_architecture_freeze_v3.json"
)


class Candidate10NormalizedFreezeV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT.read_text(encoding="ascii"))

    def test_generator_is_reproducible(self) -> None:
        completed = subprocess.run(
            ["python3", "scripts/prepare_candidate10_normalized_freeze_v3.py"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_matrix_and_algorithms_are_frozen(self) -> None:
        matrix = self.contract["frozen_artifacts"]["experiment_matrix"]
        self.assertEqual(matrix["fixtures"], 23)
        self.assertEqual(matrix["run_cases"], 73)
        self.assertEqual(
            set(self.contract["algorithm_contracts"]),
            {
                "weighted_sssp",
                "full_pagerank",
                "thresholded_residual_pagerank",
            },
        )

    def test_every_prototype_difference_is_dispositioned(self) -> None:
        allowed = {
            "exact_configuration",
            "structurally_equivalent",
            "latest_hls_optimization",
            "feasibility_prototype_mismatch",
            "missing_feasibility_evidence",
        }
        crosswalk = self.contract["prototype_crosswalk"]
        self.assertGreaterEqual(len(crosswalk), 8)
        self.assertEqual(len({item["mechanism"] for item in crosswalk}), len(crosswalk))
        for item in crosswalk:
            self.assertIn(item["difference_class"], allowed)
            self.assertIsInstance(item["performance_sensitive"], bool)
            self.assertIsInstance(item["publication_blocker"], bool)
            self.assertTrue(item["disposition"])

    def test_matching_label_is_blocked_by_real_mismatches(self) -> None:
        blockers = [
            item
            for item in self.contract["prototype_crosswalk"]
            if item["publication_blocker"]
        ]
        self.assertGreaterEqual(len(blockers), 5)
        self.assertIn(
            "matching-HLS normalized label for PageRank",
            self.contract["claim_boundary"]["blocked_now"],
        )

    def test_frozen_profiles_are_hash_pinned(self) -> None:
        artifacts = self.contract["frozen_artifacts"]
        self.assertEqual(len(artifacts["spine_profile"]["sha256"]), 64)
        for artifact in artifacts["grasu_regraph_profiles"].values():
            self.assertEqual(len(artifact["sha256"]), 64)
            self.assertTrue(artifact["profile_id"].endswith("_v3"))

    def test_latest_hls_revision_and_sources_are_pinned(self) -> None:
        prototype = self.contract["latest_hls_prototype"]
        self.assertEqual(len(prototype["revision"]), 40)
        self.assertEqual(prototype["common_page_rank_cus"], 16)
        self.assertEqual(len(prototype["source_sha256"]), 11)
        self.assertEqual(prototype["bin_search_axi"]["masters_per_cu"], 2)
        self.assertEqual(
            prototype["hmss_master_budget"]["thresholded_residual_pagerank"],
            29,
        )
        self.assertTrue(
            all(len(value) == 64 for value in prototype["source_sha256"].values())
        )
        repository = Path(prototype["repository"])
        revision_is_ancestor = subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                prototype["revision"],
                "HEAD",
            ],
            cwd=repository,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(
            revision_is_ancestor.returncode,
            0,
            "pinned HLS revision is not an ancestor of the current checkout: "
            + revision_is_ancestor.stdout,
        )
        for relative, expected in prototype["source_sha256"].items():
            source = subprocess.check_output(
                ["git", "show", f"{prototype['revision']}:{relative}"],
                cwd=repository,
            )
            actual = hashlib.sha256(source).hexdigest()
            self.assertEqual(actual, expected, relative)


if __name__ == "__main__":
    unittest.main()
