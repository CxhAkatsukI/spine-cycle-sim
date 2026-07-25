from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

from scripts.run_hls_weighted_real_comparison import _write_csv


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


if __name__ == "__main__":
    unittest.main()
