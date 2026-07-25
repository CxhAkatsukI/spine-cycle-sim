from __future__ import annotations

import csv
import json
import math
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.comparison_analysis import (
    aggregate_dram_stats,
    analyze_completed_matrix,
    build_pair_details,
    classify_phase_bottleneck,
    geometric_mean,
    group_summaries,
    sha256_file,
)


class SharedComparisonAnalysisTests(unittest.TestCase):
    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _write_read_only_dram(path: Path, reads: int, energy: float) -> None:
        path.parent.mkdir(parents=True)
        row = {
            "num_reads_done": reads,
            "num_writes_done": 0,
            "num_read_row_hits": reads // 2,
            "num_write_row_hits": 0,
            "num_act_cmds": reads // 2,
            "num_pre_cmds": reads // 2,
            "total_energy": energy,
            "average_read_latency": 20.0,
            "write_latency": None,
        }
        path.write_text(json.dumps({"channel_0": row}), encoding="utf-8")

    def test_geometric_mean_and_invalid_samples(self) -> None:
        self.assertAlmostEqual(geometric_mean([2.0, 8.0]), 4.0)
        for values in ([], [0.0], [math.inf], [math.nan]):
            with self.assertRaises(ValueError):
                geometric_mean(values)

    def test_phase_bottleneck_boundaries(self) -> None:
        self.assertEqual(
            classify_phase_bottleneck(55, 100), "structure_update_dominant"
        )
        self.assertEqual(classify_phase_bottleneck(45, 100), "compute_dominant")
        self.assertEqual(classify_phase_bottleneck(50, 100), "balanced")
        with self.assertRaises(ValueError):
            classify_phase_bottleneck(101, 100)

    def test_raw_dramsim_aggregation_is_request_weighted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [
                {
                    "num_reads_done": 3,
                    "num_writes_done": 1,
                    "num_read_row_hits": 2,
                    "num_write_row_hits": 1,
                    "num_act_cmds": 2,
                    "num_pre_cmds": 1,
                    "total_energy": 8.0,
                    "average_read_latency": 10.0,
                    "write_latency": {"20": 1},
                },
                {
                    "num_reads_done": 1,
                    "num_writes_done": 3,
                    "num_read_row_hits": 0,
                    "num_write_row_hits": 1,
                    "num_act_cmds": 4,
                    "num_pre_cmds": 3,
                    "total_energy": 12.0,
                    "average_read_latency": 30.0,
                    "write_latency": {"40": 3},
                },
            ]
            for channel, row in enumerate(rows):
                directory = root / f"channel{channel}"
                directory.mkdir()
                (directory / "dramsim3.json").write_text(
                    json.dumps({f"channel_{channel}": row}), encoding="utf-8"
                )
            result = aggregate_dram_stats(root)
        self.assertEqual(result["channels"], 2)
        self.assertEqual(result["requests"], 8)
        self.assertEqual(result["row_hit_rate"], 0.5)
        self.assertEqual(result["average_read_latency"], 15.0)
        self.assertEqual(result["average_write_latency"], 35.0)
        self.assertEqual(result["write_latency_coverage"], 1.0)
        self.assertEqual(result["total_energy_pj"], 20.0)

    def test_missing_write_histogram_is_reported_as_zero_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "channel0"
            directory.mkdir()
            row = {
                "num_reads_done": 0,
                "num_writes_done": 2,
                "num_read_row_hits": 0,
                "num_write_row_hits": 0,
                "num_act_cmds": 1,
                "num_pre_cmds": 1,
                "total_energy": 4.0,
                "average_read_latency": 0.0,
                "write_latency": None,
            }
            (directory / "dramsim3.json").write_text(
                json.dumps({"channel_0": row}), encoding="utf-8"
            )
            result = aggregate_dram_stats(Path(temporary))
        self.assertEqual(result["average_write_latency"], 0.0)
        self.assertEqual(result["write_latency_coverage"], 0.0)

    def test_pair_and_group_summary_preserve_claim_boundaries(self) -> None:
        common = {
            "run_id": "case",
            "fixture_id": "fixture",
            "dataset_kind": "synthetic",
            "role": "holdout",
            "algorithm": "weighted_sssp",
            "dram_row_hit_rate": 0.5,
            "phase_bottleneck": "compute_dominant",
        }
        pairs = build_pair_details(
            [
                {
                    **common,
                    "system": "spine",
                    "cycles": 100,
                    "backend_requests": 10,
                    "active_channel_dram_energy_pj": 5.0,
                },
                {
                    **common,
                    "system": "grasu_regraph",
                    "cycles": 250,
                    "backend_requests": 40,
                    "active_channel_dram_energy_pj": 20.0,
                },
            ]
        )
        self.assertEqual(pairs[0]["spine_speedup_over_grasu"], 2.5)
        self.assertEqual(pairs[0]["spine_request_advantage"], 4.0)
        self.assertEqual(pairs[0]["spine_active_dram_energy_advantage"], 4.0)
        summary = group_summaries(pairs)[0]
        self.assertEqual(summary["spine_wins"], 1)
        self.assertEqual(
            summary["energy_claim"], "sparse_active_channel_dramsim3_only"
        )

    def test_complete_matrix_analysis_checks_raw_evidence_and_writes_outputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matrix_dir = root / "matrix"
            analysis_dir = root / "analysis"
            matrix_dir.mkdir()
            source_manifest = root / "workloads.json"
            source_manifest.write_text(
                json.dumps({"runs": [{"run_id": "case"}]}), encoding="utf-8"
            )
            rows = []
            specifications = (
                ("spine", 100, 10, 20, 5.0),
                ("grasu_regraph", 250, 40, 1, 20.0),
            )
            for system, cycles, requests, phase_cycles, energy in specifications:
                run_dir = matrix_dir / "case" / system
                result = {
                    "correctness_mismatches": 0,
                    "architecture_correctness_mismatches": 0,
                    "mathematical_correctness_mismatches": 0,
                    "backend_submit_stalls": 0,
                    "backend_response_queue_stalls": 0,
                }
                run_dir.mkdir(parents=True)
                if system == "spine":
                    result["maintenance_cycles"] = phase_cycles
                    result["edge_axis_push_stalls"] = 0
                    (run_dir / "summary.json").write_text(
                        json.dumps(result), encoding="utf-8"
                    )
                else:
                    result["update_cycles"] = phase_cycles
                    result["axis_push_stalls"] = 0
                    (run_dir / "manifest.json").write_text(
                        json.dumps({"result": result}), encoding="utf-8"
                    )
                self._write_read_only_dram(
                    run_dir / "dram" / "channel0" / "dramsim3.json",
                    requests,
                    energy,
                )
                rows.append(
                    {
                        "run_id": "case",
                        "fixture_id": "fixture",
                        "dataset_kind": "synthetic",
                        "role": "holdout",
                        "algorithm": "weighted_sssp",
                        "system": system,
                        "claim_class": "normalized_simulation",
                        "cycles": cycles,
                        "simulated_ms": cycles / 150_000.0,
                        "backend_requests": requests,
                        "bound_dram_channels": 1,
                    }
                )
            self._write_csv(matrix_dir / "results.csv", rows)
            self._write_csv(
                matrix_dir / "pairs.csv",
                [{"run_id": "case", "spine_speedup_over_grasu": 2.5}],
            )
            (matrix_dir / "comparison_manifest.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "complete_matrix": True,
                        "failure": None,
                        "source_manifest": str(source_manifest),
                        "source_manifest_sha256": sha256_file(source_manifest),
                        "simulation_implementation": {"sha256": "simulation"},
                        "orchestration_implementation": {
                            "sha256": "orchestration"
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = analyze_completed_matrix(matrix_dir, analysis_dir)
            for output_name in result["outputs"]:
                self.assertNotIn(
                    b"\r",
                    (analysis_dir / output_name).read_bytes(),
                    f"{output_name} must use reproducible LF line endings",
                )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["system_rows"], 2)
        self.assertEqual(result["pairs"], 1)
        self.assertEqual(result["group_summary"][0]["speedup_geomean"], 2.5)
        self.assertEqual(len(result["outputs"]), 4)


if __name__ == "__main__":
    unittest.main()
