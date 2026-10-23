"""Threshold restoration must not erase scope, precision or zero-active work."""

import copy
import json
import unittest

from test_figure_refresh_multialgorithm import complete_report
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm import (
    residual_followup as followup, study, validation,
)


def reports():
    previous = complete_report()
    previous["pins"] = [dict(path="/old/core/" + name, sha256=name)
                        for name in ("liboriginal_regraph_cycle.a", "libspine_cycle_core.a")]
    current = copy.deepcopy(previous)
    current["model"] = dict(residual_epsilon=study.residual_threshold(1e-6))
    for key in ("matrix", "rows"):
        current[key] = [r for r in current[key] if r["algorithm"] == "ResPR"]
    return current, previous


class ResidualThresholdFollowupTests(unittest.TestCase):
    def test_residual_gate_retains_legacy_precision_and_checks_explicit_identity(self):
        epsilon = study.residual_threshold(1e-6)
        actual, bound = validation.pagerank_threshold(
            dict(residual_epsilon=epsilon), dict(residual_epsilon=epsilon), 515281)
        self.assertEqual(actual, epsilon)
        self.assertGreater(bound, 3)
        old, old_bound = validation.pagerank_threshold({}, {}, 515281)
        self.assertEqual(old, study.residual_threshold(1e-5 / 515281))
        self.assertLess(old_bound, 6.668e-5)
        with self.assertRaisesRegex(ValueError, "model identity"):
            validation.pagerank_threshold(dict(residual_epsilon=epsilon), {}, 515281)
        with self.assertRaisesRegex(ValueError, "model identity"):
            validation.pagerank_threshold({}, dict(residual_epsilon=epsilon), 515281)
        for value in (None, "invalid", 0, -1, float("nan"), float("inf"), 1e100, 1e-100):
            with self.assertRaisesRegex(ValueError, "positive finite FP32"):
                validation.pagerank_threshold(dict(residual_epsilon=value), {}, 515281)

    def test_three_pair_followup_does_not_relax_nine_pair_delivery(self):
        current, _ = reports()
        self.assertEqual(len(validation.selection(current, {}, expected=followup.EXPECTED)), 3)
        with self.assertRaisesRegex(ValueError, "nine-pair"):
            validation.selection(current, {})
        current["rows"].pop()
        with self.assertRaisesRegex(ValueError, "requested"):
            validation.selection(current, {}, expected=followup.EXPECTED)

    def test_zero_active_and_unchanged_rank_remain_explicit(self):
        current, previous = reports()
        for row in current["rows"]:
            for arm in ("spine", "gr"):
                row[arm]["state_hashes"]["final"] = row[arm]["state_hashes"]["old_state"]
        text = ('CORRECTION_TRACE {"active_vertices":0}\n' + 'PR_ORACLE ' +
                json.dumps(dict(maximum_error=1e-6, l1_error=1e-5, l1_error_bound=1.0)))
        rows = followup.compare(current, previous, lambda _: text.encode())
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["correction_active_vertices"] == 0 and r["final_rank_equals_old"] for r in rows))
        with self.assertRaisesRegex(ValueError, "one raw"):
            followup.record(text + '\nCORRECTION_TRACE {}', "CORRECTION_TRACE ")

    def test_threshold_csv_is_stable_after_sorted_json_roundtrip(self):
        current, _ = reports()
        summary = dict(comparisons=validation.selection(current, dict(source_report_sha256="digest"),
            expected=followup.EXPECTED), threshold_comparison=[dict(z=1, a=2)])
        restored = json.loads(json.dumps(summary, sort_keys=True))
        self.assertEqual(followup.derived(summary), followup.derived(restored))

    def test_library_or_old_state_changes_are_not_threshold_only(self):
        current, previous = reports()
        current["pins"][0]["sha256"] = "changed"
        with self.assertRaisesRegex(ValueError, "library identities"):
            followup.compare(current, previous, lambda _: b"")
        current, previous = reports()
        for arm in ("spine", "gr"):
            current["rows"][0][arm]["state_hashes"]["old_state"] = "changed"
        with self.assertRaisesRegex(ValueError, "retain graph"):
            followup.compare(current, previous, lambda _: b"")

    def test_fixed_contract_cannot_be_replaced_by_size_normalization(self):
        current, previous = reports()
        current["model"]["residual_epsilon"] = 1e-5 / 515281
        with self.assertRaisesRegex(ValueError, "fixed per-vertex"):
            followup.compare(current, previous, lambda _: b"")


if __name__ == "__main__":
    unittest.main()
