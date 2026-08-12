from pathlib import Path
import unittest

from scripts.run_current_fpga_grasu_update_observability_v13 import (
    build_command,
    output_directory,
    valid_result,
    workload_paths,
)


class CurrentFpgaGrasuUpdateObservabilityV13Tests(unittest.TestCase):
    def test_roles_have_physically_separate_outputs(self) -> None:
        root = Path("/tmp/evidence")
        self.assertEqual(
            output_directory(root, "calibration", "au", "weighted_sssp"),
            root / "calibration/au/weighted_sssp",
        )
        self.assertEqual(
            output_directory(root, "holdout", "wk", "weighted_sssp"),
            root / "holdout/wk/weighted_sssp",
        )

    def test_workload_names_match_frozen_u8_cases(self) -> None:
        initial, update = workload_paths(
            Path("/tmp/workloads"), "su", "connected_components"
        )
        self.assertEqual(initial.name, "su_connected_components_insert_u8.initial.slice")
        self.assertEqual(update.name, "su_connected_components_insert_u8.update.slice")

    def test_every_algorithm_uses_update_only(self) -> None:
        for algorithm in (
            "weighted_sssp",
            "connected_components",
            "thresholded_residual_pagerank",
        ):
            command = build_command(
                Path("/tmp/workloads"),
                Path("/tmp/output"),
                Path("/tmp/library"),
                "calibration",
                "au",
                algorithm,
            )
            self.assertIn("--update-only", command)
            self.assertIn("--no-build", command)
            self.assertNotIn("--hardware-warm-sssp", command)

    def test_weighted_runner_manifest_form_is_accepted(self) -> None:
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "update_only": True,
                        "sst_plugin_sha256": "plugin",
                    }
                ),
                encoding="ascii",
            )
            (root / "result.json").write_text(
                json.dumps(
                    {
                        "success": True,
                        "measurement_window": "pure_update_only",
                        "compute_cycles": 0,
                        "memory_locality_ledger_match": True,
                        "correctness_mismatches": 0,
                        "update_observability": {"start_cycle": 0, "end_cycle": 1},
                    }
                ),
                encoding="ascii",
            )
            self.assertTrue(valid_result(root, "plugin"))


if __name__ == "__main__":
    unittest.main()
