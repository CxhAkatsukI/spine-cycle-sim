from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.render_formal_v6_primary import admitted_pairs, publication_dataset_scope


class FormalV6ReportTests(unittest.TestCase):
    def test_r19_pair_is_retained_as_separate_endpoint(self) -> None:
        row = {
            "competitor": "grasu_regraph_k4_shared",
            "scenario": "insert",
            "batch_size": "8",
            "algorithm": "weighted_sssp",
            "dataset_id": "rmat_19_32",
            "spine_cycles": "100",
            "competitor_cycles": "250",
            "spine_speedup": "2.5",
            "spine_memory_bytes": "64",
            "competitor_memory_bytes": "128",
            "spine_random_request_fraction": "0.5",
            "competitor_random_request_fraction": "0.25",
            "spine_dram_energy_pj": "10",
            "competitor_dram_energy_pj": "20",
        }
        pairs = admitted_pairs([row])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["dataset"], "R19")
        self.assertEqual(pairs[0]["label"], "R19-SSSP")

    def test_dataset_scope_is_derived_from_materialization_capacity(self) -> None:
        contract = {
            "datasets": [
                {"dataset_id": "small", "abbreviation": "SM"},
                {"dataset_id": "large", "abbreviation": "LG"},
            ]
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for dataset_id, vertices, admitted in (
                ("small", 10, True),
                ("large", 200, False),
            ):
                directory = root / dataset_id
                directory.mkdir()
                (directory / "materialization_manifest.json").write_text(
                    json.dumps(
                        {
                            "dataset_id": dataset_id,
                            "capacity": {
                                "vertices": vertices,
                                "spine_max_vertices": 128,
                                "spine_full_graph_admitted": admitted,
                            },
                        }
                    ),
                    encoding="ascii",
                )
            scope = publication_dataset_scope(contract, root)

        self.assertEqual(scope["catalog_datasets"], 2)
        self.assertEqual(scope["admitted_datasets"], 1)
        self.assertEqual(scope["spine_max_vertices"], 128)
        self.assertFalse(scope["rows"][1]["spine_full_graph_admitted"])


if __name__ == "__main__":
    unittest.main()
