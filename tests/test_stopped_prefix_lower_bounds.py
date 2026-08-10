from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect_stopped_prefix_lower_bounds.py"
SPEC = importlib.util.spec_from_file_location("stopped_prefix_bounds", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StoppedPrefixLowerBoundsTest(unittest.TestCase):
    def test_collects_only_certified_stopped_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = root / "system_rows.csv"
            with rows.open("w", encoding="ascii", newline="") as stream:
                writer = csv.DictWriter(
                    stream,
                    fieldnames=(
                        "execution_id",
                        "dataset_id",
                        "algorithm",
                        "system",
                        "scenario",
                        "batch_size",
                        "cycles",
                    ),
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "execution_id": "spine",
                        "dataset_id": "graph",
                        "algorithm": "connected_components",
                        "system": "spine",
                        "scenario": "insert",
                        "batch_size": 8,
                        "cycles": 100,
                    }
                )
            state = root / "state.json"
            state.write_text(
                json.dumps(
                    {
                        "campaign_id": "campaign",
                        "manifest_sha256": "abc",
                        "jobs": [
                            {
                                "status": "stopped",
                                "system": "grasu_regraph_k4_shared",
                                "dataset_id": "graph",
                                "algorithm": "connected_components",
                                "job_id": "job",
                                "elapsed_seconds": 10,
                                "peak_rss_bytes": 20,
                                "reason": "threshold reached",
                                "progress": {
                                    "status": "running",
                                    "simulated_cycles": 10_100,
                                    "backend_requests": 30,
                                },
                            }
                        ],
                    }
                ),
                encoding="ascii",
            )
            evidence = MODULE.collect_lower_bounds([state], rows)
        bound = evidence["lower_bounds"][0]
        self.assertEqual(bound["certified_threshold"], 100.0)
        self.assertEqual(bound["strict_lower_bound_ratio"], 101.0)
        self.assertFalse(bound["admitted_as_completed_performance"])


if __name__ == "__main__":
    unittest.main()
