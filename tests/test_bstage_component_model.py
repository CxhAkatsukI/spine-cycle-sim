from __future__ import annotations

import unittest
from pathlib import Path

from spine_cycle_sim.calibration import (
    COMPONENT_ORDER,
    WHATIF_ORDER,
    CaseRecord,
    classify_trust,
    evidence_note,
    fit_carry_residual,
    fit_component_model,
    fit_l0_model,
    group_summary,
    load_default_evidence,
    model_to_dict,
    prediction_field_order,
    prediction_row,
)

ROOT = Path(__file__).resolve().parents[1]

# Calibration L0 evidence: (case, active_parts, edges, cycles, jitter_pct).
_L0_16PART = [
    ("l0_store_e256", 16, 256, 993021.74, 5.56),
    ("l0_store_e1024", 16, 1024, 3720751.2, 0.46),
    ("l0_store_e4096", 16, 4096, 14697924.0, 0.05),
    ("l0_store_e16384", 16, 16384, 58646976.0, 0.09),
    ("l0_store_e65536", 16, 65536, 234403520.0, 0.01),
    ("l0_store_e131072", 16, 131072, 468752100.0, 0.01),
]
_L0_ONEPART = [
    ("phase4c_l0_onepart_e10", 1, 10, 32264.52, 9.03),
    ("phase4c_l0_onepart_e80", 1, 80, 57251.098, 17.84),
    ("phase4c_l0_onepart_e512", 1, 512, 171331.06, 3.33),
    ("phase4c_l0_onepart_e4096", 1, 4096, 1104260.5, 0.385),
    ("phase4c_l0_onepart_e32768", 1, 32768, 8539578.8, 0.072),
    ("phase4c_l0_onepart_e98304", 1, 98304, 25539060.0, 0.017),
]
# Calibration carry evidence: (case, target, edges, sources, cycles).
_CARRY = [
    ("carry_l1_batch_e1024_s64", 1, 1024, 64, 2868658.6),
    ("carry_l1_batch_e4096_s64", 1, 4096, 64, 11149094.8),
    ("carry_l1_batch_e65536_s64", 1, 65536, 64, 177156039.99),
    ("carry_target_l2_e4096_s64", 2, 4096, 64, 12473095.2),
    ("carry_target_l4_e4096_s64", 4, 4096, 64, 20311184.0),
]
# Real one-partition holdout slices: (case, edges, cycles).
_REAL = [
    ("amazon_top512_exact", 5120, 10.1398 * 134_000),
    ("amazon_top4096_exact", 40960, 79.4461 * 134_000),
    ("amazon_stride4096_exact", 32571, 63.2189 * 134_000),
]


def _l0_record(case, active, edges, cycles, jitter, role="calibration", group="synthetic"):
    return CaseRecord(
        group=group,
        role=role,
        case=case,
        mode="l0_store",
        target_level=0,
        batch_edges=edges,
        active_partitions=active,
        source_count=1,
        pages_epoch_stamped=active,
        actual_cycles=cycles,
        jitter_pct=jitter,
    )


def _carry_record(case, target, edges, sources, cycles, role="calibration"):
    return CaseRecord(
        group="synthetic",
        role=role,
        case=case,
        mode="carry",
        target_level=target,
        batch_edges=edges,
        active_partitions=16,
        source_count=sources,
        pages_epoch_stamped=16,
        actual_cycles=cycles,
        jitter_pct=0.1,
    )


def _calibration_records():
    records = [_l0_record(*row) for row in _L0_16PART]
    records += [_l0_record(*row) for row in _L0_ONEPART]
    records += [_carry_record(*row) for row in _CARRY]
    return records


