from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.sst_library import forced_sst_library_binding


class SstLibraryBindingTest(unittest.TestCase):
    def test_forces_plugin_before_installed_elements(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sst = root / "bin/sst"
            plugin = root / "candidate/libspine_cycle.so"
            elements = root / "lib/sst-elements-library/libmemHierarchy.so"
            for path, payload in (
                (sst, b"sst"),
                (plugin, b"candidate"),
                (elements, b"mem"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            binding = forced_sst_library_binding(sst, plugin.parent)
            self.assertTrue(binding["command_option"].startswith("--lib-path="))
            self.assertEqual(
                binding["search_path"].split(":"),
                [str(plugin.parent), str(elements.parent)],
            )
            self.assertEqual(len(binding["plugin_sha256"]), 64)

    def test_rejects_missing_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "missing Spine SST plugin"):
                forced_sst_library_binding(root / "bin/sst", root / "candidate")

    def test_exact_idle_wrapper_uses_isolated_element_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrapper = root / "repo/scripts/run_sst_exact_idle_dramsim3.sh"
            plugin = root / "candidate/libspine_cycle.so"
            elements = (
                root
                / "idle-install/lib/sst-elements-library/libmemHierarchy.so"
            )
            for path, payload in (
                (wrapper, b"wrapper"),
                (plugin, b"candidate"),
                (elements, b"idle-mem"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
            with patch.dict(
                "os.environ",
                {"SPINE_IDLE_SST_INSTALL_PREFIX": str(root / "idle-install")},
            ):
                binding = forced_sst_library_binding(wrapper, plugin.parent)
            self.assertEqual(
                binding["search_path"].split(":"),
                [str(plugin.parent), str(elements.parent)],
            )
