from pathlib import Path
import unittest

from scripts.run_current_fpga_spine_compacted_matrix import (
    OUTPUT_DIRECTORY,
    build_command,
    output_directory,
    workload_paths,
)


class CurrentFPGASpineCompactedMatrixTests(unittest.TestCase):
    def test_sssp_command_freezes_warm_start_and_source(self) -> None:
        command = build_command(Path("/sim"), Path("/plugin"), "su", "weighted_sssp")
        self.assertIn("dynamic_sssp", command)
        self.assertIn("--sssp-warm-start", command)
        self.assertEqual(command[command.index("--source") + 1], "23")
        self.assertEqual(command[command.index("--max-rounds") + 1], "256")

    def test_residual_command_freezes_contract_and_threshold(self) -> None:
        command = build_command(
            Path("/sim"),
            Path("/plugin"),
            "wk",
            "thresholded_residual_pagerank",
        )
        self.assertEqual(
            command[command.index("--residual-contract") + 1],
            "grasu_hardware_warm_dangling_linf",
        )
        self.assertEqual(command[command.index("--pagerank-epsilon") + 1], "1e-6")

    def test_cc_command_uses_device_active_path(self) -> None:
        command = build_command(
            Path("/sim"), Path("/plugin"), "r19", "connected_components"
        )
        self.assertIn("run_sst_connected_components.py", " ".join(command))
        self.assertNotIn("--hardware-full-recompute", command)

    def test_paths_are_versioned_and_do_not_replace_old_evidence(self) -> None:
        initial, update = workload_paths(
            Path("/sim"), "au", "connected_components"
        )
        self.assertEqual(initial.name, "au_connected_components_insert_u8.initial.slice")
        self.assertEqual(update.name, "au_connected_components_insert_u8.update.slice")
        self.assertEqual(
            output_directory(Path("/sim"), "au", "connected_components").name,
            OUTPUT_DIRECTORY["connected_components"],
        )


if __name__ == "__main__":
    unittest.main()
