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
            "plus_calibrated_device_cycles"
        ),
        "sst_plugin_sha256": "plugin-v12",
        "case_contract_sha256": "cases-v7",
        "calibration_contract_sha256": "calibration-v8",
        "frozen_component_models": {"sha256": "frozen-models"},
    }


class Fig8UpdateOnlyExportTests(unittest.TestCase):
    def test_current_runner_defaults_follow_v12_freeze(self) -> None:
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_LIB_DIR,
            ROOT / "cpp/sst/build/sst-current-fpga-v12",
        )
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_CASE_CONTRACT,
            ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v7.json",
        )
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_CALIBRATION_CONTRACT,
            ROOT / "configs/contracts/evaluation_refresh_fpga_calibration_v8.json",
        )
        self.assertEqual(
            run_current_fig8_update_only_case.DEFAULT_FROZEN_MODELS,
            ROOT / "docs/evaluation_refresh_20260810/calibration_v12_frozen",
        )

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
            calibration_component="maintenance",
        )
        self.assertEqual(result["raw_device_cycles"], 101)
        self.assertEqual(result["calibrated_device_cycles"], 152)
        self.assertEqual(result["device_cycles"], 152)
        self.assertEqual(result["device_cycle_calibration_scale"], 1.5)

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
