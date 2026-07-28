from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from scripts.render_delta_hls_residual_figure import render, render_scalability


class DeltaHlsResidualFigureTests(unittest.TestCase):
    def test_render_requires_correctness_and_emits_svg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            screening = root / "screening.json"
            sensitivity = root / "sensitivity.json"
            output = root / "figure.svg"
            screening.write_text(
                json.dumps(
                    {
                        "all_correct": True,
                        "pairs": [
                            {
                                "user_mutations": 1,
                                "spine_speedup_over_grasu": 2.0,
                            },
                            {
                                "user_mutations": 8,
                                "spine_speedup_over_grasu": 3.0,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            sensitivity.write_text(
                json.dumps(
                    {
                        "all_correct": True,
                        "pairs": [
                            {"epsilon": 1e-7, "spine_speedup_over_grasu": 2.5},
                            {"epsilon": 1e-6, "spine_speedup_over_grasu": 3.0},
                            {"epsilon": 1e-5, "spine_speedup_over_grasu": 1.2},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            render(screening, sensitivity, output)
            svg = ET.parse(output).getroot()
            self.assertTrue(svg.tag.endswith("svg"))
            text = output.read_text(encoding="utf-8")
            self.assertIn("3.00x", text)
            self.assertIn("values above 1 favor Spine", text)

    def test_render_rejects_failed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failed = root / "failed.json"
            passed = root / "passed.json"
            failed.write_text(
                json.dumps({"all_correct": False, "pairs": []}), encoding="utf-8"
            )
            passed.write_text(
                json.dumps({"all_correct": True, "pairs": []}), encoding="utf-8"
            )
            with self.assertRaises(ValueError):
                render(failed, passed, root / "figure.svg")

    def test_render_scalability_emits_cycle_bars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "summary.json"
            output = root / "scalability.svg"
            summary.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "checks": {"work": True, "requests": True},
                        "metrics": {
                            "k1_to_direct_k4_speedup": 3.2,
                            "k1_to_shared_k4_speedup": 3.1,
                            "shared_k4_penalty_over_direct": 1.025,
                        },
                        "rows": [
                            {"cycles": 1_000_000},
                            {"cycles": 16_000_000},
                            {"cycles": 5_000_000},
                            {"cycles": 5_125_000},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            render_scalability(summary, output)
            text = output.read_text(encoding="utf-8")
            self.assertIn("16.00M", text)
            self.assertIn("shared penalty: 2.50%", text)


if __name__ == "__main__":
    unittest.main()
