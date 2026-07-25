from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import statistics
import unittest

from spine_cycle_sim.calibration.grasu_native import (
    COMPONENT_TARGETS,
    SUMMARY_TARGETS,
    fit_native_timing_model,
    load_native_timing_records,
    native_group_summary,
    native_prediction_rows,
    native_timing_model_to_dict,
    parse_native_hardware_log,
)


ROOT = Path(__file__).resolve().parents[1]


class NativeTimingEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = load_native_timing_records()
        cls.model = fit_native_timing_model(cls.records)
        cls.rows = native_prediction_rows(cls.model, cls.records)

    def test_frozen_evidence_has_five_calibration_and_five_holdout(self) -> None:
        self.assertEqual(sum(record.role == "calibration" for record in self.records), 5)
        self.assertEqual(sum(record.role == "holdout" for record in self.records), 5)

    def test_tiny_cases_have_repeats_and_large_cases_remain_single_sample(self) -> None:
        counts = {record.case: record.hardware_samples for record in self.records}
        self.assertEqual(counts["tiny_chain_v16"], 6)
        self.assertEqual(counts["tiny_hotdst_v64_u32"], 6)
        self.assertEqual(counts["medium_star_v65536_u8192"], 1)
        self.assertEqual(counts["medium_spread_v65536_u16384"], 1)

    def test_repeat_variability_is_exposed(self) -> None:
        repeated = [record for record in self.records if record.hardware_samples > 1]
        self.assertTrue(all(record.update_cv_pct > 10.0 for record in repeated))
        self.assertTrue(all(record.compute_span_cv_pct < 4.0 for record in repeated))

    def test_all_four_envelopes_are_present_and_nonnegative(self) -> None:
        self.assertEqual(
            set(self.model.envelopes), {*COMPONENT_TARGETS, "event_gap"}
        )
        for envelope in self.model.envelopes.values():
            self.assertGreaterEqual(envelope.intercept_cycles, 0.0)
            self.assertTrue(all(value >= 0.0 for value in envelope.coefficients))
            self.assertEqual(envelope.samples, 5)

    def test_holdout_never_changes_fit(self) -> None:
        poisoned = [
            dataclasses.replace(
                record,
                hardware_event_e2e_cycles=record.hardware_event_e2e_cycles * 1000,
                hardware_update_cycles=record.hardware_update_cycles * 1000,
            )
            if record.role == "holdout"
            else record
            for record in self.records
        ]
        refit = fit_native_timing_model(poisoned)
        self.assertEqual(refit.calibration_cases, self.model.calibration_cases)
        for target in self.model.envelopes:
            left = self.model.envelopes[target]
            right = refit.envelopes[target]
            self.assertAlmostEqual(left.intercept_cycles, right.intercept_cycles)
            self.assertEqual(left.coefficients, right.coefficients)

    def test_calibration_case_names_are_exact(self) -> None:
        self.assertEqual(
            set(self.model.calibration_cases),
            {
                "tiny_chain_v16",
                "tiny_star_v16_u12",
                "small_spread_v4096_u1024",
                "small_hotdst_v4096_u1024",
                "medium_star_v65536_u8192",
            },
        )

    def test_prediction_ledger_closes(self) -> None:
        for row in self.rows:
            self.assertAlmostEqual(float(row["ledger_closure_cycles"]), 0.0, places=6)
            expected = sum(
                float(row[f"{target}_calibrated_cycles"])
                for target in (*COMPONENT_TARGETS, "event_gap")
            )
            self.assertAlmostEqual(expected, float(row["event_e2e_calibrated_cycles"]))

    def test_baseline_is_optimistic_for_every_case(self) -> None:
        for row in self.rows:
            self.assertLess(float(row["event_e2e_baseline_signed_error_pct"]), 0.0)

    def test_holdout_e2e_gate(self) -> None:
        holdout = [row for row in self.rows if row["role"] == "holdout"]
        errors = [float(row["event_e2e_calibrated_absolute_error_pct"]) for row in holdout]
        self.assertLessEqual(statistics.median(errors), 5.0)
        self.assertLessEqual(max(errors), 10.0)

    def test_holdout_baseline_was_not_already_close(self) -> None:
        holdout = [row for row in self.rows if row["role"] == "holdout"]
        errors = [float(row["event_e2e_baseline_absolute_error_pct"]) for row in holdout]
        self.assertGreater(statistics.median(errors), 40.0)

    def test_component_limitations_remain_visible(self) -> None:
        holdout = [row for row in self.rows if row["role"] == "holdout"]
        update_errors = [
            float(row["update_calibrated_absolute_error_pct"]) for row in holdout
        ]
        self.assertGreater(max(update_errors), 30.0)

    def test_group_summary_keeps_roles_and_targets_separate(self) -> None:
        summary = native_group_summary(self.rows)
        self.assertEqual(
            {(row["role"], row["target"]) for row in summary},
            {(role, target) for role in ("calibration", "holdout", "all") for target in SUMMARY_TARGETS},
        )

    def test_serialized_model_labels_single_sample_event_window_claim(self) -> None:
        payload = native_timing_model_to_dict(self.model)
        self.assertEqual(payload["fit_role"], "calibration_only")
        self.assertEqual(
            payload["claim_class"], "hardware_event_window_calibrated_partial_repeats"
        )
        self.assertTrue(any("OpenCL event windows" in item for item in payload["limitations"]))
        self.assertTrue(any("one sample" in item for item in payload["limitations"]))

    def test_loader_rejects_invalid_role(self) -> None:
        with self.assertRaises(ValueError):
            load_native_timing_records(roles=("future",))

    def test_loader_rejects_missing_nonstress_result(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_native_timing_records(simulation_dir=ROOT / "does-not-exist")

    def test_committed_analysis_evidence_passes_holdout_gate(self) -> None:
        evidence = ROOT / "docs/evidence/grasu_native_timing_model"
        manifest = json.loads((evidence / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "PASS")
        self.assertFalse(manifest["holdout_used_for_fit"])
        self.assertEqual(
            manifest["claim_class"],
            "hardware_event_window_calibrated_partial_repeats",
        )
        self.assertLessEqual(
            manifest["holdout_event_e2e_median_absolute_error_pct"], 5.0
        )
        self.assertLessEqual(
            manifest["holdout_event_e2e_max_absolute_error_pct"], 10.0
        )


class NativeTimingLogParserTests(unittest.TestCase):
    def test_rejects_incomplete_and_failed_logs(self) -> None:
        with self.assertRaises(ValueError):
            parse_native_hardware_log("PURE_PIPELINE_RESULT status=PASS\n")
        with self.assertRaises(ValueError):
            parse_native_hardware_log(
                "PURE_PIPELINE_INPUT vertices=1\n"
                "PURE_PIPELINE_TIMING grasu_ms=1\n"
                "PURE_PIPELINE_RESULT status=FAIL mismatches=1\n"
            )

    def test_parses_committed_log(self) -> None:
        path = ROOT / "docs/evidence/grasu_native_hw_matrix/tiny_chain_v16.log"
        parsed = parse_native_hardware_log(path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["input"]["vertices"], 16)
        self.assertEqual(parsed["result"]["mismatches"], 0)
        self.assertGreater(parsed["timing_ms"]["event_e2e"], 0.0)


if __name__ == "__main__":
    unittest.main()
