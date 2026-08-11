from __future__ import annotations

import subprocess
from pathlib import Path
import unittest

from spine_cycle_sim.profiles import load_architecture_profile, verify_profile_artifacts


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
            self.assertTrue(profile.parameters["device_determines_active_membership"])
            self.assertFalse(profile.parameters["host_recomputes_active_membership"])
            self.assertEqual(verify_profile_artifacts(profile, repository_root=ROOT), [])


if __name__ == "__main__":
    unittest.main()
