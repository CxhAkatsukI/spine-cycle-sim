from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/collect_candidate10_m_axi_adapter_rtl_oracle.py"
SPEC = importlib.util.spec_from_file_location("candidate10_m_axi_adapter", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Candidate10MAxiAdapterOracleTest(unittest.TestCase):
    def test_matrix_covers_read_write_boundaries_and_pressure(self) -> None:
        self.assertGreaterEqual(len(MODULE.CASES), 29)
        self.assertEqual({case.op for case in MODULE.CASES}, {0, 1})
        self.assertTrue(any(case.start_word == 511 and case.beats == 17
                            for case in MODULE.CASES))
        self.assertGreaterEqual(
            sum(case.expect_outstanding_limit for case in MODULE.CASES), 3
        )
        self.assertGreaterEqual(
            sum(case.expect_backpressure for case in MODULE.CASES), 3
        )
        self.assertEqual(sum(case.expect_issue_throttle for case in MODULE.CASES), 1)

    def test_expected_bursts_split_at_length_and_4k(self) -> None:
        case = MODULE.AdapterCase("boundary", 0, 1, 511, 33, 64)
        self.assertEqual(MODULE.expected_bursts(case), [
            {"addr": 4088, "beats": 1},
            {"addr": 4096, "beats": 16},
            {"addr": 4224, "beats": 16},
        ])

    def test_expected_bursts_do_not_coalesce_child_requests(self) -> None:
        case = MODULE.AdapterCase("adjacent", 1, 2, 0, 8, 8)
        self.assertEqual(MODULE.expected_bursts(case), [
            {"addr": 0, "beats": 8},
            {"addr": 64, "beats": 8},
        ])

    def test_parse_oracle(self) -> None:
        summary, bursts = MODULE.parse_oracle(
            "AXI_ADAPTER_BURST op=0 index=0 addr=4088 beats=1 issue_cycle=7\n"
            "AXI_ADAPTER_RTL op=0 requests=1 errors=0\n"
        )
        self.assertEqual(summary, {"op": 0, "requests": 1, "errors": 0})
        self.assertEqual(bursts[0]["addr"], 4088)

    def test_parse_rejects_timeout(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            MODULE.parse_oracle("AXI_ADAPTER_TIMEOUT cycle=100")

    def test_repository_evidence_passes_when_present(self) -> None:
        evidence = (
            ROOT / "docs/evidence/"
            "candidate10_m_axi_adapter_rtl_oracle_20260726"
        )
        csv_path = evidence / "m_axi_adapter_oracle.csv"
        manifest_path = evidence / "manifest.json"
        if not csv_path.exists() or not manifest_path.exists():
            self.skipTest("adapter RTL evidence has not been collected")
        with csv_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(manifest["all_pass"])
        self.assertEqual(len(rows), len(MODULE.CASES))
        self.assertTrue(all(row["status"] == "PASS" for row in rows))
        self.assertEqual(
            max(int(row["max_outstanding"]) for row in rows), 16
        )


if __name__ == "__main__":
    unittest.main()
