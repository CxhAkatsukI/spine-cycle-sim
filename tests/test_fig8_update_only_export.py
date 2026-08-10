from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.render_evaluation_refresh import collect_fig8_rows


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


class Fig8UpdateOnlyExportTests(unittest.TestCase):
    def test_exporter_writes_renderer_ready_current_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence"
            write_json(
                evidence / "cross_dataset" / "au" / "comparison.json",
                comparison(4096, 10, 2.0),
            )
            write_json(
                evidence / "batch_sensitivity" / "b10" / "comparison.json",
                comparison(1024, 10, 3.0),
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
