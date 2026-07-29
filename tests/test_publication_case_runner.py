from __future__ import annotations

import unittest
from pathlib import Path

from scripts.run_publication_case import _final_state_identity, _replace_option
from spine_cycle_sim.experiments.publication_cases import (
    PublicationCase,
    architecture_profile_path,
    comparison_run,
)


class PublicationCaseRunnerTests(unittest.TestCase):
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

    def test_option_replacement_is_exact(self) -> None:
        self.assertEqual(
            _replace_option(("runner", "--max-cycles", "1"), "--max-cycles", "9"),
            ("runner", "--max-cycles", "9"),
        )
        with self.assertRaises(ValueError):
            _replace_option(("runner",), "--max-cycles", "9")

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
