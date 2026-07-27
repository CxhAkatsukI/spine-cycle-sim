from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.real_memory_analysis import (
    load_selected_matrix,
    normalize_system_row,
    normalize_physical_system_row,
    pair_memory_rows,
    paper_memory_rows,
    physical_pair_rows,
    physical_paper_rows,
    summarize_pairs,
)


def _group(prefix: str, requests: int, bytes_: int) -> dict[str, str]:
    first_requests = 1 if requests else 0
    first_bytes = 8 if bytes_ else 0
    classified_requests = requests - first_requests
    classified_bytes = bytes_ - first_bytes
    return {
        f"{prefix}_requests": str(requests),
        f"{prefix}_bytes": str(bytes_),
        f"{prefix}_nominal_64b_bytes": str(requests * 64),
        f"{prefix}_read_requests": str(requests),
        f"{prefix}_read_bytes": str(bytes_),
        f"{prefix}_write_requests": "0",
        f"{prefix}_write_bytes": "0",
        f"{prefix}_first_requests": str(first_requests),
        f"{prefix}_first_bytes": str(first_bytes),
        f"{prefix}_contiguous_requests": str(classified_requests),
        f"{prefix}_contiguous_bytes": str(classified_bytes),
        f"{prefix}_repeated_requests": "0",
        f"{prefix}_repeated_bytes": "0",
        f"{prefix}_discontinuous_requests": "0",
        f"{prefix}_discontinuous_bytes": "0",
        f"{prefix}_first_request_ratio": "0",
        f"{prefix}_first_byte_ratio": "0",
        f"{prefix}_contiguous_request_ratio": "1",
        f"{prefix}_contiguous_byte_ratio": "1",
        f"{prefix}_repeated_request_ratio": "0",
        f"{prefix}_repeated_byte_ratio": "0",
        f"{prefix}_discontinuous_request_ratio": "0",
        f"{prefix}_discontinuous_byte_ratio": "0",
    }


def _base(system: str) -> dict[str, str]:
    return {
        "run_id": "r",
        "dataset_id": "d",
        "scenario": "insert",
        "system": system,
        "e2e_ms": "2.0" if system == "spine" else "4.0",
    }


