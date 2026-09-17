from __future__ import annotations

import copy
import csv
from pathlib import Path
import unittest

from scripts.package_simulator_predicted_fig10 import (
    DEFAULT_ROWS,
    DEFAULT_SUMMARY,
    GROUPS,
    normalized_rows,
    read_json,
    validate_and_order_rows,
    validate_summary,
)


def source_rows() -> list[dict[str, str]]:
    with Path(DEFAULT_ROWS).open(encoding="ascii", newline="") as source:
        return list(csv.DictReader(source))


class PackageSimulatorPredictedFig10Tests(unittest.TestCase):
    def test_tracked_rows_cover_all_five_classes_and_close(self) -> None:
        selected = validate_and_order_rows(source_rows())
        self.assertEqual(len(selected), 11)
        self.assertEqual(
            [group for group, _entries in GROUPS],
            ["Zero-net", "Shallow insert", "Deep carry", "PR correction", "Deletion fallback"],
        )
        normalized = normalized_rows(selected)
        for row in normalized:
            percentage = sum(
                float(value)
                for key, value in row.items()
                if key.endswith("_percent")
            )
            self.assertAlmostEqual(percentage, 100.0, places=6)

    def test_rejects_mixed_plugins(self) -> None:
        rows = source_rows()
        rows[0]["plugin_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "one identified simulator plugin"):
            validate_and_order_rows(rows)

    def test_rejects_open_stage_ledger(self) -> None:
        rows = source_rows()
        rows[0]["ten_stage_ledger_closed"] = "False"
        with self.assertRaisesRegex(ValueError, "ten_stage_ledger_closed"):
            validate_and_order_rows(rows)

    def test_rejects_cycle_nonconservation(self) -> None:
        rows = source_rows()
        rows[0]["total_cycles"] = str(int(rows[0]["total_cycles"]) + 1)
        with self.assertRaisesRegex(ValueError, "stage ledger does not close"):
            validate_and_order_rows(rows)

    def test_rejects_missing_zero_net_semantics(self) -> None:
        rows = copy.deepcopy(source_rows())
        rows[0]["explicit_zero_net_semantics"] = "False"
        with self.assertRaisesRegex(ValueError, "explicit zero-net"):
            validate_and_order_rows(rows)

    def test_rejects_internally_consistent_old_plugin(self) -> None:
        rows = source_rows()
        for row in rows:
            row["plugin_sha256"] = "7563b028e61e792e7043a582682dd26d0e3d8cc3e2407021f144519d0ef57bf6"
        with self.assertRaisesRegex(ValueError, "frozen Figure 11"):
            validate_and_order_rows(rows)

    def test_tracked_summary_matches_rows_and_closes_all_classes(self) -> None:
        rows = validate_and_order_rows(source_rows())
        validate_summary(read_json(DEFAULT_SUMMARY), rows[0]["plugin_sha256"])

    def test_rejects_incomplete_summary_coverage(self) -> None:
        summary = read_json(DEFAULT_SUMMARY)
        summary["coverage"].pop("zero_net")
        with self.assertRaisesRegex(ValueError, "complete five-class"):
            validate_summary(summary, summary["preferred_plugin_sha256"][0])


if __name__ == "__main__":
    unittest.main()
