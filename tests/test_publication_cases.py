from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.publication_cases import (
    deduplicate_publication_cases,
    load_materialization_manifest,
    select_publication_case,
)


def artifact(name: str, records: int = 10) -> dict[str, object]:
    return {
        "case_id": name,
        "path": f"/tmp/{name}.slice",
        "sha256": hashlib.sha256(name.encode("ascii")).hexdigest(),
        "vertices": 64,
        "records": records,
    }


class PublicationCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        directed = {
            **artifact("directed", 100),
            "source_cohorts": {
                "default": 7,
                "high_degree": 7,
                "median_degree": 3,
                "random_reachable": 11,
            },
        }
        residual = {
            **artifact("residual", 120),
            "sink_vertices_after_projection": 0,
        }
        pagerank = {
            **artifact("pagerank", 50),
            "requested_edges": 4_000_000,
            "actual_edges": 50,
        }
        bounded_weighted = {
            **artifact("bounded_weighted", 50),
            "requested_edges": 64_000,
            "actual_edges": 50,
            "source_cohorts": {
                "default": 13,
                "high_degree": 13,
                "median_degree": 5,
                "random_reachable": 17,
            },
        }
        updates = []
        for projection in (
            "directed",
            "reciprocal",
            "residual_sink_free",
            "full_pagerank_e4000000",
        ):
            updates.append(
                {
                    **artifact(f"{projection}_insert", 8),
                    "projection": projection,
                    "scenario": "insert",
                    "user_mutations": 8,
                    "physical_records": 16 if projection == "reciprocal" else 8,
                }
            )
        self.manifest = {
            "schema_version": 1,
            "status": "pass",
            "dataset_id": "tiny",
            "graphs": {
                "directed": directed,
                "reciprocal": artifact("reciprocal", 180),
                "residual_sink_free": residual,
            },
            "full_pagerank_slices": [bounded_weighted, pagerank],
            "updates": updates,
        }
        self.manifest["updates"].append(
            {
                **artifact("full_pagerank_e64000_delete", 8),
                "projection": "full_pagerank_e64000",
                "scenario": "delete",
                "user_mutations": 8,
                "physical_records": 8,
            }
        )

    def test_algorithm_projection_and_source_selection(self) -> None:
        weighted = select_publication_case(
            self.manifest,
            system="spine",
            algorithm="weighted_sssp",
            scenario="insert",
            batch_size=8,
        )
        self.assertEqual(weighted.source, 7)
        self.assertEqual(weighted.update["projection"], "directed")
        pagerank = select_publication_case(
            self.manifest,
            system="grasu_regraph_k4_shared",
            algorithm="full_pagerank",
            scenario="insert",
            batch_size=8,
        )
        self.assertEqual(pagerank.graph["case_id"], "pagerank")
        self.assertEqual(pagerank.update["projection"], "full_pagerank_e4000000")
        residual = select_publication_case(
            self.manifest,
            system="grasu_regraph_k1",
            algorithm="thresholded_residual_pagerank",
            scenario="insert",
            batch_size=8,
        )
        self.assertEqual(
            residual.algorithm_parameters["residual_contract"],
            "deltahls_sink_free_linf_warm",
        )

    def test_nonmonotonic_sssp_uses_bounded_real_topology_slice(self) -> None:
        cases = [
            select_publication_case(
                self.manifest,
                system=system,
                algorithm="weighted_sssp",
                scenario="delete",
                batch_size=8,
            )
            for system in ("spine", "grasu_regraph_k4_shared")
        ]
        self.assertEqual(cases[0].graph, cases[1].graph)
        self.assertEqual(cases[0].update, cases[1].update)
        self.assertEqual(cases[0].graph["case_id"], "bounded_weighted")
        self.assertEqual(cases[0].source, 13)
        self.assertEqual(
            cases[0].algorithm_parameters["graph_scope"],
            "bounded_real_topology_nonmonotonic_fallback",
        )

    def test_nonmonotonic_sssp_cap_cannot_exceed_hardware_contract(self) -> None:
        with self.assertRaisesRegex(ValueError, "MAX_SORT_EDGES=131072"):
            select_publication_case(
                self.manifest,
                system="spine",
                algorithm="weighted_sssp",
                scenario="delete",
                batch_size=8,
                nonmonotonic_sssp_edge_cap=131_073,
            )

    def test_identical_tier_views_share_one_execution(self) -> None:
        case = select_publication_case(
            self.manifest,
            system="spine",
            algorithm="weighted_sssp",
            scenario="insert",
            batch_size=8,
        )
        unique, views = deduplicate_publication_cases(
            [("main_e2e", case), ("update_performance", case)]
        )
        self.assertEqual(len(unique), 1)
        self.assertEqual(
            views[case.execution_id], ["main_e2e", "update_performance"]
        )

    def test_manifest_loader_requires_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(self.manifest), encoding="ascii")
            self.assertEqual(load_materialization_manifest(path)["dataset_id"], "tiny")
            self.manifest["status"] = "fail"
            path.write_text(json.dumps(self.manifest), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "not passing"):
                load_materialization_manifest(path)


if __name__ == "__main__":
    unittest.main()
