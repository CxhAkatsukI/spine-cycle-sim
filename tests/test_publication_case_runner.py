from __future__ import annotations

import unittest
from pathlib import Path

from scripts.run_publication_case import (
    _canonical_profile_semantics,
    _final_state_identity,
    _publication_system_row,
    _replace_option,
    _verify_profile_evidence_amendment,
)
from spine_cycle_sim.experiments.publication_cases import (
    PublicationCase,
    architecture_profile_path,
    comparison_run,
)


class PublicationCaseRunnerTests(unittest.TestCase):
    def test_profile_semantics_exclude_only_evidence(self) -> None:
        first = {
            "profile_id": "p",
            "parameters": {"pipelines": 1},
            "evidence": [{"sha256": "old"}],
        }
        second = {
            "profile_id": "p",
            "parameters": {"pipelines": 1},
            "evidence": [{"sha256": "new"}],
        }
        self.assertEqual(
            _canonical_profile_semantics(first, ("evidence",)),
            _canonical_profile_semantics(second, ("evidence",)),
        )
        second["parameters"]["pipelines"] = 4
        self.assertNotEqual(
            _canonical_profile_semantics(first, ("evidence",)),
            _canonical_profile_semantics(second, ("evidence",)),
        )

    def test_frozen_profile_evidence_amendment_is_proven_from_git(self) -> None:
        root = Path(__file__).resolve().parents[1]
        audit = _verify_profile_evidence_amendment(
            root / "configs/contracts/profile_evidence_amendments_v1.json",
            profile_path=(
                root
                / "configs/architectures/"
                "grasu_regraph_candidate10_k1_multipart_weighted_fullgraph_v7.json"
            ),
            observed_sha256=(
                "25d95cabe45d98809ac0a267f64f26150ca623fd22ff1eb80b0212a0b09dd861"
            ),
            expected_sha256=(
                "8340355673f6d6be5153ba33616b7056c7dc497dafb3cb6f6176124720eee03c"
            ),
            repository_root=root,
        )
        self.assertEqual(
            audit["classification"],
            "evidence_only_no_architecture_semantic_change",
        )
        with self.assertRaises(ValueError):
            _verify_profile_evidence_amendment(
                root / "configs/contracts/profile_evidence_amendments_v1.json",
                profile_path=(
                    root
                    / "configs/architectures/"
                    "grasu_regraph_candidate10_k1_multipart_weighted_fullgraph_v7.json"
                ),
                observed_sha256="0" * 64,
                expected_sha256=audit["amended_sha256"],
                repository_root=root,
            )

    def test_weighted_scenarios_map_to_dynamic_execution(self) -> None:
        case = PublicationCase(
            dataset_id="tiny",
            system="spine",
            algorithm="weighted_sssp",
            scenario="weight_change",
            batch_size=8,
            graph={"case_id": "g", "path": "/g", "sha256": "a", "vertices": 4, "records": 3},
            update={"case_id": "u", "path": "/u", "sha256": "b", "vertices": 4, "records": 16},
            source=0,
            algorithm_parameters={"source_cohort": "default"},
            execution_id="execution",
        )
        run = comparison_run(case)
        self.assertEqual(run["algorithm"], "weighted_dynamic_sssp")
        self.assertEqual(run["scenario"], "full_rebuild_increase")

    def test_r19_is_labeled_as_a_synthetic_scalability_endpoint(self) -> None:
        case = PublicationCase(
            dataset_id="rmat_19_32",
            system="spine",
            algorithm="weighted_sssp",
            scenario="insert",
            batch_size=8,
            graph={
                "case_id": "g",
                "path": "/g",
                "sha256": "a",
                "vertices": 4,
                "records": 3,
            },
            update={
                "case_id": "u",
                "path": "/u",
                "sha256": "b",
                "vertices": 4,
                "records": 8,
            },
            source=0,
            algorithm_parameters={"source_cohort": "default"},
            execution_id="execution",
        )
        run = comparison_run(case)
        self.assertEqual(run["dataset_kind"], "synthetic")
        self.assertEqual(run["role"], "publication_scalability_endpoint")

    def test_final_state_hash_is_stable(self) -> None:
        first = _final_state_identity({"ranks": [0.25, 0.75]})
        second = _final_state_identity({"ranks": [0.25, 0.75]})
        self.assertEqual(first, second)
        self.assertEqual(first["count"], 2)

    def test_final_state_prefers_external_order_and_normalizes_infinity(self) -> None:
        first = _final_state_identity(
            {
                "distances_external": [0, 0x7FFFFFFE, 7],
                "distances_internal": [7, 0, 0x7FFFFFFE],
            },
            "weighted_sssp",
        )
        second = _final_state_identity(
            {"final_values": [0, 0xFFFFFFFF, 7]},
            "weighted_sssp",
        )
        self.assertEqual(first, second)
        external = _final_state_identity(
            {
                "ranks": [0.75, 0.25],
                "ranks_external": [0.25, 0.75],
            },
            "thresholded_residual_pagerank",
        )
        canonical = _final_state_identity(
            {"ranks": [0.25, 0.75]},
            "thresholded_residual_pagerank",
        )
        self.assertEqual(external, canonical)

    def test_dynamic_sssp_uses_post_update_digest_not_cold_baseline(self) -> None:
        identity = _final_state_identity(
            {
                "final_values_count": 3,
                "final_values_sha256": "a" * 64,
                "cold_final_values": [0, 85, 7],
            },
            "weighted_sssp",
        )
        self.assertEqual(identity["field"], "final_values")
        self.assertEqual(identity["sha256"], "a" * 64)

    def test_option_replacement_is_exact(self) -> None:
        self.assertEqual(
            _replace_option(("runner", "--max-cycles", "1"), "--max-cycles", "9"),
            ("runner", "--max-cycles", "9"),
        )
        with self.assertRaises(ValueError):
            _replace_option(("runner",), "--max-cycles", "9")

    def test_publication_row_preserves_model_and_formal_system_names(self) -> None:
        row = _publication_system_row(
            {"system": "grasu_regraph", "cycles": 10},
            "grasu_regraph_k4_shared",
        )
        self.assertEqual(row["system"], "grasu_regraph_k4_shared")
        self.assertEqual(row["model_system"], "grasu_regraph")

    def test_connected_components_profiles_are_selected_per_system(self) -> None:
        contract = {
            "architecture_baselines": {
                "spine": {"profile": "profiles/spine.json"},
                "grasu_regraph_k1": {
                    "profiles": {"connected_components": ["profiles/k1.json", "a"]}
                },
                "grasu_regraph_k4_shared": {
                    "profiles": {"connected_components": ["profiles/k4.json", "b"]}
                },
            }
        }
        root = Path("/tmp/publication-profile-test")
        self.assertEqual(
            architecture_profile_path(
                contract, "spine", "connected_components", root
            ),
            root / "profiles/spine.json",
        )
        self.assertEqual(
            architecture_profile_path(
                contract, "grasu_regraph_k1", "connected_components", root
            ),
            root / "profiles/k1.json",
        )
        self.assertEqual(
            architecture_profile_path(
                contract,
                "grasu_regraph_k4_shared",
                "connected_components",
                root,
            ),
            root / "profiles/k4.json",
        )


if __name__ == "__main__":
    unittest.main()
