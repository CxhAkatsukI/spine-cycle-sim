from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/collect_candidate10_m_axi_adapter_alignment.py"
SPEC = importlib.util.spec_from_file_location("m_axi_adapter_alignment", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Candidate10MAxiAdapterAlignmentTest(unittest.TestCase):
    def test_repository_evidence_is_consistent(self) -> None:
        evidence = MODULE.collect(
            MODULE.DEFAULT_ORACLE,
            MODULE.DEFAULT_BEFORE,
            MODULE.DEFAULT_AFTER,
        )
        self.assertEqual(evidence["rtl_oracle"]["cases"], 29)
        self.assertEqual(evidence["rtl_oracle"]["max_observed_outstanding"], 16)
        schedule = evidence["backpressure_schedule"]
        self.assertEqual(schedule["status"], "PASS_BOUNDED")
        self.assertEqual(
            schedule["cases"]["read_channel_backpressure"]["status"],
            "EXACT",
        )
        self.assertEqual(
            schedule["cases"]["write_channel_backpressure"]["status"],
            "BOUNDED_1_CYCLE",
        )
        for case in schedule["cases"].values():
            self.assertEqual(case["elapsed"]["max_abs_delta_cycles"], 0)
            self.assertEqual(
                case["external_data"]["max_abs_delta_cycles"], 0
            )
            self.assertEqual(case["child_output"]["max_abs_delta_cycles"], 0)
        hardware = evidence["hardware_holdout"]
        self.assertEqual(len(hardware["cases"]), 11)
        self.assertGreater(
            hardware["group_summary"]["calibration"][
                "median_abs_error_improvement_pct_points"
            ],
            0,
        )
        self.assertGreater(
            hardware["group_summary"]["holdout"][
                "median_abs_error_improvement_pct_points"
            ],
            0,
        )
        for case in hardware["cases"]:
            stats = case["axi_stats"]
            self.assertEqual(
                stats["maintenance_axi_requests_accepted"],
                stats["maintenance_axi_requests_completed"],
            )
            self.assertEqual(
                stats["maintenance_axi_beats_issued"],
                stats["maintenance_axi_beats_completed"],
            )
            self.assertLessEqual(
                stats["maintenance_axi_max_outstanding_bursts"], 16
            )

    def test_comparison_rejects_changed_logical_traffic(self) -> None:
        before_source = MODULE.DEFAULT_BEFORE / "runs/cal_zero/summary.json"
        after_source = MODULE.DEFAULT_AFTER / "runs/cal_zero/summary.json"
        before_row = next(
            row
            for row in MODULE.read_csv(MODULE.DEFAULT_BEFORE / "matrix.csv")
            if row["case_id"] == "cal_zero"
        )
        after_row = next(
            row
            for row in MODULE.read_csv(MODULE.DEFAULT_AFTER / "matrix.csv")
            if row["case_id"] == "cal_zero"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before_dir = root / "before"
            after_dir = root / "after"
            for target, row in ((before_dir, before_row), (after_dir, after_row)):
                target.mkdir()
                with (target / "matrix.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as stream:
                    writer = csv.DictWriter(stream, fieldnames=row.keys())
                    writer.writeheader()
                    writer.writerow(row)
                (target / "runs/cal_zero").mkdir(parents=True)
            before = json.loads(before_source.read_text(encoding="utf-8"))
            after = json.loads(after_source.read_text(encoding="utf-8"))
            after["maintenance_graph_write_bytes"] += 8
            (before_dir / "runs/cal_zero/summary.json").write_text(
                json.dumps(before), encoding="utf-8"
            )
            (after_dir / "runs/cal_zero/summary.json").write_text(
                json.dumps(after), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "logical ledger changed"):
                MODULE.compare_matrices(before_dir, after_dir)

    def test_trace_parser_rejects_missing_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.log"
            trace.write_text(
                "AXI_CORE_EVENT kind=child_request op=0 index=0 cycle=1\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "two summaries"):
                MODULE.parse_core_trace(trace)


if __name__ == "__main__":
    unittest.main()
