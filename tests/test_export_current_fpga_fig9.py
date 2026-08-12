from __future__ import annotations

import csv
import json
from pathlib import Path
import tempfile
import unittest

from scripts.export_current_fpga_fig9 import (
    DEFAULT_CONTRACT,
    conservation_audit,
    dram_energy_pj,
    pair_row,
    write_csv,
)
from scripts.render_evaluation_refresh import collect_fig9_rows_from_campaign


class ExportCurrentFPGAFig9Tests(unittest.TestCase):
    def test_csv_writer_uses_repository_lf_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "rows.csv"
            write_csv(output, [{"dataset": "au", "value": 1}])
            self.assertEqual(output.read_bytes(), b"dataset,value\nau,1\n")

    def test_v20_contract_pins_dual_plugins_and_nine_rows(self) -> None:
        contract = json.loads(DEFAULT_CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["gates"]["rows_expected"], 9)
        self.assertNotEqual(
            contract["architectures"]["spine"]["plugin"]["sha256"],
            contract["architectures"]["grasu_regraph"]["plugin"]["sha256"],
        )
        self.assertFalse(contract["measurement"]["timing_calibration_applied"])

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

    def test_conservation_audit_requires_closed_arbitration_and_dram(self) -> None:
        result = {
            "backend_requests": 7,
            "backend_arbitration": {
                "ledger_closed": True,
                "unique_intents": 7,
                "grants": 7,
                "consumed_grants": 7,
                "pending_intents": 0,
                "pending_grants": 0,
            },
        }
        manifest = {
            "dram": {"reads": 5, "writes": 2},
            "checks": {"dram_request_ledger": True},
        }
        audit = conservation_audit(result, manifest, {"status": "PASS"})
        self.assertEqual(audit["status"], "PASS")
        result["backend_arbitration"]["pending_grants"] = 1
        self.assertEqual(
            conservation_audit(result, manifest, {"status": "PASS"})["status"],
            "FAIL",
        )

    def test_conservation_accepts_flat_spine_dram_schema(self) -> None:
        result = {
            "backend_requests": 3,
            "backend_arbitration": {
                "ledger_closed": True,
                "unique_intents": 3,
                "grants": 3,
                "consumed_grants": 3,
                "pending_intents": 0,
                "pending_grants": 0,
            },
        }
        manifest = {"dram_reads": 2, "dram_writes": 1}
        self.assertEqual(
            conservation_audit(result, manifest, {"status": "PASS"})["status"],
            "PASS",
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
