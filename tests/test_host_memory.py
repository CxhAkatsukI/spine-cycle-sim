from __future__ import annotations

import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.host_memory import release_process_heap


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
        with patch(
            "spine_cycle_sim.experiments.host_memory.ctypes.CDLL",
            return_value=library,
        ):
            self.assertTrue(release_process_heap())
        self.assertEqual(trim.calls, [0])

    def test_release_process_heap_reports_missing_platform_support(self) -> None:
        library = object()
        with patch(
            "spine_cycle_sim.experiments.host_memory.ctypes.CDLL",
            return_value=library,
        ):
            self.assertFalse(release_process_heap())


if __name__ == "__main__":
    unittest.main()
