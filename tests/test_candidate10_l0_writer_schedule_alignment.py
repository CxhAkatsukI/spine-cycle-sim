from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/collect_candidate10_l0_writer_schedule_alignment.py"
SPEC = importlib.util.spec_from_file_location("writer_schedule_alignment", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Candidate10L0WriterScheduleAlignmentTest(unittest.TestCase):
    def test_repository_evidence_is_consistent(self) -> None:
        evidence = MODULE.collect(
            MODULE.DEFAULT_ORACLE,
            MODULE.DEFAULT_SCHEDULE_ON,
            MODULE.DEFAULT_SCHEDULE_OFF,
            MODULE.DEFAULT_HW_MATRIX,
            MODULE.DEFAULT_BASELINE_MATRIX,
        )
        self.assertEqual(evidence["rtl_oracle"]["cases"], 56)
        self.assertEqual(evidence["rtl_oracle"]["valid_ideal_cases"], 52)
        self.assertEqual(
            evidence["rtl_oracle"]["max_abs_prediction_error_cycles"], 0
        )
        self.assertEqual(evidence["execution_driven_ab"]["cycle_delta"], 483)
        self.assertTrue(evidence["execution_driven_ab"]["request_count_equal"])
        self.assertEqual(len(evidence["hardware_holdout"]["cases"]), 11)

    def test_ab_rejects_changed_traffic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            enabled = {
                "status": "PASS",
                "success": True,
                "candidate_l0_writer_rtl_schedule": True,
                "backend_requests": 1,
                "backend_traffic": {"read": 8},
            }
            disabled = {
                **enabled,
                "candidate_l0_writer_rtl_schedule": False,
                "backend_traffic": {"read": 16},
            }
            on_path = root / "on.json"
            off_path = root / "off.json"
            on_path.write_text(json.dumps(enabled), encoding="utf-8")
            off_path.write_text(json.dumps(disabled), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "traffic"):
                MODULE.summarize_ab(on_path, off_path)

    def test_hardware_summary_rejects_case_mismatch(self) -> None:
        fieldnames = [
            "case_id", "role", "input_edges", "unique_sources",
            "classify_blocks", "hardware_cycles", "simulated_cycles",
            "raw_error_pct", "status",
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current.csv"
            baseline = root / "baseline.csv"
            for path, case_id in ((current, "new"), (baseline, "old")):
                with path.open("w", encoding="utf-8", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerow({
                        "case_id": case_id,
                        "role": "holdout",
                        "input_edges": 1,
                        "unique_sources": 1,
                        "classify_blocks": 1,
                        "hardware_cycles": 10,
                        "simulated_cycles": 8,
                        "raw_error_pct": -20,
                        "status": "PASS",
                    })
            with self.assertRaisesRegex(RuntimeError, "different cases"):
                MODULE.summarize_hardware(current, baseline)


if __name__ == "__main__":
    unittest.main()
