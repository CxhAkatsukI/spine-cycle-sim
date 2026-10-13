"""Reject numerical drift, free replicas and incomplete metadata controls."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.preparation import (
    ARMS, CONTROLS, PREVIOUS, REPLICA_CHANNELS, baseline_value)
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.preparation import ARMS as BASE_ARMS


def fixture():
    previous = json.loads(PREVIOUS.read_text())
    declared = deepcopy(previous["contract"])
    declared["baseline_rows"] = [baseline_value(row) for row in previous["rows"]]
    rows = deepcopy(previous["rows"])
    for row in rows:
        row["observation"].update(diagnostics=None, resources=None)
    for row in list(rows):
        if row["arm"] != BASE_ARMS[2]:
            continue
        value = row["observation"]
        cycles = value["cycles"]
        value["diagnostics"] = {"sampling": "after every committed cycle; overlapping markers are not additive",
            "search_done": [cycles] * 4, "first_hot_update": [1, 1], "last_hot_update": [cycles] * 2,
            "cache_loaded": [1, 1], "write_started": [cycles] * 2,
            "hot_completed": [value["physical_updates"] // 2] * 2,
            "metadata_port_cycles": [cycles] * 4, "metadata_full_cycles": [0] * 4,
            "metadata_peak_parents": [1] * 4,
            "ports": [{"name": "stub-for-analysis-test", "channel": 0, "requests": 1, "responses": 1,
                "beats_issued": 1, "beats_completed": 1, "peak_bursts": 1, "burst_limit": 32,
                "read_bytes": value["read_bytes"], "write_bytes": value["write_bytes"]}]}
        value["resources"] = {"row_allocated_bytes": 4096, "binary_allocated_bytes": 2 * 1024**2,
            "allocated_bytes": 32 * 1024**2, "channel_span_bytes": 32 * 1024**2,
            "extra_metadata_bytes": 0, "used_channels": 10, "row_channels": [2] * 4,
            "binary_channels": [1] * 4}
        for arm in CONTROLS:
            new = deepcopy(row)
            new["arm"] = new["observation"]["arm"] = arm
            resource = new["observation"]["resources"]
            extra = 0
            for key, copy in (("row", arm in (CONTROLS[0], CONTROLS[2])),
                              ("binary", arm in (CONTROLS[1], CONTROLS[2]))):
                if copy:
                    resource[key + "_channels"] = list(REPLICA_CHANNELS)
                    extra += 4 * resource[key + "_allocated_bytes"]
            resource["extra_metadata_bytes"] = extra
            resource["allocated_bytes"] += extra
            resource["channel_span_bytes"] += extra
            resource["used_channels"] = 13
            rows.append(new)
    declared["matrix"] = [{key: row[key] for key in ("case", "latency", "arm")} for row in rows]
    return declared, rows


class MetadataLayoutTests(unittest.TestCase):
    def test_complete_scope_reports_bad_performance_without_admission(self):
        declared, rows = fixture()
        result = analyze(rows, declared)
        self.assertEqual(result["prediction_rows"], 72)
        self.assertEqual(result["baseline_exact_replay_rows"], 36)
        self.assertEqual(len(result["metadata_comparisons"]), 12)
        self.assertEqual(set(ARMS), {row["arm"] for row in rows})
        self.assertFalse(result["runtime_ten_percent_diagnostic_met"])
        self.assertTrue(result["replication_controls_only"])
        for key in ("production_baseline_admitted", "hardware_timing_admitted", "publication_match_admitted",
                    "host_inclusive_timing_admitted", "production_layout_changed"):
            self.assertFalse(result[key])
        self.assertEqual(result["control_ten_percent_diagnostic_met"], dict.fromkeys(CONTROLS, False))

    def test_observation_and_wrapper_replacement_must_exactly_replay(self):
        for key, value in (("cycles", 1), ("read_bytes", 0), ("binary_probes", 0)):
            declared, rows = fixture()
            rows[2]["observation"][key] = value
            with self.assertRaisesRegex(ValueError, "instrumentation changed"):
                analyze(rows, declared)
        declared, rows = fixture()
        rows[2]["state_sha256"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "instrumentation changed"):
            analyze(rows, declared)

    def test_missing_extra_or_undeclared_arm_is_rejected(self):
        declared, rows = fixture()
        for bad in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError): analyze(bad, declared)
        rows[-1]["arm"] = "magic-free-bank"
        with self.assertRaises(ValueError): analyze(rows, declared)

    def test_control_state_and_work_must_match(self):
        for key, value in (("pma_read_bytes", 0), ("row_reads", 0), ("cycles", 0)):
            declared, rows = fixture()
            rows[-1]["observation"][key] = value
            with self.assertRaises(ValueError): analyze(rows, declared)
        declared, rows = fixture()
        rows[-1]["state_sha256"] = "b" * 64
        with self.assertRaises(ValueError): analyze(rows, declared)

    def test_free_replication_or_wrong_placement_is_rejected(self):
        for key, value in (("extra_metadata_bytes", 0), ("allocated_bytes", 1),
                           ("row_channels", [0] * 4), ("binary_channels", [32] * 4),
                           ("used_channels", 24), ("row_allocated_bytes", 0)):
            declared, rows = fixture()
            rows[-1]["observation"]["resources"][key] = value
            with self.assertRaises(ValueError): analyze(rows, declared)

    def test_missing_diagnostic_traffic_or_non_drained_port_is_rejected(self):
        declared, rows = fixture()
        rows[-1]["observation"]["diagnostics"] = None
        with self.assertRaises(ValueError): analyze(rows, declared)
        for key, value in (("read_bytes", 0), ("responses", 0), ("peak_bursts", 33)):
            declared, rows = fixture()
            rows[-1]["observation"]["diagnostics"]["ports"][0][key] = value
            with self.assertRaises(ValueError): analyze(rows, declared)

    def test_control_failure_is_reported_without_filtering(self):
        declared, rows = fixture()
        rows[-1]["observation"]["cycles"] *= 2
        result = analyze(rows, declared)
        self.assertEqual(result["prediction_rows"], 72)
        self.assertFalse(result["control_ten_percent_diagnostic_met"][CONTROLS[-1]])

    def test_parent_pressure_includes_exactly_one_staged_input(self):
        declared, rows = fixture()
        rows[-1]["observation"]["diagnostics"]["metadata_peak_parents"] = [33] * 4
        analyze(rows, declared)
        rows[-1]["observation"]["diagnostics"]["metadata_peak_parents"] = [34] * 4
        with self.assertRaisesRegex(ValueError, "pressure"):
            analyze(rows, declared)


if __name__ == "__main__":
    unittest.main()
