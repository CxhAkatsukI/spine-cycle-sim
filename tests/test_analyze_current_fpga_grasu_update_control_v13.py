import json
from pathlib import Path
import tempfile
import unittest

from scripts.analyze_current_fpga_grasu_update_control_v13 import (
    load_model,
    summarize,
    validate_contract,
)


class AnalyzeCurrentFpgaGrasuUpdateControlV13Tests(unittest.TestCase):
    def test_load_model_requires_frozen_pre_holdout_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.json"
            path.write_text(
                json.dumps({"status": "DRAFT", "models": []}), encoding="ascii"
            )
            with self.assertRaisesRegex(ValueError, "not frozen"):
                load_model(path)

    def test_load_model_preserves_algorithm_specific_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "FROZEN_BEFORE_HOLDOUT",
                        "models": [
                            {
                                "algorithm": "weighted_sssp",
                                "profile_id": "p1",
                                "calibration_datasets": ["au", "su"],
                                "control_cycles_per_nonempty_shard": 123.0,
                            }
                        ],
                    }
                ),
                encoding="ascii",
            )
            model = load_model(path)["weighted_sssp"]
            self.assertEqual(model.calibration_datasets, ("au", "su"))
            self.assertEqual(model.control_cycles_per_nonempty_shard, 123.0)

    def test_load_model_accepts_diagnostic_replay_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "FROZEN_BEFORE_DIAGNOSTIC_REPLAY",
                        "models": [],
                    }
                ),
                encoding="ascii",
            )
            self.assertEqual(load_model(path), {})

    def test_summary_keeps_holdout_error_visible(self) -> None:
        rows = [
            {
                "algorithm": "weighted_sssp",
                "role": "holdout",
                "absolute_error_percent": 5.0,
            },
            {
                "algorithm": "weighted_sssp",
                "role": "holdout",
                "absolute_error_percent": 55.0,
            },
        ]
        summary = summarize(rows)
        self.assertEqual(summary[0]["median_absolute_error_percent"], 30.0)
        self.assertEqual(summary[0]["max_absolute_error_percent"], 55.0)

    def test_current_contract_is_explicitly_not_independent_holdout(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / "configs/contracts/current_fpga_grasu_update_control_v15.json"
        contract = json.loads(path.read_text(encoding="ascii"))
        validate_contract(path, contract)
        self.assertFalse(contract["evidence_boundary"]["holdout_is_independent"])
        self.assertFalse(contract["model"]["holdout_may_fit"])
        self.assertEqual(
            contract["evidence_boundary"]["next_untouched_transfer_datasets"],
            ["lj", "lj08"],
        )


if __name__ == "__main__":
    unittest.main()
