from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs/contracts/simulator_throughput_r19_v1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SimulatorThroughputContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_frozen_tracked_inputs_have_expected_hashes(self) -> None:
        baseline = self.contract["baseline"]
        expected = {
            baseline["hbm_config"]["path"]: baseline["hbm_config"]["sha256"],
            baseline["fresh_probe"]["manifest_path"]: baseline["fresh_probe"][
                "manifest_sha256"
            ],
            baseline["historical_real_topology_runtime"]["path"]: baseline[
                "historical_real_topology_runtime"
            ]["sha256"],
            baseline["historical_real_topology_runtime"]["raw_archive_path"]: baseline[
                "historical_real_topology_runtime"
            ]["raw_archive_sha256"],
        }
        for relative, digest in expected.items():
            with self.subTest(path=relative):
                self.assertEqual(sha256(ROOT / relative), digest)

    def test_acceptance_and_coverage_are_not_weakened(self) -> None:
        acceptance = self.contract["acceptance"]
        self.assertGreaterEqual(
            acceptance["medium_large_wall_speedup_geomean_min"], 10.0
        )
        self.assertLessEqual(
            acceptance["non_tiny_wall_regression_max_fraction"], 0.05
        )
        self.assertEqual(
            set(self.contract["architecture_freeze"]["systems"]),
            {"spine", "grasu_regraph"},
        )
        self.assertEqual(
            set(self.contract["architecture_freeze"]["algorithms"]),
            {
                "weighted_sssp",
                "connected_components",
                "full_pagerank",
                "thresholded_residual_pagerank",
            },
        )
        self.assertEqual(
            len(self.contract["coverage"]["primary_real_temporal_datasets"]), 5
        )
        self.assertEqual(
            self.contract["coverage"]["scale_endpoint"]["dataset_id"],
            "rmat_19_32",
        )

    def test_only_host_observables_may_change(self) -> None:
        allowed = set(self.contract["equivalence_gate"]["allowed_to_change"])
        self.assertEqual(
            allowed,
            {
                "host_wall_seconds",
                "host_cycles_per_second",
                "host_peak_rss_bytes",
                "host_profiler_samples",
            },
        )
        self.assertIn(
            "dramsim3_commands_statistics_and_energy",
            self.contract["equivalence_gate"]["exact"],
        )


if __name__ == "__main__":
    unittest.main()