def _dram(requests: int) -> dict[str, int | float]:
    return {
        "channels": 2,
        "reads": requests - 1,
        "writes": 1,
        "read_row_hits": requests // 2,
        "write_row_hits": 0,
        "activates": requests // 3,
        "precharges": requests // 4,
        "requests": requests,
        "row_hit_rate": (requests // 2) / requests,
        "average_read_latency": 30.0,
        "average_write_latency": 28.0,
        "write_latency_coverage": 1.0,
        "total_energy_pj": 100.0,
    }


def _physical_row(system: str, *, aligned: bool = True) -> dict[str, str]:
    return {
        **_base(system),
        **_group("backend", 6, 96),
        **_group("update_backend", 2, 32),
        **_group("compute_backend", 4, 64),
        "e2e_cycles": "100",
        "axis_push_stalls": "2",
        "axi_issue_stalls": "3",
        "hbm_queue_stalls": "5",
        "hbm_response_queue_stalls": "7",
        "stall_metrics_complete": "True",
        "stall_metric_contract": "axis_axi_request_fifo_hbm_backend_v1",
        "dram_window_scope": (
            "update_plus_compute_active_channels"
            if aligned
            else "cold_plus_update_not_aligned"
        ),
    }


class RealMemoryAnalysisTests(unittest.TestCase):
    def test_physical_row_closes_controller_and_stall_ledgers(self) -> None:
        row = normalize_physical_system_row(
            "full_pagerank", _physical_row("spine"), _dram(6)
        )
        self.assertTrue(row["dram_physical_window_aligned"])
        self.assertEqual(row["physical_backend_requests"], 6)
        self.assertEqual(row["backend_nominal_64b_bytes"], 384)
        self.assertEqual(row["burst_amplification"], 4.0)
        self.assertEqual(row["hbm_queue_stalls_per_backend_request"], 5 / 6)

    def test_physical_row_rejects_legacy_backpressure(self) -> None:
        row = _physical_row("spine")
        row["axi_issue_stalls"] = ""
        row["stall_metrics_complete"] = "False"
        with self.assertRaisesRegex(ValueError, "backpressure contract"):
            normalize_physical_system_row("full_pagerank", row, _dram(6))

    def test_physical_paper_rows_exclude_unaligned_algorithm(self) -> None:
        rows: list[dict[str, object]] = []
        for system in ("spine", "grasu_regraph"):
            rows.append(
                normalize_physical_system_row(
                    "full_pagerank", _physical_row(system), _dram(6)
                )
            )
            weighted = {
                **_physical_row(system, aligned=system != "spine"),
                **_group("aligned_backend", 2, 32),
                "aligned_e2e_ms": "1.0",
                "aligned_e2e_cycles": "50",
                "cold_cycles": "50" if system == "spine" else "0",
            }
            rows.append(
                normalize_physical_system_row(
                    "weighted_sssp", weighted, _dram(6)
                )
            )
        pairs = physical_pair_rows(rows)
        self.assertFalse(
            next(row for row in pairs if row["algorithm"] == "weighted_sssp")[
                "physical_window_comparable"
            ]
        )
        paper = physical_paper_rows(rows)
        self.assertEqual([row["algorithm_id"] for row in paper], ["full_pagerank"])

    def test_weighted_cold_subtraction_uses_aligned_logical_window(self) -> None:
        weighted = {
            **_physical_row("spine", aligned=False),
            **_group("aligned_backend", 2, 32),
            "aligned_e2e_ms": "1.0",
            "aligned_e2e_cycles": "50",
            "cold_cycles": "50",
        }
        row = normalize_physical_system_row(
            "weighted_sssp",
            weighted,
            _dram(2),
            cold_subtracted=True,
            stall_overrides={
                "axis_push_stalls": 1,
                "axi_issue_stalls": 2,
                "hbm_queue_stalls": 3,
                "hbm_response_queue_stalls": 4,
            },
        )
        self.assertTrue(row["dram_physical_window_aligned"])
        self.assertEqual(row["physical_backend_requests"], 2)
        self.assertEqual(row["physical_window_cycles"], 50)
        self.assertEqual(row["hbm_queue_stalls"], 3)
        self.assertEqual(
            row["physical_window_derivation"],
            "quiescent_identical_cold_prefix_subtraction",
        )

    def test_pagerank_requires_closed_update_compute_phases(self) -> None:
        row = {
            **_base("spine"),
            **_group("backend", 6, 96),
            **_group("update_backend", 2, 32),
            **_group("compute_backend", 4, 64),
        }
        normalized = normalize_system_row("full_pagerank", row)
        self.assertEqual(normalized["bytes"], 96)
        self.assertEqual(normalized["phase_split"], "update_compute")
        row["compute_backend_bytes"] = "63"
        row["compute_backend_read_bytes"] = "63"
        row["compute_backend_contiguous_bytes"] = "55"
        with self.assertRaisesRegex(ValueError, "phase bytes"):
            normalize_system_row("full_pagerank", row)

    def test_weighted_spine_uses_aligned_window_without_fake_phase_split(self) -> None:
        row = {
            **_base("spine"),
            "aligned_e2e_ms": "3.0",
            **_group("aligned_backend", 3, 24),
        }
        normalized = normalize_system_row("weighted_sssp", row)
        self.assertEqual(normalized["phase_split"], "aligned_total_only")
        self.assertEqual(normalized["bytes"], 24)
        self.assertNotIn("update_bytes", normalized)

    def test_pair_and_summary_keep_time_volume_and_locality_separate(self) -> None:
        rows = []
        for system, requests, bytes_ in (
            ("spine", 4, 64),
            ("grasu_regraph", 8, 256),
        ):
            row = {
                **_base(system),
                **_group("backend", requests, bytes_),
                **_group("update_backend", requests // 2, bytes_ // 2),
                **_group("compute_backend", requests // 2, bytes_ // 2),
            }
            rows.append(normalize_system_row("full_pagerank", row))
        pairs = pair_memory_rows(rows)
        self.assertEqual(pairs[0]["spine_speedup_over_grasu"], 2.0)
        self.assertEqual(pairs[0]["grasu_to_spine_request_ratio"], 2.0)
        self.assertEqual(pairs[0]["grasu_to_spine_byte_ratio"], 4.0)
        summary = summarize_pairs(pairs)
        self.assertEqual(summary[0]["pairs"], 1)
        self.assertEqual(summary[0]["spine_e2e_wins"], 1)
        self.assertEqual(summary[0]["spine_requested_bytes"], 64)
        self.assertEqual(summary[0]["grasu_requested_bytes"], 256)
        self.assertEqual(summary[0]["spine_contiguous_byte_ratio_aggregate"], 1.0)
        self.assertEqual(summary[0]["grasu_discontinuous_byte_ratio_aggregate"], 0.0)

    def test_paper_rows_require_three_algorithms_and_average_bytes(self) -> None:
        summaries = []
        for algorithm in (
            "weighted_sssp",
            "full_pagerank",
            "thresholded_residual_pagerank",
        ):
            summaries.append(
                {
                    "algorithm": algorithm,
                    "pairs": 2,
                    "spine_requested_bytes": 200,
                    "grasu_requested_bytes": 400,
                    "spine_contiguous_byte_ratio_aggregate": 0.25,
                    "grasu_contiguous_byte_ratio_aggregate": 0.5,
                    "spine_discontinuous_byte_ratio_aggregate": 0.75,
                    "grasu_discontinuous_byte_ratio_aggregate": 0.5,
                }
            )
        rows = paper_memory_rows(summaries)
        self.assertEqual(rows[0]["algorithm"], "SSSP")
        self.assertEqual(rows[0]["spine_bytes"], 100.0)
        self.assertEqual(rows[0]["grasu_discontinuous"], 0.5)

    def _selected_matrix(self, directory: Path, algorithm: str) -> None:
        rows = []
        for system in ("spine", "grasu_regraph"):
            row = {
                **_base(system),
                "correctness_mismatches": "0",
                **_group("backend", 6, 96),
                **_group("update_backend", 2, 32),
                **_group("compute_backend", 4, 64),
            }
            rows.append(row)
        row_path = directory / "system_rows.csv"
        with row_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        correctness_key = {
            "weighted_sssp": "cross_system_distances_match",
            "full_pagerank": "cross_system_ranks_match",
            "thresholded_residual_pagerank": "cross_system_state_match",
        }[algorithm]
        pair_path = directory / "pairs.csv"
        with pair_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=("run_id", correctness_key), lineterminator="\n"
            )
            writer.writeheader()
            writer.writerow({"run_id": "r", correctness_key: "True"})
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        (directory / "matrix_manifest.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "all_correct": True,
                    "complete_matrix": False,
                    "system_rows_sha256": digest(row_path),
                    "pairs_sha256": digest(pair_path),
                }
            ),
            encoding="utf-8",
        )

    def test_selected_loader_accepts_exact_correct_incomplete_subset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._selected_matrix(directory, "full_pagerank")
            _, rows = load_selected_matrix("full_pagerank", directory, {"r"})
            self.assertEqual(len(rows), 2)

    def test_selected_loader_rejects_missing_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._selected_matrix(directory, "full_pagerank")
            with self.assertRaisesRegex(ValueError, "coverage mismatch"):
                load_selected_matrix("full_pagerank", directory, {"r", "missing"})

    def test_selected_loader_rejects_duplicate_system_row(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._selected_matrix(directory, "full_pagerank")
            row_path = directory / "system_rows.csv"
            lines = row_path.read_text(encoding="utf-8").splitlines()
            row_path.write_text("\n".join([*lines, lines[1]]) + "\n", encoding="utf-8")
            manifest_path = directory / "matrix_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["system_rows_sha256"] = hashlib.sha256(
                row_path.read_bytes()
            ).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate selected system row"):
                load_selected_matrix("full_pagerank", directory, {"r"})

    def test_selected_loader_rejects_cross_system_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self._selected_matrix(directory, "full_pagerank")
            pair_path = directory / "pairs.csv"
            pair_path.write_text(
                "run_id,cross_system_ranks_match\nr,False\n", encoding="utf-8"
            )
            manifest_path = directory / "matrix_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["pairs_sha256"] = hashlib.sha256(pair_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cross-system result mismatch"):
                load_selected_matrix("full_pagerank", directory, {"r"})


if __name__ == "__main__":
    unittest.main()
