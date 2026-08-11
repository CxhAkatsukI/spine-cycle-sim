import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_current_fpga_calibration import analyze_total
from scripts.analyze_current_fpga_components import analyze_component_records
from spine_cycle_sim.calibration.current_fpga import (
    CurrentFPGAComponentRecord,
    CurrentFPGATimingRecord,
    PositiveScaleModel,
)
from spine_cycle_sim.calibration.frozen import load_frozen_scale_models


class CurrentFPGAFrozenModelTests(unittest.TestCase):
    def write_bundle(self, root: Path, *, holdout_used: bool = False) -> None:
        models = {
            "schema_version": 1,
            "status": "FROZEN_BEFORE_HOLDOUT",
            "contract_id": "c",
            "contract_sha256": "contract",
            "cases_sha256": "cases",
            "plugin_sha256": "plugin",
            "models": [
                {
                    "architecture": "spine",
                    "algorithm": "weighted_sssp",
                    "profile_id": "p",
                    "component": None,
                    "scale": 2.0,
                    "calibration_datasets": ["au", "su"],
                    "fit_role": "calibration_only",
                    "holdout_used_for_fit": holdout_used,
                }
            ],
        }
        models_path = root / "frozen_total_models.json"
        models_path.write_text(json.dumps(models), encoding="utf-8")
        manifest = {
            "status": "FROZEN_BEFORE_HOLDOUT",
            "contract_id": "c",
            "contract_sha256": "contract",
            "cases_sha256": "cases",
            "plugin_sha256": "plugin",
            "holdout_result_files_present_at_freeze": [],
            "frozen_total_models": str(models_path.resolve()),
            "frozen_total_models_sha256": hashlib.sha256(
                models_path.read_bytes()
            ).hexdigest(),
        }
        (root / "calibration_freeze_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    def load(self, root: Path):
        return load_frozen_scale_models(
            root,
            kind="total",
            contract_id="c",
            contract_sha256="contract",
            cases_sha256="cases",
            plugin_sha256="plugin",
        )

    def test_loads_exact_frozen_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_bundle(root)
            models, provenance = self.load(root)
            self.assertEqual(models[("spine", "weighted_sssp", "p")].scale, 2.0)
            self.assertTrue(provenance["models_sha256"])

    def test_rejects_model_file_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_bundle(root)
            path = root / "frozen_total_models.json"
            path.write_text(path.read_text() + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "model hash mismatch"):
                self.load(root)

    def test_rejects_holdout_fit_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_bundle(root, holdout_used=True)
            with self.assertRaisesRegex(ValueError, "non-calibration"):
                self.load(root)

    def test_total_holdout_evaluation_uses_supplied_frozen_scale(self) -> None:
        key = ("spine", "weighted_sssp", "p")
        model = PositiveScaleModel("spine", "weighted_sssp", None, 2.0, ("au", "su"))
        rows = [
            CurrentFPGATimingRecord(*key, "au", "calibration", 10, 20),
            CurrentFPGATimingRecord(*key, "su", "calibration", 20, 40),
            CurrentFPGATimingRecord(*key, "wk", "holdout", 30, 6000),
            CurrentFPGATimingRecord(*key, "r19", "holdout", 40, 8000),
        ]
        predictions, _summaries, models = analyze_total(rows, {key: model})
        self.assertEqual(models[0]["scale"], 2.0)
        self.assertEqual(
            [row["predicted_cycles"] for row in predictions if row["role"] == "holdout"],
            [80.0, 60.0],
        )

    def test_component_holdout_evaluation_uses_supplied_frozen_scale(self) -> None:
        key = ("spine", "weighted_sssp", "p", "reader")
        model = PositiveScaleModel("spine", "weighted_sssp", "reader", 3.0, ("au", "su"))
        observation = "routed reader"
        rows = [
            CurrentFPGAComponentRecord(*key[:3], "au", "calibration", key[3], 10, 30, observation),
            CurrentFPGAComponentRecord(*key[:3], "su", "calibration", key[3], 20, 60, observation),
            CurrentFPGAComponentRecord(*key[:3], "wk", "holdout", key[3], 30, 9000, observation),
        ]
        predictions, _summaries, models = analyze_component_records(
            rows, 20.0, {key: model}
        )
        self.assertEqual(models[0]["scale"], 3.0)
        self.assertEqual(
            [row["predicted_cycles"] for row in predictions if row["role"] == "holdout"],
            [90.0],
        )


if __name__ == "__main__":
    unittest.main()
