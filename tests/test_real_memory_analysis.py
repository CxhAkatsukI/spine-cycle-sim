from __future__ import annotations

import unittest

from spine_cycle_sim.experiments.real_memory_analysis import (
    normalize_system_row,
    pair_memory_rows,
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


class RealMemoryAnalysisTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
