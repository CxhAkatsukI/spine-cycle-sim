"""CPU-only chronological sublaunch scheduling regressions, with no XRT dependency."""

from pathlib import Path
import subprocess
import tempfile
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "cpp/tests/evaluation_impact/"
          "figure8_fpga/test_spine_persistent_schedule.cpp")


class PersistentScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="figure8-schedule-")
        cls.addClassCleanup(temporary.cleanup)
        cls.binary = Path(temporary.name) / "schedule-test"
        result = subprocess.run(
            ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
             str(SOURCE), "-o", str(cls.binary)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    def run_case(self, name):
        result = subprocess.run(
            [str(self.binary), name], capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, f"PASS {name}\n")

    def test_launch_counts_coverage_and_original_edge_order(self):
        self.run_case("matrix")

    def test_invalid_sizes_and_overflow_safe_boundaries(self):
        self.run_case("guards")

    def test_default_limit_preserves_l1_capacity(self):
        self.run_case("l1")


if __name__ == "__main__":
    unittest.main()
