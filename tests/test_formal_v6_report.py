from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.render_formal_v6_primary import publication_dataset_scope


class FormalV6ReportTests(unittest.TestCase):
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
