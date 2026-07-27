from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.summarize_grasu_k_pipeline_sensitivity import (
    CONSERVATION_FIELDS,
    load_run,
    summarize,
)


def make_run(k: int, cycles: int, requests: int = 100) -> dict[str, object]:
    return {
        "algorithm": "weighted_sssp",
        "compute_pipelines": k,
        "cycles": cycles,
        "max_parallel_partitions": min(k, 2),
        "identity": {
            "workload_sha256": "workload",
            "update_workload_sha256": "update",
            "sst_plugin_sha256": "plugin",
        },
        "conservation": {
            "destination_partitions": 2,
            "partition_passes": 2,
            "backend_requests": requests,
        },
    }


class GraSuKPipelineSensitivityTests(unittest.TestCase):
    def test_summary_requires_conserved_work(self) -> None:
        summary = summarize(
            [make_run(1, 200), make_run(2, 110), make_run(4, 110)]
        )
        weighted = summary["algorithms"]["weighted_sssp"]
        self.assertEqual(weighted["work_conservation"], "PASS")
        self.assertAlmostEqual(
            weighted["runs"]["2"]["speedup_over_k1"], 200 / 110
        )

    def test_summary_rejects_missing_k(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly K=1,2,4"):
            summarize([make_run(1, 200), make_run(2, 110)])

    def test_summary_rejects_request_drift(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not conserve work"):
            summarize(
                [make_run(1, 200), make_run(2, 110, 99), make_run(4, 110)]
            )

    def test_summary_rejects_plugin_drift(self) -> None:
        k2 = make_run(2, 110)
        k2["identity"] = {**k2["identity"], "sst_plugin_sha256": "other"}
        with self.assertRaisesRegex(ValueError, "different run inputs"):
            summarize([make_run(1, 200), k2, make_run(4, 110)])

    def test_summary_rejects_cycle_regression(self) -> None:
        with self.assertRaisesRegex(ValueError, "cycles increase"):
            summarize(
                [make_run(1, 200), make_run(2, 210), make_run(4, 110)]
            )

    def test_loader_rejects_missing_conservation_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result = {
                **{field: 1 for field in CONSERVATION_FIELDS},
                "success": True,
                "compute_pipelines": 1,
                "destination_partitions": 2,
                "max_parallel_partitions": 1,
                "memory_locality_ledger_match": True,
                "backend_arbitration": {"ledger_closed": True},
                "cycles": 200,
                "compute_cycles": 190,
                "update_cycles": 10,
            }
            del result["compute_row_reads"]
            manifest = {
                "workload_sha256": "workload",
                "update_workload_sha256": "update",
                "sst_plugin_sha256": "plugin",
            }
            (directory / "result.json").write_text(
                json.dumps(result), encoding="utf-8"
            )
            (directory / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "compute_row_reads"):
                load_run("weighted_sssp", 1, directory)


if __name__ == "__main__":
    unittest.main()
