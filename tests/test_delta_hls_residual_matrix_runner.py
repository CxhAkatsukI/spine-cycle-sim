from __future__ import annotations

import argparse
from pathlib import Path
import unittest

from scripts.run_delta_hls_residual_matrix import (
    DAMPING,
    DEFAULT_CAPABILITIES,
    DEFAULT_GRASU_PROFILE,
    DEFAULT_MANIFEST,
    DEFAULT_SPINE_PROFILE,
    DELTA_CONTRACT,
    _command,
    _pair,
    _validate_input_manifest,
    epsilon_slug,
)


class DeltaHlsResidualMatrixRunnerTests(unittest.TestCase):
    def test_frozen_manifest_hashes_and_invariants_match(self) -> None:
        manifest = _validate_input_manifest(DEFAULT_MANIFEST)
        self.assertEqual(len(manifest["runs"]), 4)
        self.assertEqual(manifest["runs"][0]["user_mutations"], 1)

    def test_epsilon_slug_is_stable(self) -> None:
        self.assertEqual(epsilon_slug(1.0e-6), "eps_1e-06")
        self.assertEqual(epsilon_slug(1.0e-5), "eps_1e-05")

    def test_commands_pin_delta_contract_damping_and_profiles(self) -> None:
        run = _validate_input_manifest(DEFAULT_MANIFEST)["runs"][0]
        args = argparse.Namespace(
            python="python3",
            sst=Path("/sst"),
            lib_dir=Path("/lib"),
            max_cycles=10,
            spine_profile=DEFAULT_SPINE_PROFILE,
            grasu_profile=DEFAULT_GRASU_PROFILE,
            capability_catalog=DEFAULT_CAPABILITIES,
        )
        spine = _command("spine", run, Path("/out/s"), args=args, epsilon=1e-6)
        grasu = _command(
            "grasu_regraph", run, Path("/out/g"), args=args, epsilon=1e-6
        )
        for command in (spine, grasu):
            self.assertIn(DELTA_CONTRACT, command)
            self.assertEqual(command[command.index("--pagerank-epsilon") + 1], "1e-06")
        self.assertEqual(
            spine[spine.index("--pagerank-damping") + 1], str(DAMPING)
        )
        self.assertIn(str(DEFAULT_SPINE_PROFILE.resolve()), spine)
        self.assertIn(str(DEFAULT_GRASU_PROFILE.resolve()), grasu)

    def test_pair_requires_identical_frontier_and_reports_speedup(self) -> None:
        common = {
            "run_id": "r",
            "role": "screening",
            "epsilon": 1e-6,
            "user_mutations": 1,
            "iterations": 2,
            "ranks": (0.4, 0.6),
            "residuals": (0.0, 0.0),
            "frontier_in": (2, 1),
            "frontier_out": (1, 0),
            "backend_bytes": 100,
        }
        pair = _pair(
            {**common, "cycles": 10, "time_us": 1.0},
            {**common, "cycles": 20, "time_us": 2.0, "backend_bytes": 200},
        )
        self.assertEqual(pair["spine_speedup_over_grasu"], 2.0)
        self.assertEqual(pair["grasu_to_spine_backend_byte_ratio"], 2.0)

    def test_pair_rejects_cross_system_state_mismatch(self) -> None:
        common = {
            "run_id": "r",
            "role": "screening",
            "epsilon": 1e-6,
            "user_mutations": 1,
            "iterations": 1,
            "residuals": (0.0,),
            "frontier_in": (1,),
            "frontier_out": (0,),
            "backend_bytes": 100,
            "cycles": 10,
            "time_us": 1.0,
        }
        with self.assertRaises(RuntimeError):
            _pair(
                {**common, "ranks": (0.0,)},
                {**common, "ranks": (1.0,)},
            )


if __name__ == "__main__":
    unittest.main()
