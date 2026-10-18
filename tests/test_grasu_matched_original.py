"""Same original layout/order on the actual production G host path, not timing."""

import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.common_g.matched_original import analysis, preparation

ROOT = Path(__file__).resolve().parents[1]
EMPTY = 1 << 63


def packet(path, *, target=2, final=2, empty=False):
    arrays = ([0, 0, 0, 0], [], [], [], []) if empty else (
        [0, 16, 16, 16], [1], [1] + [EMPTY] * 15, [target, EMPTY | 1], [final] + [EMPTY] * 15)
    path.write_bytes(struct.pack("<5I", 0x3142474f, 1, 3, 0 if empty else 1, len(arrays[3])) +
                     b"".join(struct.pack("<" + "Q" * len(values), *values) for values in arrays))


class MatchedGAnalysisTests(unittest.TestCase):
    def test_complete_typed_facts_required(self):
        row = {"facts": {"vertices": 3, "segments": 1, "updates": 2, "route_updates": [2, 0, 0, 0]}}
        facts = analysis.expected(row)
        self.assertEqual(analysis.inspect("MATCHED_G_MODEL " + json.dumps(facts), "", row), facts)
        for key, value in (("same_update_order", 1), ("vertices", True), ("checked_words", 3),
                           ("same_logical_slots", False), ("route_updates", [0, 0, 0, 2])):
            changed = {**facts, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.inspect("MATCHED_G_MODEL " + json.dumps(changed), "", row)
        for out, err in (("MATCHED_G_MODEL " + json.dumps(facts), "warning"),
                         ("MATCHED_G_MODEL " + json.dumps(facts) + "\nextra", "")):
            with self.assertRaises(ValueError):
                analysis.inspect(out, err, row)

    def test_checked_words_include_cold_threshold_and_empty_backing(self):
        row = {"facts": {"vertices": 3, "segments": 0, "updates": 0, "route_updates": [0] * 4}}
        self.assertEqual(analysis.expected(row)["checked_words"], 4194336)
        row["facts"]["segments"] = 262146
        self.assertEqual(analysis.expected(row)["checked_words"], 8388640)

    def test_compile_profiles_do_not_change_hardware_geometry(self):
        for sanitizer in (False, True):
            argv = preparation.command(Path("/source"), Path("/xrt"), "g++", Path("/probe"), sanitizer=sanitizer)
            self.assertIn("-O1" if sanitizer else "-O3", argv)
            self.assertEqual("-DMATCHED_G_MODEL_ONLY" in argv, sanitizer)
            self.assertEqual("-lxilinxopencl" in argv, not sanitizer)
            self.assertIn("-MD", argv)
            self.assertFalse(any("MAX_CACHE" in arg for arg in argv))

    def test_freeze_rejects_missing_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                preparation.freeze(root, root, root / "output")


@unittest.skipUnless(shutil.which("g++") and os.environ.get("SPINE_G_INTEGRATION"),
                     "set SPINE_G_INTEGRATION to the reviewed production HLS checkout")
class MatchedGModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = Path(cls.temporary.name)
        cls.source = root / "source"
        cls.pins = preparation.freeze(ROOT, Path(os.environ["SPINE_G_INTEGRATION"]), cls.source)
        cls.binary = root / "probe"
        subprocess.run(preparation.command(cls.source, Path("/unused"), shutil.which("g++"),
            cls.binary, sanitizer=True), check=True, capture_output=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def invoke(self, path):
        return subprocess.run([str(self.binary), "--self-test", str(path)],
                              text=True, capture_output=True, timeout=15)

    def test_mixed_original_order_and_empty_graph(self):
        for empty in (False, True):
            with self.subTest(empty=empty), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "input.ogb"
                packet(path, empty=empty)
                result = self.invoke(path)
                self.assertEqual(result.returncode, 0, result.stderr)
                row = {"facts": {"vertices": 3, "segments": 0 if empty else 1,
                                 "updates": 0 if empty else 2, "route_updates": [0 if empty else 2, 0, 0, 0]}}
                analysis.inspect(result.stdout, result.stderr, row)

    def test_original_oracle_rejects_duplicate_absent_delete_and_wrong_final(self):
        for changes in ({"target": 1}, {"target": EMPTY | 2}, {"final": 1}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "input.ogb"
                packet(path, **changes)
                result = self.invoke(path)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, "")
                self.assertIn("original G", result.stderr)

    def test_frozen_sources_are_immutable_and_cannot_be_overwritten(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            preparation.freeze(ROOT, Path(os.environ["SPINE_G_INTEGRATION"]), self.source)
        self.assertEqual(len(self.pins), len({pin["path"] for pin in self.pins}))


if __name__ == "__main__":
    unittest.main()
