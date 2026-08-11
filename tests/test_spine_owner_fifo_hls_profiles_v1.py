from __future__ import annotations

import json
import subprocess
from pathlib import Path
import unittest

from spine_cycle_sim.profiles import load_architecture_profile, verify_profile_artifacts
from spine_cycle_sim.sst_binding import spine_memory_binding


ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "configs" / "architectures"
PROFILES = tuple(ARCH / f"spine_owner_fifo_{tag}_hls_v1.json" for tag in ("sssp", "cc", "respr", "fullpr"))


class SpineOwnerFifoHlsProfilesV1Tests(unittest.TestCase):
    def test_generated_profiles_are_current(self) -> None:
        subprocess.run(
            [
                "python3",
                str(ROOT / "scripts" / "generate_spine_owner_fifo_hls_profiles_v1.py"),
                "--check",
            ],
            cwd=ROOT,
            check=True,
        )

    def test_profiles_pin_owner_scheduler_and_routed_evidence(self) -> None:
        for path in PROFILES:
            profile = load_architecture_profile(path)
            self.assertEqual(profile.evidence_tier.value, "hardware_validated")
            self.assertEqual(profile.clock("data").achieved_mhz, 150.0)
            self.assertEqual(profile.parameters["owner_fifo_depth_per_partition"], 256)
            self.assertEqual(profile.parameters["reactivation_fifo_depth_per_partition"], 256)
            self.assertTrue(profile.parameters["owner_scheduler_enabled"])
            self.assertTrue(profile.parameters["device_determines_active_membership"])
            self.assertFalse(profile.parameters["host_recomputes_active_membership"])
            self.assertEqual(verify_profile_artifacts(profile, repository_root=ROOT), [])

    def test_profiles_bind_complete_spine_hbm_topology(self) -> None:
        workload = ROOT / "tests" / "data" / "shared_comparison" / "syn_chain_v64.slice"
        for path in PROFILES:
            raw = json.loads(path.read_text(encoding="utf-8"))
            binding = spine_memory_binding(raw, [workload])
            self.assertEqual(binding.physical_channels, 32)
            self.assertEqual(binding.instantiated_channels, binding.reachable_channels)
            self.assertTrue(set(range(16, 23)) <= set(binding.reachable_channels))


if __name__ == "__main__":
    unittest.main()
