from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.profiles import (
    EvidenceTier,
    ProfileError,
    ProfileStatus,
    load_architecture_profile,
    verify_profile_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "configs" / "architectures"


class ArchitectureProfileTests(unittest.TestCase):
    def test_repository_profiles_load_and_have_unique_ids(self) -> None:
        loaded = [load_architecture_profile(path) for path in sorted(PROFILES.glob("*.json"))]
        self.assertEqual(len(loaded), 3)
        self.assertEqual(len({profile.profile_id for profile in loaded}), len(loaded))
        self.assertTrue(all(profile.manifest_sha256 for profile in loaded))

    def test_stable_profile_pins_accepted_clocks_and_hash(self) -> None:
        profile = load_architecture_profile(PROFILES / "spine_shared_engine_9c08763.json")
        self.assertEqual(profile.status, ProfileStatus.STABLE)
        self.assertEqual(profile.evidence_tier, EvidenceTier.HARDWARE_VALIDATED)
        self.assertEqual(profile.clock("data").requested_mhz, 150.0)
        self.assertEqual(profile.clock("data").achieved_mhz, 141.0)
        self.assertEqual(profile.clock("hbm").achieved_mhz, 450.0)
        self.assertEqual(profile.memory.channels, 32)
        self.assertEqual(profile.parameters["graph_hbm_channels"], 16)
        self.assertEqual(profile.parameters["hbm_pseudo_channels_used"], 23)
        self.assertEqual(profile.parameters["sorted_edges_hbm_channel"], 16)
        self.assertEqual(profile.parameters["active_bitmap_hbm_channel"], 22)
        self.assertEqual(
            profile.evidence[2].sha256,
            "1828434e164bf0aef28fff9fba7925cfa39f93ad86f6bfc3878f504461c76dbf",
        )

    def test_stable_profile_artifacts_exist_and_match(self) -> None:
        profile = load_architecture_profile(PROFILES / "spine_shared_engine_9c08763.json")
        self.assertEqual(verify_profile_artifacts(profile), [])

    def test_unknown_root_field_is_rejected(self) -> None:
        source = json.loads((PROFILES / "spine_latest_afb8199.json").read_text())
        source["typo"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "unknown=typo"):
                load_architecture_profile(path)

    def test_duplicate_clock_is_rejected(self) -> None:
        source = json.loads((PROFILES / "spine_latest_afb8199.json").read_text())
        source["clocks"].append(dict(source["clocks"][0]))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "duplicate clock"):
                load_architecture_profile(path)

    def test_dirty_must_be_boolean(self) -> None:
        source = json.loads((PROFILES / "spine_latest_afb8199.json").read_text())
        source["source"]["dirty"] = "false"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(source), encoding="utf-8")
            with self.assertRaisesRegex(ProfileError, "must be boolean"):
                load_architecture_profile(path)


if __name__ == "__main__":
    unittest.main()
