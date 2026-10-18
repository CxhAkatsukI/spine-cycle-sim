"""Bounded packet, compiler and independent-oracle checks; never programs XRT."""

import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import preparation, preflight

ROOT = Path(__file__).resolve().parents[1]
EMPTY = 1 << 63


def captures(directory, *, target=2):
    directory.mkdir()
    contents = ([0, 16, 16, 16], [1], [1] + [EMPTY] * 15,
                [target, EMPTY | 1], [target] + [EMPTY] * 15)
    for name, values in zip(preparation.PACKET_CAPTURES, contents):
        (directory / name).write_bytes(struct.pack("<" + "Q" * len(values), *values))
    return {"vertices": 3, "segments": 1, "updates": 2}


@unittest.skipUnless(shutil.which("g++"), "C++ compiler required")
class OriginalGraSUBoardHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.binary = Path(cls.temporary.name) / "probe"
        subprocess.run([shutil.which("g++"), "-std=c++17", "-O1", "-Wall", "-Wextra", "-Werror",
            "-DORIGINAL_G_MODEL_ONLY", "-fsanitize=undefined", "-fno-sanitize-recover=all",
            str(ROOT / preflight.CPP / "control.cpp"), "-o", str(cls.binary)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def invoke(self, path, *, board=False):
        return subprocess.run([str(self.binary), "--board" if board else "--self-test", str(path)],
                              text=True, capture_output=True, timeout=15)

    def test_packet_export_and_complete_oracle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            facts = captures(root / "captures")
            preparation.export(root / "captures", facts, root / "input")
            self.assertEqual((root / "input").stat().st_size, 20 + 8 * (4 + 33 + 2))
            result = self.invoke(root / "input")
            self.assertEqual(result.returncode, 0, result.stderr)
            observed = json.loads(result.stdout.removeprefix("ORIGINAL_G_MODEL "))
            self.assertEqual(observed["route_updates"], [2, 0, 0, 0])
            self.assertEqual(observed["checked_slots_including_guards"], 4 * 16 * 131072 + 128)
            self.assertEqual(observed["status"], "PASS_NOT_BOARD")

    def test_final_state_and_duplicate_or_absent_updates_rejected(self):
        for target in (1, EMPTY | 2):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                facts = captures(root / "captures", target=target)
                preparation.export(root / "captures", facts, root / "input")
                self.assertNotEqual(self.invoke(root / "input").returncode, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            facts = captures(root / "captures")
            (root / "captures/updated.u64le").write_bytes(struct.pack("<16Q", 1, *([EMPTY] * 15)))
            preparation.export(root / "captures", facts, root / "input")
            self.assertIn("final-state disagreement", self.invoke(root / "input").stderr)

    def test_bad_header_extents_trailing_bytes_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            facts = captures(root / "captures")
            preparation.export(root / "captures", facts, root / "good")
            good = (root / "good").read_bytes()
            for payload in (good[:19], b"xxxx" + good[4:], good + b"x",
                            good[:8] + struct.pack("<I", 0xffffffff) + good[12:]):
                (root / "bad").write_bytes(payload)
                self.assertNotEqual(self.invoke(root / "bad").returncode, 0)
            (root / "link").symlink_to(root / "good")
            self.assertNotEqual(self.invoke(root / "link").returncode, 0)
            self.assertNotEqual(self.invoke(root / "good", board=True).returncode, 0)

    def test_export_rejects_bad_dimensions_capture_extent_and_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            facts = captures(root / "captures")
            for invalid in (0, -1, 262209, True):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    preparation.export(root / "captures", {**facts, "vertices": invalid}, root / "input")
            preparation.export(root / "captures", facts, root / "input")
            with self.assertRaises(FileExistsError):
                preparation.export(root / "captures", facts, root / "input")
            (root / "captures/binary.u64le").write_bytes(b"extra")
            with self.assertRaises(ValueError):
                preparation.export(root / "captures", facts, root / "other")

    def test_unreviewed_baseline_stops_before_capture_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "report.json").write_text("{}")
            with patch.object(preparation, "analyze") as analyze, self.assertRaises(ValueError):
                preparation.prepare(root, root / "output")
            analyze.assert_not_called()
            self.assertFalse((root / "output").exists())

    def test_compiler_is_release_with_real_xrt_or_separate_ubsan_model(self):
        for sanitizer in (False, True):
            command = preflight.compiler_command(ROOT, Path("/xrt"), Path("/out"), "/g++", sanitizer=sanitizer)
            self.assertIn("-O1" if sanitizer else "-O3", command)
            self.assertEqual("-lxilinxopencl" in command, not sanitizer)
            self.assertNotIn("-lOpenCL", command)
            self.assertEqual("-DORIGINAL_G_MODEL_ONLY" in command, sanitizer)
            self.assertIn("-DNDEBUG", command)

    def test_model_inspection_rejects_false_counters_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "stdout").write_text('ORIGINAL_G_MODEL {"status":"PASS_NOT_BOARD"}\n')
            (root / "stderr").write_bytes(b"")
            row = {"facts": {key: 0 for key in ("vertices", "segments", "updates", "route_updates")},
                   "expected_slots_including_guards": 0}
            with self.assertRaises(ValueError):
                preflight.inspect_model(root / "stdout", root / "stderr", row)
            (root / "stderr").write_text("warning")
            with self.assertRaises(ValueError):
                preflight.inspect_model(root / "stdout", root / "stderr", row)


if __name__ == "__main__":
    unittest.main()
