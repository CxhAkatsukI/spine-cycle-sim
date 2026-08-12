from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.render_evaluation_refresh import collect_fig8_rows
from scripts import run_current_fig8_update_only_case
from scripts.run_current_fig8_update_only_case import pure_result
from scripts.run_current_fig8_update_only_case import (
    validate_grasu_holdout,
    validate_spine_maintenance_holdout,
)


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def comparison(updates: int, batches: int, speedup: float) -> dict[str, object]:
    return {
        "experiment": "persistent_trace_aware_update_only",
        "correctness": "pass",
        "logical_updates": updates,
        "batch_count": batches,
        "rows": [
            {
                "system": "spine",
                "modeled_host_inclusive_updates_per_second": 20_000.0,
            },
            {
                "system": "grasu_regraph",
                "modeled_host_inclusive_updates_per_second": 10_000.0,
            },
        ],
        "spine_speedup": {
            "modeled_host_inclusive": speedup,
        },
    }


def current_case_manifest() -> dict[str, object]:
    return {
        "status": "PASS",
        "timing_boundary": (
            "measured_host_preprocessing_plus_explicit_transfer_launch_model_"
            "plus_frozen_calibrated_persistent_device_cycles"
        ),
        "spine_sst_plugin_sha256": "spine-plugin-v12",
        "grasu_sst_plugin_sha256": "grasu-plugin-v19",
        "case_contract_sha256": "cases-v7",
        "spine_calibration_contract_sha256": "spine-calibration-v15",
        "grasu_calibration_contract_sha256": "grasu-calibration-v20",
        "spine_frozen_mechanism_model_sha256": "spine-v15",
        "grasu_frozen_persistent_update_model_sha256": "grasu-v20",
        "spine_holdout_analysis_sha256": "spine-holdout-v15",
        "grasu_holdout_analysis_sha256": "grasu-holdout-v20",
    }


