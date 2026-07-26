from __future__ import annotations

import configparser
import json
from pathlib import Path
import tempfile
import unittest

from scripts.generate_hbm_sensitivity_configs import (
    DEFAULT_MANIFEST,
    ROOT,
    load_manifest,
    read_ini,
    render_profiles,
)


class HbmSensitivityProfileTests(unittest.TestCase):
    def test_generated_configs_are_current_and_change_only_declared_keys(self) -> None:
        manifest = load_manifest(DEFAULT_MANIFEST)
        baseline_spec = manifest["baseline"]
        self.assertIsInstance(baseline_spec, dict)
        baseline = read_ini(ROOT / baseline_spec["path"])
        rendered = render_profiles(DEFAULT_MANIFEST)
        profiles = {profile["output"]: profile for profile in manifest["profiles"]}
        self.assertEqual(len(rendered), 4)
        for path, expected in rendered.items():
            self.assertEqual(path.read_text(encoding="ascii"), expected)
            profile = profiles[str(path.relative_to(ROOT))]
            with tempfile.NamedTemporaryFile(mode="w", encoding="ascii") as stream:
                stream.write(expected)
                stream.flush()
                candidate = read_ini(Path(stream.name))
            declared = set(profile["changes"])
            observed: set[str] = set()
            for section in baseline.sections():
                for key, value in baseline.items(section):
                    if candidate.get(section, key) != value:
                        observed.add(f"{section}.{key}")
            self.assertEqual(observed, declared)

    def test_profile_set_is_orthogonal_and_directionally_named(self) -> None:
        manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="ascii"))
        identities = {
            (profile["axis"], profile["direction"])
            for profile in manifest["profiles"]
        }
        self.assertEqual(
            identities,
            {
                ("latency", "low"),
                ("latency", "high"),
                ("bandwidth", "low"),
                ("bandwidth", "high"),
            },
        )
        for profile in manifest["profiles"]:
            keys = set(profile["changes"])
            if profile["axis"] == "latency":
                self.assertTrue(keys <= {
                    "timing.CL",
                    "timing.CWL",
                    "timing.tRCDRD",
                    "timing.tRCDWR",
                    "timing.tRP",
                })
            else:
                self.assertTrue(keys <= {"timing.tCCD_S", "timing.tCCD_L"})


if __name__ == "__main__":
    unittest.main()