class L0ModelFitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = fit_l0_model([_l0_record(*row) for row in _L0_16PART + _L0_ONEPART])

    def test_all_coefficients_positive(self) -> None:
        self.assertGreater(self.model.fixed, 0.0)
        self.assertGreater(self.model.c_part, 0.0)
        self.assertGreater(self.model.c_edge, 0.0)
        self.assertGreater(self.model.c_edge_part, 0.0)

    def test_per_partition_edge_cost_dominates_per_edge_cost(self) -> None:
        # The active-partition filter+write composite is far more expensive than
        # the shared per-edge scan -- this is what makes a 16-partition star cost
        # ~13x a one-partition slice.
        self.assertGreater(self.model.c_edge_part, self.model.c_edge * 3)

    def test_large_calibration_cases_within_two_percent(self) -> None:
        for case, active, edges, cycles, _ in _L0_16PART + _L0_ONEPART:
            if edges < 512:
                continue
            pred = self.model.total(edges, active)
            err = abs(pred - cycles) / cycles * 100.0
            self.assertLess(err, 2.0, f"{case}: {err:.2f}% error")

    def test_one_partition_model_predicts_real_slices(self) -> None:
        # The headline validation: a one-partition L0 model matches real exact
        # Amazon slices, whereas a 16-partition treatment would be ~13x too high.
        for case, edges, cycles in _REAL:
            pred_1p = self.model.total(edges, 1)
            pred_16p = self.model.total(edges, 16)
            err_1p = abs(pred_1p - cycles) / cycles * 100.0
            self.assertLess(err_1p, 2.0, f"{case}: 1-part {err_1p:.2f}% error")
            self.assertGreater(pred_16p / cycles, 10.0, f"{case}: 16-part not >10x")


class CarryResidualTests(unittest.TestCase):
    def test_residual_is_positive_and_corrects_bias(self) -> None:
        records = [_carry_record(*row) for row in _CARRY]
        residual = fit_carry_residual(records)
        self.assertGreater(residual, 0.0)

    def test_carry_predictions_within_three_percent(self) -> None:
        model = fit_component_model(_calibration_records())
        for case, target, edges, sources, cycles in _CARRY:
            record = _carry_record(case, target, edges, sources, cycles)
            pred = model.predicted_cycles(record)
            err = abs(pred - cycles) / cycles * 100.0
            self.assertLess(err, 3.0, f"{case}: {err:.2f}% error")


class ComponentModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = fit_component_model(_calibration_records())

    def test_components_sum_to_predicted_total(self) -> None:
        for record in _calibration_records():
            components = self.model.components(record)
            self.assertAlmostEqual(
                sum(components.values()),
                self.model.predicted_cycles(record),
                places=3,
            )

    def test_l0_component_keys_complete(self) -> None:
        record = _l0_record(*_L0_16PART[2])
        components = self.model.components(record)
        self.assertEqual(set(components), set(COMPONENT_ORDER))

    def test_l0_scan_split_is_one_to_sixteen(self) -> None:
        record = _l0_record(*_L0_16PART[2])
        components = self.model.components(record)
        hot_cold = components["hot_cold_input_scan"]
        family = components["family_precount_scan"]
        self.assertAlmostEqual(family / hot_cold, 16.0, places=6)

    def test_top_component_for_star_is_level_write_composite(self) -> None:
        prediction = self.model.predict(_l0_record(*_L0_16PART[3]))
        self.assertEqual(
            prediction["top_component"], "active_partition_filter_and_level_write"
        )

    def test_top_component_for_carry_is_family_filter_scan(self) -> None:
        prediction = self.model.predict(_carry_record(*_CARRY[2]))
        self.assertEqual(prediction["top_component"], "family_precount_scan")

    def test_whatifs_present_and_speedups_at_least_one(self) -> None:
        prediction = self.model.predict(_l0_record(*_L0_16PART[3]))
        self.assertEqual(set(prediction["whatifs"]), set(WHATIF_ORDER))
        for name, entry in prediction["whatifs"].items():
            self.assertGreaterEqual(entry["speedup"], 1.0, name)
            self.assertGreater(entry["cycles"], 0.0, name)

    def test_single_partition_whatif_large_for_star_small_for_onepart(self) -> None:
        star = self.model.predict(_l0_record(*_L0_16PART[3]))
        onepart = self.model.predict(_l0_record(*_L0_ONEPART[4]))
        self.assertGreater(star["whatifs"]["l0_single_active_partition"]["speedup"], 10.0)
        self.assertAlmostEqual(
            onepart["whatifs"]["l0_single_active_partition"]["speedup"], 1.0, places=6
        )

    def test_carry_single_partition_whatif_is_noop(self) -> None:
        prediction = self.model.predict(_carry_record(*_CARRY[2]))
        self.assertAlmostEqual(
            prediction["whatifs"]["l0_single_active_partition"]["speedup"], 1.0, places=6
        )


