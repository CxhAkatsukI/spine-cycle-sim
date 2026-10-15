"""Composition gates distinguish a known host-only change from hardware drift."""

from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.core_identity import (
    GUARD, REPORT, THREAD_REPORT, check)


class CoreIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.composition, self.search, self.cache = (root / name for name in ("composition", "search", "cache"))
        self.left = self.composition / "source/hls"
        self.right = self.search / "source/cpp/tests/evaluation_impact/common_g/hls"
        for folder in (self.left, self.right):
            (folder / "search_binding").mkdir(parents=True)
            (folder / "search_binding/top.cpp").write_text("same hardware wrapper\n")
            (folder / "search_binding/top.hpp").write_text("same hardware declaration\n")
            (folder / "search_pipeline").mkdir()
            (folder / "search_pipeline/network.hpp").write_text(GUARD)
            (folder / "search_pipeline/finite_host.hpp").write_text(REPORT)
        (self.cache / "source").mkdir(parents=True)
        for name in ("cache_pipeline.hpp", "cache_bank.hpp", "cache_lane.hpp"):
            (self.cache / "source" / name).write_text("same cache\n")
            (self.left / name).write_text("same cache\n")

    def run_check(self):
        return check(self.composition, self.search, self.cache)

    def test_identical_or_exact_known_host_change(self):
        self.assertEqual(self.run_check()["host_only_differences"], [])
        (self.left / "search_pipeline/finite_host.hpp").write_text(THREAD_REPORT)
        observation = self.run_check()
        self.assertTrue(observation["synthesizable_core_identical"])
        self.assertEqual(len(observation["host_only_differences"]), 1)

    def test_other_host_change_rejected(self):
        (self.left / "search_pipeline/finite_host.hpp").write_text(THREAD_REPORT + "\nother change\n")
        with self.assertRaises(ValueError):
            self.run_check()

    def test_synthesis_guard_removal_rejected(self):
        (self.left / "search_pipeline/finite_host.hpp").write_text(THREAD_REPORT)
        for folder in (self.left, self.right):
            (folder / "search_pipeline/network.hpp").write_text('#include "finite_host.hpp"')
        with self.assertRaises(ValueError):
            self.run_check()

    def test_hardware_drift_or_missing_file_rejected(self):
        path = self.left / "search_binding/top.cpp"
        path.write_text("changed hardware\n")
        with self.assertRaises(ValueError):
            self.run_check()
        path.unlink()
        with self.assertRaises(ValueError):
            self.run_check()

    def test_cache_change_rejected(self):
        (self.left / "cache_pipeline.hpp").write_text("different cache\n")
        with self.assertRaises(ValueError):
            self.run_check()

    def test_independent_testbench_files_are_not_shared_core(self):
        for name in ("control.cpp", "rtl_control.cpp"):
            (self.right / "search_binding" / name).write_text("independent testbench\n")
            (self.right / "search_pipeline" / name).write_text("independent testbench\n")
        (self.right / "search_pipeline/top.cpp").write_text("component wrapper\n")
        self.assertTrue(self.run_check()["synthesizable_core_identical"])
        (self.right / "search_pipeline/extra.hpp").write_text("unexpected core\n")
        with self.assertRaises(ValueError):
            self.run_check()


if __name__ == "__main__":
    unittest.main()
