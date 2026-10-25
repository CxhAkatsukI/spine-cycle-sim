from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.host_memory import release_process_heap, sample_host_memory


GIB = 1024**3
MODULE = Path(__file__).resolve().parents[1] / "spine_cycle_sim/experiments/host_memory.py"


class HostMemoryAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.meminfo, self.arcstats = self.root / "meminfo", self.root / "arcstats"
        self.meminfo.write_text("MemTotal: 262144000 kB\nMemAvailable: 20971520 kB\n")

    def sample(self):
        return sample_host_memory(meminfo=self.meminfo, arcstats=self.arcstats)

    def arc(self, *, size=125, minimum=8, mru=10, mfu=100):
        values = {"size": size, "c_min": minimum,
                  "mru_evictable_data": mru, "mfu_evictable_data": mfu}
        self.arcstats.write_text("12 1 0x01 95 1 1\nname type data\n" + "".join(
            f"{key} 4 {int(value * GIB)}\n" for key, value in values.items()))

    def test_non_zfs_preserves_linux_estimate(self):
        sample = self.sample()
        self.assertEqual(sample.available_bytes, 20 * GIB)
        self.assertEqual(sample.arc_status, "absent")

    def test_only_evictable_data_is_added_not_all_arc_or_metadata(self):
        self.arc()
        with self.arcstats.open("a") as stream:
            stream.write(f"mru_evictable_metadata 4 {5 * GIB}\nanon_size 4 {GIB}\n")
        sample = self.sample()
        self.assertEqual(sample.available_bytes, 130 * GIB)
        self.assertEqual(sample.record()["arc_allowance_bytes"], 110 * GIB)

    def test_minimum_arc_is_not_offered_for_builds(self):
        self.arc(mru=100, mfu=100)
        self.assertEqual(self.sample().arc_allowance_bytes, 117 * GIB)

    def test_arc_already_below_minimum_adds_nothing(self):
        self.arc(size=4)
        self.assertEqual(self.sample().available_bytes, 20 * GIB)

    def test_unevictable_arc_adds_nothing(self):
        self.arc(mru=0, mfu=0)
        self.assertEqual(self.sample().available_bytes, 20 * GIB)

    def test_estimate_cannot_exceed_physical_memory(self):
        self.meminfo.write_text("MemTotal: 262144000 kB\nMemAvailable: 251658240 kB\n")
        self.arc()
        self.assertEqual(self.sample().available_bytes, 250 * GIB)

    def test_bad_or_partial_arc_falls_back_to_linux(self):
        self.arc()
        good = self.arcstats.read_text()
        for text in ("", "size 4 99\n", good + "size 4 12\n",
                     good.replace("c_min 4", "c_min 3"),
                     good.replace(str(8 * GIB), "-1"),
                     good.replace(str(125 * GIB), str(500 * GIB)),
                     "\N{LATIN SMALL LETTER E WITH ACUTE}"):
            with self.subTest(text=text):
                self.arcstats.write_text(text)
                sample = self.sample()
                self.assertEqual(sample.available_bytes, 20 * GIB)
                self.assertEqual(sample.arc_status, "unreadable_or_invalid")

    def test_unreadable_arc_falls_back_to_linux(self):
        self.arcstats.mkdir()
        self.assertEqual(self.sample().arc_status, "unreadable_or_invalid")

    def test_invalid_meminfo_refuses_admission(self):
        for text in ("", "MemTotal: 20 kB\n", "MemTotal: 1 kB\nMemAvailable: 2 kB\n",
                     "MemTotal: 2 kB\nMemAvailable: -1 kB\n",
                     "MemTotal: 2 kB\nMemAvailable: 1 B\n",
                     "MemTotal: 2 kB\nMemAvailable: 1 kB\nMemAvailable: 1 kB\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.meminfo.write_text(text)
                self.sample()

    def test_missing_meminfo_is_not_an_unbounded_launch(self):
        self.meminfo.unlink()
        with self.assertRaises(FileNotFoundError):
            self.sample()

    def test_standalone_probe_is_available_to_external_build_shell(self):
        output = subprocess.check_output([sys.executable, str(MODULE), "--bytes"],
                                         text=True, timeout=10)
        self.assertGreater(int(output), 0)


class _FakeTrim:
    argtypes: object = None
    restype: object = None

    def __init__(self, result: int) -> None:
        self.result = result
        self.calls: list[int] = []

    def __call__(self, pad: int) -> int:
        self.calls.append(pad)
        return self.result


class HostMemoryTests(unittest.TestCase):
    def test_release_process_heap_invokes_glibc_trim(self) -> None:
        trim = _FakeTrim(1)
        library = type("FakeLibc", (), {"malloc_trim": trim})()
        with patch("spine_cycle_sim.experiments.host_memory.ctypes.CDLL", return_value=library):
            self.assertTrue(release_process_heap())
        self.assertEqual(trim.calls, [0])

    def test_release_process_heap_reports_missing_platform_support(self) -> None:
        with patch("spine_cycle_sim.experiments.host_memory.ctypes.CDLL", return_value=object()):
            self.assertFalse(release_process_heap())


if __name__ == "__main__":
    unittest.main()
