from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from scripts.export_current_fpga_fig9 import dram_energy_pj, pair_row
from scripts.render_evaluation_refresh import collect_fig9_rows_from_campaign


class ExportCurrentFPGAFig9Tests(unittest.TestCase):
    def test_energy_accepts_spine_direct_and_grasu_nested_forms(self) -> None:
        self.assertEqual(dram_energy_pj({}, {"dram_total_energy_pj": 12.0}), 12.0)
        self.assertEqual(
            dram_energy_pj({}, {"dram": {"total_energy_pj": 34.0}}), 34.0
        )

    def test_pair_requires_passing_ledgers_and_reports_ratios(self) -> None:
        row = pair_row(
            dataset="au",
            algorithm="weighted_sssp",
            spine_ledger={"status": "PASS", "accepted_backend_bytes": 100},
            grasu_ledger={"status": "PASS", "accepted_backend_bytes": 250},
            spine_energy_pj=20.0,
            grasu_energy_pj=60.0,
        )
        self.assertEqual(row["memory_ratio_gr_over_spine"], 2.5)
        self.assertEqual(row["spine_energy_advantage"], 3.0)
        with self.assertRaisesRegex(ValueError, "failed memory ledger"):
            pair_row(
                dataset="au",
                algorithm="weighted_sssp",
                spine_ledger={"status": "FAIL", "accepted_backend_bytes": 100},
                grasu_ledger={"status": "PASS", "accepted_backend_bytes": 250},
                spine_energy_pj=20.0,
                grasu_energy_pj=60.0,
            )

    def test_renderer_admits_complete_current_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = []
            for algorithm in (
                "weighted_sssp",
                "connected_components",
                "thresholded_residual_pagerank",
            ):
                for dataset in ("au", "su", "wk"):
                    rows.append(
                        {
                            "dataset_id": dataset,
                            "algorithm": algorithm,
                            "competitor": "grasu_regraph_k4_shared",
                            "spine_memory_bytes": 100,
                            "competitor_memory_bytes": 200,
                            "spine_energy_advantage": 3.0,
                        }
                    )
            with (root / "pair_rows.csv").open(
                "w", encoding="ascii", newline=""
            ) as sink:
                writer = csv.DictWriter(sink, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            (root / "manifest.json").write_text(
                json.dumps({"status": "PASS_CURRENT_MODEL_DATA"}) + "\n",
                encoding="ascii",
            )

            selected, _, status = collect_fig9_rows_from_campaign(root)

        self.assertEqual(len(selected), 9)
        self.assertEqual(status, "PASS_CURRENT_MODEL_DATA")


if __name__ == "__main__":
    unittest.main()