class Fig8UpdateOnlyExportTests(unittest.TestCase):
    def test_current_runner_defaults_follow_split_v15_v20_freeze(self) -> None:
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_SPINE_LIB_DIR,
            ROOT / "cpp/sst/build/sst-current-fpga-v12",
        )
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_GRASU_LIB_DIR,
            ROOT / "cpp/sst/build/sst-current-fpga-v19",
        )
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_CASE_CONTRACT,
            ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v7.json",
        )
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_SPINE_CALIBRATION_CONTRACT,
            ROOT
            / "configs/contracts/current_fpga_spine_mechanism_components_v15.json",
        )
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_GRASU_CALIBRATION_CONTRACT,
            ROOT
            / "configs/contracts/current_fpga_grasu_persistent_update_v20.json",
        )
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_GRASU_FROZEN_MODEL,
            ROOT
            / "docs/evaluation_refresh_20260810/"
            "calibration_v20_grasu_persistent_update_frozen/frozen_model.json",
        )
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_SPINE_FROZEN_MODEL,
            ROOT
            / "docs/evaluation_refresh_20260810/calibration_v15_frozen"
            / "frozen_spine_mechanism_component_models.json",
        )

    def test_spine_component_admission_does_not_require_whole_machine_pass(self) -> None:
        contract = {
            "thresholds": {
                "holdout_component_median_absolute_error_percent_max": 20.0,
                "holdout_component_absolute_error_percent_max": 40.0,
            }
        }
        analysis = {
            "status": "FAIL",
            "holdout_used_for_fit": False,
            "gate_results": {"memory_ledger": "PASS", "structural_work": "PASS"},
            "holdout_component_summary": [
                {
                    "algorithm": "weighted_sssp",
                    "component": "maintenance",
                    "role": "holdout",
                    "cases": 2,
                    "median_absolute_error_percent": 9.2,
                    "max_absolute_error_percent": 16.2,
                }
            ],
        }
        row = validate_spine_maintenance_holdout(
            analysis, contract, "weighted_sssp"
        )
        self.assertEqual(row["component"], "maintenance")

    def test_grasu_holdout_requires_pass_without_refit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contract = root / "contract.json"
            model = root / "model.json"
            contract.write_text("{}\n", encoding="ascii")
            model.write_text("{}\n", encoding="ascii")
            good = {
                "status": "PASS",
                "model_refit": False,
                "contract_sha256": run_current_fig8_update_only_case.sha256_file(
                    contract
                ),
                "frozen_model_sha256": run_current_fig8_update_only_case.sha256_file(
                    model
                ),
            }
            validate_grasu_holdout(good, contract, model)
            with self.assertRaisesRegex(ValueError, "did not pass"):
                validate_grasu_holdout(dict(good, status="FAIL"), contract, model)

    def test_current_case_preserves_raw_and_applies_frozen_component_scale(self) -> None:
        result = pure_result(
            {
                "success": True,
                "core_mhz": 150.0,
                "maintenance_cycles": 101,
                "correctness_mismatches": 0,
                "backend_traffic": {"combined": {"requests": 1, "bytes": 64}},
            },
            system="spine",
            updates=8,
            calibration_scale=1.5,
            calibration_fixed_cycles=10.0,
            calibration_component="maintenance",
        )
        self.assertEqual(result["raw_device_cycles"], 101)
        self.assertEqual(result["calibrated_device_cycles"], 162)
        self.assertEqual(result["device_cycles"], 162)
        self.assertEqual(result["device_cycle_calibration_scale"], 1.5)
        self.assertEqual(result["device_cycle_calibration_fixed_cycles"], 10.0)

    def test_current_case_applies_additive_shard_envelope(self) -> None:
        result = pure_result(
            {
                "success": True,
                "core_mhz": 150.0,
                "update_cycles": 101,
                "correctness_mismatches": 0,
                "backend_traffic": {"combined": {"requests": 1, "bytes": 64}},
            },
            system="grasu",
            updates=8,
            calibration_scale=1.0,
            calibration_additive_cycles=30_000.0,
            calibration_component="persistent_shard_envelope",
        )
        self.assertEqual(result["raw_device_cycles"], 101)
        self.assertEqual(result["calibrated_device_cycles"], 30_101)
        self.assertEqual(result["device_cycle_calibration_additive_cycles"], 30_000.0)

    def test_exporter_writes_renderer_ready_current_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            write_json(
                evidence / "cross_dataset" / "au" / "comparison.json",
                comparison(4096, 10, 2.0),
            )
            write_json(
                evidence / "cross_dataset" / "au" / "manifest.json",
                current_case_manifest(),
            )
            write_json(
                evidence / "batch_sensitivity" / "b10" / "comparison.json",
                comparison(1024, 10, 3.0),
            )
            write_json(
                evidence / "batch_sensitivity" / "b10" / "manifest.json",
                current_case_manifest(),
            )
            out = root / "out"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "export_persistent_update_setup_fig8.py"),
                    "--evidence-root",
                    str(evidence),
                    "--out-dir",
                    str(out),
                    "--cross-dataset",
                    "au:AU",
                    "--batch-count",
                    "10",
                    "--status",
                    "PASS_CURRENT_MODEL_DATA",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )

            cross, batch, sources, status = collect_fig8_rows(out)

            self.assertEqual(status, "PASS_CURRENT_MODEL_DATA")
            self.assertEqual(cross[0]["dataset"], "AU")
            self.assertEqual(float(batch[0]["spine_speedup"]), 3.0)
            self.assertEqual(float(batch[0]["updates_per_batch"]), 102.4)
            self.assertEqual(len(sources), 3)

    def test_current_pass_rejects_missing_case_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            write_json(
                evidence / "cross_dataset" / "au" / "comparison.json",
                comparison(8, 1, 2.0),
            )
            write_json(
                evidence / "batch_sensitivity" / "b8" / "comparison.json",
                comparison(8, 1, 2.0),
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "export_persistent_update_setup_fig8.py"),
                    "--evidence-root",
                    str(evidence),
                    "--out-dir",
                    str(root / "out"),
                    "--cross-dataset",
                    "au:AU",
                    "--batch-count",
                    "8",
                    "--status",
                    "PASS_CURRENT_MODEL_DATA",
                ],
                cwd=ROOT,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("case manifest is missing", completed.stderr)

    def test_renderer_rejects_noncurrent_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out = root / "out"
            out.mkdir()
            for filename in (
                "persistent_update_setup_cross_dataset.csv",
                "persistent_update_setup_batch_sensitivity.csv",
            ):
                with (out / filename).open("w", encoding="ascii", newline="") as sink:
                    writer = csv.DictWriter(
                        sink,
                        fieldnames=[
                            "dataset",
                            "logical_updates",
                            "batch_count",
                            "spine_kups",
                            "grasu_kups",
                            "spine_speedup",
                        ],
                    )
                    writer.writeheader()
            write_json(
                out / "persistent_update_setup_manifest.json",
                {
                    "status": "INTERIM_ARCHIVED_SIMULATOR_DATA",
                    "metric": "setup_inclusive_update_only_throughput",
                },
            )

            with self.assertRaisesRegex(ValueError, "PASS_CURRENT_MODEL_DATA"):
                collect_fig8_rows(out)


if __name__ == "__main__":
    unittest.main()
