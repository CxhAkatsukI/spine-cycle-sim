from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from scripts.render_delta_hls_residual_figure import render


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


if __name__ == "__main__":
    unittest.main()
