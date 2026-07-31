from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.run_persistent_update_only import SPINE_MAX_VERTICES, _slice_vertices
from spine_cycle_sim.experiments.persistent_update_only import (
    HostRuntimeModel,
    analyze_persistent_update_pair,
)


def _result(cycles: int, mhz: float = 100.0) -> dict[str, object]:
    return {
        "measurement_window": "pure_update_only",
        "graph_compute_executed": False,
        "resident_state_persistent": True,
        "success": True,
        "correctness_mismatches": 0,
        "logical_updates": 100,
        "batch_count": 10,
        "device_cycles": cycles,
        "core_mhz": mhz,
        "backend_traffic": {"combined": {"requests": 20, "bytes": 1280}},
    }


class PersistentUpdateOnlyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.host = {
            "updates": 100,
            "batch_count": 10,
            "spine_host_preprocess_ns": 1_000_000,
            "grasu_host_preprocess_ns": 3_000_000,
            "spine_initial_h2d_bytes": 1000,
            "grasu_initial_h2d_bytes": 3000,
            "spine_update_h2d_bytes": 1000,
            "grasu_update_h2d_bytes": 1000,
        }

    def test_reports_all_three_timing_boundaries(self) -> None:
        analysis = analyze_persistent_update_pair(
            dataset_id="tiny",
            scenario="insert",
            host=self.host,
            spine_result=_result(200_000),
            grasu_result=_result(100_000),
            runtime=HostRuntimeModel(10.0, 5.0),
        )
        spine, grasu = analysis["rows"]
        self.assertAlmostEqual(spine["device_seconds"], 0.002)
        self.assertAlmostEqual(spine["preprocess_plus_device_seconds"], 0.003)
        self.assertGreater(spine["modeled_host_inclusive_seconds"], 0.003)
        self.assertAlmostEqual(analysis["spine_speedup"]["device_only"], 0.5)
        self.assertAlmostEqual(
            analysis["spine_speedup"]["preprocess_plus_device"], 4.0 / 3.0
        )
        self.assertEqual(grasu["backend_bytes"], 1280)

    def test_rejects_compute_or_incorrect_results(self) -> None:
        bad = _result(100)
        bad["graph_compute_executed"] = True
        with self.assertRaisesRegex(ValueError, "executed graph compute"):
            analyze_persistent_update_pair(
                dataset_id="tiny",
                scenario="insert",
                host=self.host,
                spine_result=bad,
                grasu_result=_result(100),
                runtime=HostRuntimeModel(10.0, 5.0),
            )

    def test_rejects_mismatched_trace_shapes(self) -> None:
        grasu = _result(100)
        grasu["logical_updates"] = 99
        with self.assertRaisesRegex(ValueError, "different trace shapes"):
            analyze_persistent_update_pair(
                dataset_id="tiny",
                scenario="insert",
                host=self.host,
                spine_result=_result(100),
                grasu_result=grasu,
                runtime=HostRuntimeModel(10.0, 5.0),
            )

    def test_large_graph_launcher_defaults_to_hls_partition_size(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (root / "sst/grasu_regraph_vertical.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'os.environ.get("GRASU_SST_PARTITION_VERTICES", "65536")', source
        )

    def test_campaign_runner_reads_and_enforces_frozen_vertex_bound(self) -> None:
        self.assertEqual(SPINE_MAX_VERTICES, 1 << 24)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "graph.slice"
            path.write_text("# vertices=17\n0 1 1 1\n", encoding="ascii")
            self.assertEqual(_slice_vertices(path), 17)

if __name__ == "__main__":
    unittest.main()
