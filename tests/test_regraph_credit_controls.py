import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.r_credits import admission
from spine_cycle_sim.experiments.evaluation_impact.r_credits.analysis import MATRIX, summarize


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / ("docs/experiments/comparisons/grasu_regraph_stage_validation/"
                    "evaluation_impact/evidence/r_convergence.json")


def fixture():
    reference = json.loads(REFERENCE.read_text())["r_rows"]
    old = {(r["latency"], r["reverse"], r["arm"]): r for r in reference}
    rows = []
    for latency, reverse, arm in MATRIX:
        template = arm if arm in ("a4", "cross_row", "candidate") else (
            "a4" if arm == "a4_io16" else "candidate")
        row = copy.deepcopy(old[(latency, reverse, template)])
        row["arm"] = arm
        row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]:
            part["arm"] = arm
        rows.append(row)
    return rows, reference


def states(active=True):
    return {unit: {"LoadState": "loaded", "ActiveState": "active" if active else "inactive",
                   "MemoryMax": str(bound * admission.GIB)}
            for unit, bound in admission.COMPETITORS.items()}


class CreditAnalysisTests(unittest.TestCase):
    def test_complete_matrix_is_sensitivity_not_admission(self):
        result = summarize(*fixture())
        self.assertEqual(result["legacy_rows_replayed_exactly"], 12)
        self.assertEqual(len(result["comparisons"]), 2)
        for gate in ("strict_resource_match_admitted", "hardware_timing_admitted",
                     "publication_match_admitted", "production_baseline_admitted",
                     "new_spine_comparison_executed"):
            self.assertIs(result[gate], False)

    def test_missing_duplicate_and_reordered_matrix_rejected(self):
        rows, reference = fixture()
        for changed in (rows[:-1], rows[:-1] + [rows[0]], list(reversed(rows))):
            with self.subTest(), self.assertRaisesRegex(ValueError, "28-row"):
                summarize(changed, reference)

    def test_legacy_cycle_and_traffic_drift_rejected(self):
        for field in ("cycles", "read_bytes", "write_bytes"):
            rows, reference = fixture()
            for row in rows:
                if row["latency"] == 64 and row["arm"] == "a4":
                    row["observations"]["result"][field] += 1
                    if field == "cycles":
                        row["observations"]["trajectory"][0]["cycles"] += 1
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "legacy"):
                summarize(rows, reference)

    def test_registration_order_drift_rejected(self):
        rows, reference = fixture()
        rows[10]["observations"]["result"]["read_bytes"] += 64
        with self.assertRaisesRegex(ValueError, "registration"):
            summarize(rows, reference)

    def test_missing_extra_or_mismatched_replica_rejected(self):
        for kind in ("missing", "extra", "hash", "bytes"):
            rows, reference = fixture()
            for row in rows:
                if row["arm"] != "candidate_both2":
                    continue
                output = row["outputs"]
                if kind == "missing":
                    output.pop()
                elif kind == "extra":
                    output.append(copy.deepcopy(output[0]))
                else:
                    output[0][kind if kind == "bytes" else "sha256"] = 0
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "replicas"):
                summarize(rows, reference)

    def test_changed_common_state_or_trajectory_rejected(self):
        for kind in ("state", "trajectory"):
            rows, reference = fixture()
            for row in rows:
                if row["arm"] != "candidate_both2":
                    continue
                if kind == "state":
                    for output in row["outputs"]:
                        output["sha256"] = "different"
                else:
                    row["observations"]["trajectory"][0]["active"] += 1
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "semantics"):
                summarize(rows, reference)

    def test_nonconverged_unclosed_and_wrong_arm_rejected(self):
        for kind in ("active", "cycles", "arm", "traffic"):
            rows, reference = fixture()
            for row in rows:
                if row["arm"] != "candidate_both2":
                    continue
                observation = row["observations"]
                if kind == "active":
                    observation["trajectory"][-1]["active"] = 1
                elif kind == "cycles":
                    observation["result"]["cycles"] += 1
                elif kind == "traffic":
                    observation["result"]["read_bytes"] = -1
                else:
                    observation["result"]["arm"] = "candidate"
                    for part in observation["trajectory"]:
                        part["arm"] = "candidate"
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                summarize(rows, reference)


