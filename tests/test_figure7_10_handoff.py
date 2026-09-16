from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "docs/evaluation_refresh_20260810/figure7_10_handoff_v1/render_all.py"
)


def load_renderer():
    spec = importlib.util.spec_from_file_location("figure7_10_handoff", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Figure 7--10 handoff renderer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FigureSevenToTenHandoffTests(unittest.TestCase):
    def test_frozen_inputs_pass_all_gates(self) -> None:
        rows = load_renderer().validate_inputs()
        self.assertEqual(len(rows["fig7"]), 27)
        self.assertEqual(len(rows["fig8_cross"]), 5)
        self.assertEqual(len(rows["fig8_batch"]), 3)
        self.assertEqual(len(rows["fig9"]), 9)
        self.assertEqual(len(rows["fig10"]), 11)
        self.assertEqual(len(rows["fig11_prediction"]), 41)
        self.assertEqual(len(rows["fig11_metric"]), 3)

    def test_handoff_is_self_contained(self) -> None:
        package = SCRIPT.parent
        required = (
            package / "README.md",
            package / "requirements.txt",
            package / "reference/GraphyFlow_Plot.zip",
            package / "data/fig7_fpga_speedup.csv",
            package / "data/fig8_update_cross_dataset.csv",
            package / "data/fig8_update_batch_sensitivity.csv",
            package / "data/fig9_memory_energy_rows.csv",
            package / "data/fig10_normalized_breakdown_rows.csv",
            package / "data/fig11_rq3_prediction_rows.csv",
            package / "data/fig11_rq3_metric_rows.csv",
            package / "data/fig11_rq3_model.json",
            package / "data/fig11_rq3_summary.json",
            package / "figures/fig11_realized_work_model.pdf",
            package / "figures/fig11_realized_work_model.png",
        )
        self.assertTrue(all(path.is_file() for path in required))

    def test_generated_outputs_match_package_manifest(self) -> None:
        module = load_renderer()
        package = SCRIPT.parent
        manifest = json.loads((package / "manifest.json").read_text(encoding="ascii"))
        self.assertEqual(manifest["status"], "PASS_COMPLETE_FIGURE_7_11_HANDOFF")
        for relative_path, expected_hash in manifest["outputs"].items():
            self.assertEqual(module.sha256(package / relative_path), expected_hash)


if __name__ == "__main__":
    unittest.main()
