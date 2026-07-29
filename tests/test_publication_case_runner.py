from __future__ import annotations

import unittest

from scripts.run_publication_case import _final_state_identity, _replace_option
from spine_cycle_sim.experiments.publication_cases import (
    PublicationCase,
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


if __name__ == "__main__":
    unittest.main()
