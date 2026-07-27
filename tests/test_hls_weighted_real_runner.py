from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.run_hls_weighted_real_comparison import (
    _restore_spine_final_values,
    _write_csv,
)


class HlsWeightedRealRunnerTests(unittest.TestCase):
    def test_csv_writer_accepts_architecture_specific_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rows.csv"
            _write_csv(
                path,
                [
                    {"system": "grasu_regraph", "update_requests": 4},
                    {"system": "spine", "cold_requests": 2},
                ],
            )
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))

        self.assertEqual(
            list(rows[0]), ["system", "update_requests", "cold_requests"]
        )
        self.assertEqual(rows[0]["cold_requests"], "")
        self.assertEqual(rows[1]["update_requests"], "")
        self.assertEqual(rows[1]["cold_requests"], "2")

    def test_csv_writer_rejects_empty_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "empty CSV"):
                _write_csv(Path(temporary) / "rows.csv", [])

    def test_restores_large_spine_vector_only_after_hash_check(self) -> None:
        values = list(range(4_097))
        encoded = json.dumps(values, separators=(",", ":")).encode("ascii")
        summary = {
            "final_values_count": len(values),
            "final_values_sha256": hashlib.sha256(encoded).hexdigest(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "result.json").write_text(
                json.dumps({"final_values": values}), encoding="utf-8"
            )
            restored = _restore_spine_final_values(root, summary)
            self.assertEqual(restored["final_values"], values)

            summary["final_values_sha256"] = "0" * 64
            with self.assertRaisesRegex(RuntimeError, "hash"):
                _restore_spine_final_values(root, summary)


if __name__ == "__main__":
    unittest.main()
