from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="ascii")


class DeriveUpdateOnlyManifestTests(unittest.TestCase):
    def test_adds_lowest_sink_only_source_absent_from_insert_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            graph = root / "graph.keys"
            graph.write_text(
                "# vertices=5\n0000000000 0000000001\n0000000002 0000000003\n",
                encoding="ascii",
            )
            update = root / "insert.keys"
            update.write_text("# update\n0000000001 0000000002 1 1\n", encoding="ascii")
            manifest = root / "materialization_manifest.json"
            output = root / "derived.json"
            write_json(
                manifest,
                {
                    "schema_version": 1,
                    "status": "pass",
                    "graphs": {
                        "directed": {
                            "path": str(graph),
                            "vertices": 5,
                            "source_cohorts": {"default": 0},
                        }
                    },
                    "updates": [
                        {
                            "projection": "directed",
                            "scenario": "insert",
                            "path": str(update),
                        }
                    ],
                },
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "derive_update_only_manifest.py"),
                    "--input",
                    str(manifest),
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )

            derived = json.loads(output.read_text(encoding="ascii"))

        self.assertIn("DERIVED_UPDATE_ONLY_MANIFEST source=3", completed.stdout)
        self.assertEqual(derived["graphs"]["directed"]["source_cohorts"]["default"], 0)
        self.assertEqual(derived["graphs"]["directed"]["source_cohorts"]["update_only"], 3)
        self.assertEqual(
            derived["derived_metadata"]["update_only_source_derivation"]["method"],
            "lowest_sink_only_vertex_absent_from_directed_insert_sources",
        )


if __name__ == "__main__":
    unittest.main()
