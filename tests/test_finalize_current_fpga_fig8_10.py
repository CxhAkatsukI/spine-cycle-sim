from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "finalize_current_fpga_fig8_10",
    ROOT / "scripts" / "finalize_current_fpga_fig8_10.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FinalizeCurrentFpgaFig8To10Tests(unittest.TestCase):
    def test_require_status_accepts_only_expected_value(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text('{"status": "PASS"}\n', encoding="ascii")
            self.assertEqual(MODULE.require_status(manifest, "PASS")["status"], "PASS")
            with self.assertRaises(ValueError):
                MODULE.require_status(manifest, "FAIL")

    def test_copy_with_hash_preserves_content_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            destination = root / "nested" / "destination.txt"
            source.write_text("evidence\n", encoding="ascii")
            record = MODULE.copy_with_hash(source, destination)
            self.assertEqual(destination.read_text(encoding="ascii"), "evidence\n")
            self.assertEqual(record["source_sha256"], record["output_sha256"])


if __name__ == "__main__":
    unittest.main()
