"""Cross-row arms conserve equal whole-line traffic without inheriting calibration."""

import copy
import unittest

import test_sharded_k4_row_line_model_validation as fixtures
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.model_contract import PROFILE_ID, TARGET
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.model_study import CROSS_ROW
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.cross_row.model_timing import SHAPES, compare


class CrossRowValidationTests(fixtures.RowLineModelValidationTests):
    def test_equal_whole_line_reads_required_in_both_arms(self):
        original = fixtures.result(self.geometry, "candidate")
        original["profile_id"] = PROFILE_ID
        candidate = copy.deepcopy(original)
        candidate["counters"]["end_cycle"] = 80
        report = CROSS_ROW.compare(original, candidate, self.geometry)
        self.assertEqual(report["arms"]["original"]["directory_bytes"], report["arms"]["candidate"]["directory_bytes"])
        self.assertFalse(report["hardware_timing_admitted"])
        for arm in (original, candidate):
            changed = copy.deepcopy(arm)
            changed["counters"]["row_reads"] += 1
            with self.assertRaises(ValueError):
                CROSS_ROW.compare(changed, candidate, self.geometry)


class CrossRowTimingTests(unittest.TestCase):
    def setUp(self):
        self.rows, self.rtl = [], {"arms": {"reference": [], "candidate": []},
            "status": "CROSS_ROW_PRODUCTION_AXI_PASS_NOT_ROUTED", "FPGA_timing_admitted": False,
            "xo": {"sha256": TARGET["candidate_adapter_xo_sha256"]}}
        for i, (v, placement, length, latency, stall) in enumerate(SHAPES):
            occupied = sum(placement == 0 or (placement == 1 and s + 1 == v) or
                           (placement == 2 and s == 0) or (placement == 3 and s % 7 == 0) for s in range(v))
            reads = occupied * length
            for arm, candidate in (("reference", False), ("candidate", True)):
                row = {"trial": i, "candidate": candidate, "adapter_done": 100,
                       "extent_reads": int(v != 0), "row_reads": int(v != 0), "segment_reads": reads,
                       "packets": reads * 2, "live_edges": reads * 10, "dummy_edges": reads * 6,
                       "exact_packets_and_traffic": True}
                self.rows.append(row)
                self.rtl["arms"][arm].append({"trial": i, "vertices": v, "placement": placement,
                    "length": length, "latency": latency, "stall": stall, "cycles": 200,
                    "row_requests": row["extent_reads"] + row["row_reads"], "pma_requests": reads,
                    "packets": reads * 2, "row_transfer_bytes": (row["extent_reads"] + row["row_reads"]) * 64,
                    "pma_transfer_bytes": reads * 64})

    def test_full_matrix_preserves_mismatch_without_fitting(self):
        report = compare(self.rows, self.rtl)
        self.assertEqual(len(report["rows"]), 24)
        self.assertFalse(report["all_rows_within_10_percent"])
        self.assertFalse(report["hardware_timing_admitted"])
        self.assertEqual(report["fitted_parameters"], [])
        self.assertTrue(all(row["absolute_percentage_error"] == 50 for row in report["rows"]))

    def test_missing_reordered_or_mismatched_rows_rejected(self):
        for rows in (self.rows[:-1], self.rows[::-1]):
            with self.assertRaises(ValueError):
                compare(rows, self.rtl)
        for key, value in (("packets", -1), ("exact_packets_and_traffic", False), ("adapter_done", 0)):
            rows = copy.deepcopy(self.rows)
            rows[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare(rows, self.rtl)

    def test_wrong_rtl_identity_or_tier_rejected(self):
        for key, value in (("xo", {"sha256": "0" * 64}), ("FPGA_timing_admitted", True),
                           ("status", "CROSS_ROW_PRODUCTION_AXI_PASS")):
            rtl = copy.deepcopy(self.rtl)
            rtl[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                compare(self.rows, rtl)


if __name__ == "__main__":
    unittest.main()
