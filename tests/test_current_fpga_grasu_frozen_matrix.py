from pathlib import Path
import unittest

from scripts.run_current_fpga_grasu_frozen_matrix import build_command


class CurrentFPGAGrasuFrozenMatrixTests(unittest.TestCase):
    def test_weighted_command_freezes_source_and_shared_k4_profile(self) -> None:
        command = build_command(Path("/sim"), Path("/plugin"), "r19", "weighted_sssp")
        self.assertIn("run_sst_grasu_regraph_hls_weighted.py", " ".join(command))
        self.assertEqual(command[command.index("--source") + 1], "113")
        self.assertEqual(command[command.index("--downstream-sharing") + 1], "shared")

    def test_residual_command_freezes_threshold_semantics(self) -> None:
        command = build_command(
            Path("/sim"),
            Path("/plugin"),
            "wk",
            "thresholded_residual_pagerank",
        )
        self.assertEqual(command[command.index("--pagerank-epsilon") + 1], "1e-6")
        self.assertEqual(
            command[command.index("--residual-contract") + 1],
            "grasu_hardware_warm_dangling_linf",
        )

    def test_cc_command_matches_routed_full_recompute_host(self) -> None:
        command = build_command(
            Path("/sim"), Path("/plugin"), "su", "connected_components"
        )
        self.assertIn("--hardware-full-recompute", command)
        self.assertEqual(command[command.index("--architecture") + 1], "grasu")


if __name__ == "__main__":
    unittest.main()

