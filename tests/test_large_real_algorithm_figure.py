from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.render_large_real_algorithm_figure import render


class LargeRealAlgorithmFigureTests(unittest.TestCase):
    def test_render_emits_all_algorithm_panels(self) -> None:
        pair = {"user_mutations": 8, "spine_speedup_over_grasu": 2.0}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.json"
            output = root / "figure.svg"
            summary.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "checks": {"correctness": True},
                        "weighted_sssp": {"pairs": [pair]},
                        "connected_components": {
                            "gate_pairs": [pair],
                            "full_pairs": [pair],
                        },
                        "residual_pagerank": {
                            "gate_pairs": [pair],
                            "full_pairs": [pair],
                        },
                    }
                ),
                encoding="utf-8",
            )
            render(summary, output)
            text = output.read_text(encoding="utf-8")
            self.assertIn("Weighted SSSP", text)
            self.assertIn("Connected Components", text)
            self.assertIn("Residual PageRank", text)
            self.assertIn("2.0x", text)

    def test_render_rejects_failed_evidence(self) -> None:
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