class CreditAdmissionTests(unittest.TestCase):
    def test_fresh_units_reserve_the_declared_tool_budgets(self):
        bounds = admission.competitors("new-route.service", "new-cache.service", "new-search.service")
        active = {unit: {"LoadState": "loaded", "ActiveState": "active",
                        "MemoryMax": str(512 * 1024**2)} for unit in bounds}
        result = admission.decision(active, 81 * admission.GIB, bounds)
        self.assertEqual(result["required_bytes"], 82 * admission.GIB)
        self.assertEqual(set(result["reservations"]), set(bounds))
        self.assertFalse(result["admitted"])
        with self.assertRaisesRegex(ValueError, "complete competing"):
            admission.decision(states(), 251 * admission.GIB, bounds)

    def test_invalid_service_names_and_bounds_rejected(self):
        for units in (("x.service", "x.service", "z.service"),
                      ("x.scope", "y.service", "z.service"),
                      ("x.service", "bad name.service", "z.service")):
            with self.subTest(units=units), self.assertRaises(ValueError):
                admission.competitors(*units)
        for bound in (0, -1, 41, float("inf"), True):
            with self.subTest(bound=bound), self.assertRaises(ValueError):
                admission.decision({}, 251 * admission.GIB, {"x.service": bound})

    def test_wait_uses_fresh_units_not_old_names(self):
        bounds = admission.competitors("new-route.service", "new-cache.service", "new-search.service")
        terminal = {unit: {"LoadState": "loaded", "ActiveState": "inactive"} for unit in bounds}
        with patch.object(admission, "unit_state", side_effect=lambda unit: terminal[unit]) as probe, \
                patch.object(admission, "available_memory_bytes", return_value=28 * admission.GIB), \
                patch.object(admission.time, "monotonic", side_effect=[10, 12]):
            report = {}
            self.assertEqual(admission.wait(report, lambda: None, 100, bounds), 2)
            self.assertEqual([call.args[0] for call in probe.call_args_list], list(bounds))
            self.assertEqual(set(report["admission"]["reservations"]), set(bounds))

    def test_pending_build_limits_are_reserved(self):
        result = admission.decision(states(), 81 * admission.GIB)
        self.assertEqual(result["required_bytes"], 82 * admission.GIB)
        self.assertFalse(result["admitted"])
        self.assertTrue(admission.decision(states(), 82 * admission.GIB)["admitted"])

    def test_terminal_jobs_keep_original_process_and_reserve(self):
        self.assertFalse(admission.decision(states(False), 27 * admission.GIB)["admitted"])
        self.assertTrue(admission.decision(states(False), 28 * admission.GIB)["admitted"])

    def test_collected_service_keeps_reserve_without_infinite_reservation(self):
        absent = {unit: {"LoadState": "not-found", "ActiveState": "inactive",
                         "SubState": "dead", "MemoryMax": "infinity"}
                  for unit in admission.COMPETITORS}
        result = admission.decision(absent, 28 * admission.GIB)
        self.assertTrue(result["admitted"])
        self.assertTrue(all(value == 0 for value in result["reservations"].values()))
        first = next(iter(absent.values()))
        first["SubState"] = "running"
        with self.assertRaises(ValueError):
            admission.decision(absent, 251 * admission.GIB)

    def test_unknown_or_unbounded_competitor_fails_closed(self):
        for kind in ("missing", "state", "limit", "too_large"):
            changed = states()
            unit = next(iter(changed))
            if kind == "missing":
                changed.pop(unit)
            elif kind == "state":
                changed[unit]["ActiveState"] = "unknown"
            else:
                changed[unit]["MemoryMax"] = "0" if kind == "limit" else str(252 * admission.GIB)
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                admission.decision(changed, 251 * admission.GIB)

    def test_expired_wait_does_not_launch(self):
        report = {}
        with patch.object(admission, "unit_state", side_effect=lambda unit: states()[unit]), \
                patch.object(admission, "available_memory_bytes", return_value=27 * admission.GIB), \
                patch.object(admission.time, "monotonic", side_effect=[0, 1]):
            with self.assertRaisesRegex(RuntimeError, "no timing case launched"):
                admission.wait(report, lambda: None, 0)
        self.assertEqual(report["status"], "WAITING_FOR_SAFE_MEMORY")

    def test_invalid_wait_rejected(self):
        for limit in (-1, float("inf"), float("nan")):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                admission.wait({}, lambda: None, limit)

    def test_admitted_wait_returns_elapsed_for_cumulative_budget(self):
        with patch.object(admission, "unit_state", side_effect=lambda unit: states(False)[unit]), \
                patch.object(admission, "available_memory_bytes", return_value=28 * admission.GIB), \
                patch.object(admission.time, "monotonic", side_effect=[10, 12]):
            self.assertEqual(admission.wait({}, lambda: None, 100), 2)


if __name__ == "__main__":
    unittest.main()