class ClassificationTests(unittest.TestCase):
    def test_trust_thresholds(self) -> None:
        self.assertEqual(classify_trust(0.0), "trusted")
        self.assertEqual(classify_trust(15.0), "trusted")
        self.assertEqual(classify_trust(15.01), "borderline")
        self.assertEqual(classify_trust(30.0), "borderline")
        self.assertEqual(classify_trust(30.01), "untrusted")

    def test_evidence_note_flags_tiny_and_jittery_cases(self) -> None:
        tiny = _l0_record("t", 1, 10, 32264.0, 9.03)
        note = evidence_note(tiny)
        self.assertIn("tiny_case_edges_lt_512", note)
        self.assertIn("high_jitter", note)

    def test_evidence_note_marks_holdout(self) -> None:
        record = _l0_record("h", 1, 4096, 1_000_000.0, 0.1, role="holdout")
        self.assertIn("holdout", evidence_note(record))

    def test_large_clean_case_has_no_warning_note(self) -> None:
        record = _l0_record("c", 16, 4096, 14_697_924.0, 0.05)
        self.assertEqual(evidence_note(record), "")


class CsvShapingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = fit_component_model(_calibration_records())

    def test_prediction_row_has_all_required_columns(self) -> None:
        prediction = self.model.predict(_l0_record(*_L0_16PART[2]))
        row = prediction_row(prediction)
        order = prediction_field_order()
        self.assertEqual(set(row), set(order))
        required = {
            "group", "role", "case", "mode", "target_level", "batch_edges",
            "active_partitions", "pages_epoch_stamped", "actual_cycles",
            "predicted_cycles", "error_pct", "abs_error_pct", "trusted_status",
            "evidence_note", "top_component", "top_component_cycles",
        }
        self.assertTrue(required.issubset(set(order)))
        for name in COMPONENT_ORDER:
            self.assertIn(f"comp_{name}_cycles", row)
            self.assertIn(f"comp_{name}_share", row)
        for name in WHATIF_ORDER:
            self.assertIn(f"whatif_{name}_cycles", row)
            self.assertIn(f"whatif_{name}_speedup", row)

    def test_component_shares_sum_to_one(self) -> None:
        prediction = self.model.predict(_l0_record(*_L0_16PART[2]))
        row = prediction_row(prediction)
        total_share = sum(row[f"comp_{name}_share"] for name in COMPONENT_ORDER)
        self.assertAlmostEqual(total_share, 1.0, places=6)

    def test_group_summary_counts_records(self) -> None:
        predictions = [self.model.predict(r) for r in _calibration_records()]
        summaries = group_summary(predictions)
        total = sum(s["cases"] for s in summaries)
        self.assertEqual(total, len(_calibration_records()))
        for summary in summaries:
            self.assertEqual(
                summary["cases"],
                summary["trusted"] + summary["borderline"] + summary["untrusted"],
            )

    def test_model_to_dict_records_form_and_thresholds(self) -> None:
        payload = model_to_dict(self.model)
        self.assertIn("edges*active_parts*c_edge_part", payload["l0_model"]["form"])
        self.assertEqual(payload["trust_thresholds"]["trusted_max_abs_pct"], 15.0)
        self.assertEqual(payload["component_order"], COMPONENT_ORDER)


class EvidenceLoadingTests(unittest.TestCase):
    """Exercise the real evidence loaders when the directories are present."""

    def _evidence_available(self) -> bool:
        return (
            ROOT / "results" / "phase4c_bstage_phase2b_current_hw_20260720_111449"
        ).exists()

    def test_load_default_evidence_covers_all_roles_and_paths(self) -> None:
        if not self._evidence_available():
            self.skipTest("evidence directories not present")
        records = load_default_evidence(root=ROOT)
        groups = {r.group for r in records}
        self.assertEqual(
            groups,
            {"phase2b", "phase4c_onepart", "phase2d_holdout", "phase4a_amazon_real"},
        )
        real = [r for r in records if r.group == "phase4a_amazon_real"]
        self.assertTrue(real)
        self.assertTrue(all(r.active_partitions == 1 for r in real))
        self.assertTrue(all(r.mode == "l0_store" and r.target_level == 0 for r in real))

    def test_fitted_model_validates_holdout_within_thresholds(self) -> None:
        if not self._evidence_available():
            self.skipTest("evidence directories not present")
        records = load_default_evidence(root=ROOT)
        model = fit_component_model(records)
        # Every non-tiny holdout case should be trusted.
        for record in records:
            if record.role != "holdout" or record.batch_edges < 512:
                continue
            prediction = model.predict(record)
            self.assertLessEqual(
                prediction["abs_error_pct"], 15.0, f"{record.case} untrusted"
            )


if __name__ == "__main__":
    unittest.main()
