from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from scripts.run_current_fpga_grasu_frozen_matrix import (
    build_command,
    valid_existing_result,
)


class CurrentFPGAGrasuFrozenMatrixTests(unittest.TestCase):
    def test_weighted_command_freezes_source_and_shared_k4_profile(self) -> None:
        command = build_command(Path("/sim"), Path("/plugin"), "r19", "weighted_sssp")
        self.assertIn("run_sst_grasu_regraph_hls_weighted.py", " ".join(command))
        self.assertEqual(command[command.index("--source") + 1], "113")
        self.assertEqual(command[command.index("--downstream-sharing") + 1], "shared")
        self.assertIn("--hardware-warm-sssp", command)

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

    def test_cc_command_matches_routed_resident_host(self) -> None:
        command = build_command(
            Path("/sim"), Path("/plugin"), "su", "connected_components"
        )
        self.assertNotIn("--hardware-full-recompute", command)
        self.assertEqual(command[command.index("--architecture") + 1], "grasu")

    def test_result_reuse_requires_resident_algorithm_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out = root / "out"
            out.mkdir()
            profile = root / "profile.json"
            plugin = root / "plugin.so"
            profile.write_text("{}\n", encoding="ascii")
            plugin.write_bytes(b"plugin")
            (out / "result.json").write_text("{}\n", encoding="ascii")
            manifest = {
                "status": "PASS",
                "sst_plugin_sha256": hashlib.sha256(plugin.read_bytes()).hexdigest(),
                "profile_sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
                "resident_state": "cold_source_initialized",
            }
            (out / "manifest.json").write_text(
                json.dumps(manifest), encoding="ascii"
            )
            self.assertFalse(
                valid_existing_result(out, profile, plugin, "weighted_sssp")
            )
            manifest["resident_state"] = "old_graph_converged"
            (out / "manifest.json").write_text(
                json.dumps(manifest), encoding="ascii"
            )
            self.assertTrue(
                valid_existing_result(out, profile, plugin, "weighted_sssp")
            )


if __name__ == "__main__":
    unittest.main()
