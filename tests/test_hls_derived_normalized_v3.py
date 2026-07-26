from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.run_sst_grasu_regraph_hls_weighted import (
    build_hls_weighted_oracle,
)
from spine_cycle_sim.experiments import (
    build_invocation,
    load_capability_catalog,
    normalized_grasu_capability_catalog_path,
    normalized_grasu_profile_paths,
    normalized_profile_set,
    validate_normalized_profile_contract,
    validate_shared_comparison_manifest,
)
from spine_cycle_sim.experiments.feasibility import (
    load_normalized_hls_feasibility,
    require_claim_eligibility,
    FeasibilityError,
)
from spine_cycle_sim.experiments.shared_workloads import load_slice


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    ROOT
    / "configs"
    / "experiments"
    / "shared_comparison_candidate10_hls_v3_20260726.json"
)
SPINE_PROFILE = (
    ROOT / "configs" / "architectures" / "spine_candidate10_normalized_v1.json"
)
FEASIBILITY = (
    ROOT
    / "configs"
    / "contracts"
    / "candidate10_normalized_hls_feasibility_v2.json"
)


class HlsDerivedNormalizedV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = validate_shared_comparison_manifest(ROOT, MANIFEST_PATH)
        cls.profile_set = normalized_profile_set(cls.manifest)
        cls.profiles = normalized_grasu_profile_paths(ROOT, cls.profile_set)
        cls.catalog_path = normalized_grasu_capability_catalog_path(
            ROOT, cls.profile_set
        )

    def test_generator_is_reproducible(self) -> None:
        completed = subprocess.run(
            ["python3", "scripts/prepare_hls_derived_normalized_v3.py"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("profiles=3 runs=73 fixtures=23", completed.stdout)

    def test_profiles_preserve_hls_microarchitecture(self) -> None:
        self.assertEqual(self.profile_set, "hls_v3")
        contract = validate_normalized_profile_contract(
            SPINE_PROFILE, self.profiles
        )
        self.assertEqual(contract["grasu_profile_set"], "hls_v3")
        self.assertEqual(
            contract["claim_class"],
            "candidate10_hls_derived_normalized_structural_execution_driven",
        )
        for path in self.profiles:
            profile = json.loads(path.read_text(encoding="ascii"))
            self.assertEqual(profile["memory"]["max_outstanding_per_port"], 16)
            self.assertEqual(profile["parameters"]["regraph_map_reduce_lanes"], 8)
            self.assertEqual(
                profile["parameters"]["grasu_pma_edge_abi"],
                "regraph_weighted32_full_word_compare_dst19_weight12",
            )
        for path in self.profiles[1:]:
            profile = json.loads(path.read_text(encoding="ascii"))
            self.assertTrue(
                profile["parameters"]["pagerank_degree_update_timing"]
            )

    def test_capabilities_cover_all_three_algorithms(self) -> None:
        catalog = load_capability_catalog(self.catalog_path)
        catalog.profile(self.profiles[0].stem).require("weighted_sssp")
        catalog.profile(self.profiles[0].stem).require("weighted_dynamic_sssp")
        catalog.profile(self.profiles[1].stem).require("full_pagerank")
        catalog.profile(self.profiles[2].stem).require(
            "thresholded_residual_pagerank"
        )

    def test_shared_invocations_use_hls_derived_drivers(self) -> None:
        cases = {
            run["algorithm"]: run
            for run in self.manifest["runs"]
            if run["fixture_id"] == "syn_weighted_diamond_v8"
            and run["algorithm"]
            in {
                "weighted_sssp",
                "full_pagerank",
                "thresholded_residual_pagerank",
            }
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            for algorithm, script in {
                "weighted_sssp": "run_sst_grasu_regraph_hls_weighted.py",
                "full_pagerank": "run_sst_grasu_regraph_hls_pagerank.py",
                "thresholded_residual_pagerank": (
                    "run_sst_grasu_regraph_hls_residual_pagerank.py"
                ),
            }.items():
                invocation = build_invocation(
                    ROOT,
                    cases[algorithm],
                    system="grasu_regraph",
                    output_root=Path(temporary),
                    python="python3",
                    sst=Path("/data/feiyang/sst/bin/sst"),
                    lib_dir=ROOT / "build" / "sst",
                    spine_profile=SPINE_PROFILE,
                    grasu_profile_paths=self.profiles,
                    grasu_capability_catalog=self.catalog_path,
                )
                self.assertTrue(invocation.command[1].endswith(script))
                self.assertIn("--capability-catalog", invocation.command)
                self.assertIn("--update-workload", invocation.command)

    def test_oracle_selects_minimum_fixed_supersteps(self) -> None:
        run = next(
            run
            for run in self.manifest["runs"]
            if run["run_id"] == "syn_chain_v64__weighted_sssp"
        )
        initial = load_slice(ROOT / run["graph"]["path"])
        update = load_slice(ROOT / run["update"]["path"])
        oracle = build_hls_weighted_oracle(initial, update, 0)
        self.assertEqual(oracle.minimum_supersteps, 63)

    def test_headline_gate_remains_blocked_for_missing_whole_system_hls(self) -> None:
        feasibility = load_normalized_hls_feasibility(ROOT, FEASIBILITY)
        self.assertEqual(feasibility["grasu_matching_hls_algorithms"], 0)
        self.assertFalse(feasibility["all_matching_hls"])
        require_claim_eligibility(feasibility, "structural_exploratory")
        with self.assertRaisesRegex(FeasibilityError, "matching whole-system"):
            require_claim_eligibility(
                feasibility, "headline_normalized_performance"
            )


if __name__ == "__main__":
    unittest.main()
