from __future__ import annotations

import unittest

from scripts.analyze_delta_hls_residual_scalability import analyze_payloads


def _payload(
    architecture: str,
    pipelines: int,
    sharing: str,
    parallel: int,
    downstream: int,
    cycles: int,
) -> dict[str, object]:
    return {
        "all_correct": True,
        "input_manifest_sha256": "input",
        "sst_plugin_sha256": "plugin",
        "grasu_profile_sha256": "k4" if pipelines == 4 else "k1",
        "runs": [
            {
                "run_id": "p4",
                "architecture": architecture,
                "epsilon": 1e-6,
                "damping": 0.85,
                "vertices": 262144,
                "initial_edges": 262144,
                "user_mutations": 4,
                "physical_records": 8,
                "iterations": 1,
                "active_edges": 24,
                "residual_linf": 5e-7,
                "compute_pipelines": pipelines,
                "downstream_sharing": sharing,
                "max_parallel_partitions": parallel,
                "max_parallel_downstream_partitions": downstream,
                "cycles": cycles,
                "time_us": cycles / 150.0,
                "backend_requests": 100,
                "backend_bytes": 1000,
            }
        ],
    }


class DeltaHlsResidualScalabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payloads = {
            "spine": _payload("spine", 1, "spine_native", 1, 1, 100),
            "k1": _payload("grasu_regraph", 1, "direct", 1, 1, 1600),
            "direct_k4": _payload(
                "grasu_regraph", 4, "direct", 4, 4, 500
            ),
            "shared_k4": _payload(
                "grasu_regraph", 4, "shared", 4, 1, 520
            ),
        }

    def test_analysis_reports_scaling_and_shared_penalty(self) -> None:
        analysis = analyze_payloads(self.payloads)
        self.assertEqual(analysis["status"], "PASS")
        self.assertAlmostEqual(
            analysis["metrics"]["k1_to_direct_k4_speedup"], 3.2
        )
        self.assertAlmostEqual(
            analysis["metrics"]["shared_k4_penalty_over_direct"], 1.04
        )

    def test_analysis_rejects_changed_memory_work(self) -> None:
        self.payloads["shared_k4"]["runs"][0]["backend_bytes"] = 999  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "conservation"):
            analyze_payloads(self.payloads)


if __name__ == "__main__":
    unittest.main()
