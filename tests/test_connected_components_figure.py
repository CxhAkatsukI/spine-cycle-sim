from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.render_connected_components_figure import render


class ConnectedComponentsFigureTests(unittest.TestCase):
    def test_render_emits_screening_and_scalability_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.json"
            output = root / "figure.svg"
            summary.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "checks": {"correctness": True},
                        "screening_pairs": [
                            {"user_mutations": 1, "spine_speedup_over_grasu": 2.0},
                            {
                                "user_mutations": 4096,
                                "spine_speedup_over_grasu": 0.5,
                            },
                        ],
                        "scalability_metrics": {
                            "k1_to_direct_k4_speedup": 3.8,
                            "k1_to_shared_k4_speedup": 3.7,
                        },
                        "scalability_rows": [
                            {"cycles": 2_000_000},
                            {"cycles": 20_000_000},
                            {"cycles": 5_000_000},
                            {"cycles": 5_250_000},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            render(summary, output)
            text = output.read_text(encoding="utf-8")
            self.assertIn("2.00x", text)
            self.assertIn("0.50x", text)
            self.assertIn("20.00M", text)

    def test_render_rejects_failed_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.json"
            summary.write_text(
                json.dumps({"status": "PASS", "checks": {"correctness": False}}),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                render(summary, root / "figure.svg")


if __name__ == "__main__":
    unittest.main()
