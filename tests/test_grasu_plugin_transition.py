from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.audit_grasu_plugin_transition import compare_pair


class GrasuPluginTransitionTests(unittest.TestCase):
    def make_run(self, root: Path, name: str, cycles: int, plugin: str) -> Path:
        run = root / name
        run.mkdir()
        (run / "result.json").write_text(
            json.dumps({"success": True, "cycles": cycles}), encoding="ascii"
        )
        (run / "manifest.json").write_text(
            json.dumps({"status": "PASS", "sst_plugin_sha256": plugin}),
            encoding="ascii",
        )
        return run

    def test_exact_result_is_admitted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = self.make_run(root, "old", 17, "a" * 64)
            candidate = self.make_run(root, "new", 17, "b" * 64)
            row = compare_pair("weighted", baseline, candidate)
            self.assertEqual(row["status"], "PASS")
            self.assertTrue(row["exact_result_match"])

    def test_changed_result_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = self.make_run(root, "old", 17, "a" * 64)
            candidate = self.make_run(root, "new", 18, "b" * 64)
            with self.assertRaisesRegex(ValueError, "cycles"):
                compare_pair("weighted", baseline, candidate)


if __name__ == "__main__":
    unittest.main()
