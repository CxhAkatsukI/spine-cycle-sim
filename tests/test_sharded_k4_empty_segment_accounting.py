"""Data-only explanation of frozen work; no fitted timing or new executor."""

import copy
import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.sensitivity import accounting


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4"


class EmptySegmentAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen_basis = json.loads((DOC / "matched_a4/sssp_partition_round/evidence/results.json").read_text())
        cls.frozen_sensitivity = json.loads((DOC / "adapter_optimization/empty_segment/sensitivity/evidence/results.json").read_text())
        cls.frozen_profile = json.loads((ROOT / "configs/architectures/grasu_regraph_routed_sssp_compute_v4.json").read_text())

    def setUp(self):
        self.basis = copy.deepcopy(self.frozen_basis)
        self.sensitivity = copy.deepcopy(self.frozen_sensitivity)
        self.profile = copy.deepcopy(self.frozen_profile)

    def derive(self):
        return accounting.derive(self.basis, self.sensitivity, self.profile)

    def test_exact_frozen_read_accounting_and_claim_limits(self):
        report = self.derive()
        self.assertEqual(report["traffic"]["a4_reads"], {
            "edges": 11613696, "source_state": 4784128, "old_state": 1048576})
        self.assertEqual(report["traffic"]["k4_reads"], {
            "extent": 256, "rows": 66059008, "segments": 30439168,
            "source_state": 4194304, "old_state": 1048576})
        self.assertEqual(report["traffic"]["k4_over_a4_read_bytes"], 101741312 / 17446400)
        self.assertEqual(report["traffic"]["a4_physical_slots"], 1451712)
        self.assertEqual(report["traffic"]["k4_physical_slots"], 7609792)
        for key in ("hardware_timing_admitted", "exclusive_stage_attribution_admitted",
                    "strict_resource_match_admitted", "production_model_modified", "numerical_executor_rerun"):
            self.assertIs(report[key], False)

    def test_serial_floor_changes_limiting_worker_without_fitting(self):
        report = self.derive()
        legacy = max(report["worker_floors"]["73"], key=lambda r: r["serial_model_floor"])
        zero = max(report["worker_floors"]["0"], key=lambda r: r["serial_model_floor"])
        self.assertEqual((legacy["worker"], legacy["serial_model_floor"]), (3, 22592644))
        self.assertEqual((zero["worker"], zero["serial_model_floor"]), (0, 16583591))
        self.assertEqual(zero["occupied_row_first_read_floor"], 179508 * 71)
        self.assertEqual(zero["row_group_read_floor"], 32256 * 71)
        self.assertEqual(zero["row_control_floor"], 258046 * 6)
        self.assertEqual(zero["empty_helper_floor"], 0)
        self.assertEqual(len(report["cases"]), 12)
        for case in report["cases"]:
            self.assertLessEqual(case["serial_model_floor"], case["k4_cycles"])
            self.assertEqual(case["floor_worker"], 0 if case["empty_exit"] == 0 else 3)

    def test_each_traffic_category_and_write_publication_is_checked(self):
        for path, keys in ((0, ("edge_read_bytes", "source_read_bytes", "read_bytes", "write_bytes",
                              "physical_edges", "dummy_edges", "replicas")),
                           (1, ("extent_reads", "row_reads", "segment_reads", "source_lines", "read_bytes",
                                "write_bytes", "physical_packets", "live_edges", "dummy_edges", "replicas"))):
            for key in keys:
                with self.subTest(path=path, key=key):
                    rows = copy.deepcopy(self.basis["cases"][0]["paths"])
                    rows[path][key] += 1
                    with self.assertRaises(ValueError):
                        accounting.traffic(*rows, self.basis["inputs"][0], self.basis["layout_audit"])

    def test_unsupported_timing_or_layout_contract_is_rejected(self):
        for key in ("adapter_min_read_to_use", "adapter_row_control", "adapter_empty_segment_exit_cycles"):
            for value in (0, 72, 71.0, True):
                with self.subTest(key=key, value=value):
                    profile = copy.deepcopy(self.profile["fixed_model"])
                    profile[key] = value
                    with self.assertRaises(ValueError):
                        accounting.worker_floors(self.basis["layout_audit"], profile, 0)
        for key, value in (("prefetch_rows", 1), ("stop_after_last", False), ("segment_slots", 8)):
            with self.subTest(key=key):
                layout = copy.deepcopy(self.basis["layout_audit"])
                layout["assumptions"][key] = value
                with self.assertRaises(ValueError):
                    accounting.worker_floors(layout, self.profile["fixed_model"], 0)

    def test_duplicate_shard_and_inconsistent_work_are_rejected(self):
        for key, value in (("partition", 1), ("empty_rows_visited", 0), ("row_read_requests", 1),
                           ("segments", 1), ("physical_slots", 1), ("dummy_slots", 1)):
            with self.subTest(key=key):
                layout = copy.deepcopy(self.basis["layout_audit"])
                layout["partitions"][0][key] = value
                with self.assertRaises(ValueError):
                    accounting.worker_floors(layout, self.profile["fixed_model"], 0)

    def test_counts_do_not_accept_boolean_float_negative_or_null(self):
        for value in (True, 1.0, -1, None):
            with self.subTest(value=value):
                layout = copy.deepcopy(self.basis["layout_audit"])
                layout["partitions"][0]["rows_visited"] = value
                with self.assertRaises(ValueError):
                    accounting.worker_floors(layout, self.profile["fixed_model"], 0)
                counters = copy.deepcopy(self.basis["cases"][0]["paths"])
                counters[1]["source_lines"] = value
                with self.assertRaises(ValueError):
                    accounting.traffic(*counters, self.basis["inputs"][0], self.basis["layout_audit"])

    def test_existing_registration_and_latency_admission_remains_required(self):
        self.sensitivity["cases"].pop()
        with self.assertRaises(ValueError):
            self.derive()

    def test_too_short_cycle_count_cannot_be_explained_by_this_floor(self):
        for row in self.sensitivity["cases"]:
            if row["empty_exit"] == 0:
                row["counters"]["cycles"] = 100
        # Keep the original positive latency sensitivity gate, independently of
        # the new floor gate, so the rejection is specifically about the floor.
        for row in self.sensitivity["cases"]:
            if row["empty_exit"] == 0 and row["latency"] == 128:
                row["counters"]["cycles"] = 200
        with self.assertRaisesRegex(ValueError, "violate serial floor"):
            self.derive()


if __name__ == "__main__":
    unittest.main()
