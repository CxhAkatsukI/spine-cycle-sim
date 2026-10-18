"""Paired G analysis must use raw, complete, same-window hardware evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.matched_original import comparison
from spine_cycle_sim.experiments.evaluation_impact.common_g.matched_original.board import analysis
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import execution as original
from spine_cycle_sim.experiments.upstream_controls.grasu.host.fixtures import NAMES
from tests.test_matched_g_board import fixture, stdout


def board_fixture(root, *, production, wall_ms=0.01):
    root.mkdir()
    cases, rows, attempts, pins = [], [], [], []
    for name in ("host", "candidate.xclbin"):
        (root / name).write_text(name)
        pins.append(identity(root / name))
    for name in NAMES:
        case, _, _ = fixture()
        packet = root / (name + ".bin")
        packet.write_text(name)
        pins.append(identity(packet))
        cases.append({**case, "id": name, "expected_slots_including_guards": 100, "packet": identity(packet)})
    for repeat in range(3):
        for case in cases:
            name = case["id"]
            _, events, observation = fixture()
            label = f"r{repeat}_{name}"
            out, err = (root / (label + suffix) for suffix in (".stdout.txt", ".stderr.txt"))
            if production:
                observation.update(launch_wait_ms=wall_ms, g_ready_wall_ms=wall_ms + 0.04)
                out.write_text(stdout(events, observation))
                err.write_text("")
                observed = analysis.inspect(out.read_text(), "", case)
            else:
                original_events = [{"role": role, "queued": 1, "submitted": 2, "start": 3, "end": 10003}
                                   for role in sorted(original.analysis.ROLES)]
                original_row = {"status": "FULL_STATE_PASS", "bdf": "0000:01:00.1", "updates": 2,
                    "checked_slots_including_guards": 100, "kernel_event_span_ns": 10000,
                    "readback_in_wall": False, "host_preparation_in_wall": False, "events": 9,
                    "resident_wall_ms": 0.01}
                out.write_text("\n".join([*("ORIGINAL_G_EVENT " + json.dumps(event) for event in original_events),
                                           "ORIGINAL_G_BOARD " + json.dumps(original_row)]) + "\n")
                err.write_text("")
                observed = original.analysis.inspect(out, err, case, "0000:01:00.1")
            rows.append({"case": name, "repeat": repeat, "analysis": observed})
            attempts.append({"id": label, "exit_code": 0, "command": ["/usr/bin/taskset", "-c", "120",
                str(root / "host"), "--board", case["packet"]["path"], str(root / "candidate.xclbin"), "0"]})
            pins += [identity(out), identity(err)]
    report = {"status": comparison.execution.PASS if production else original.EXTERNAL_PASS, "errors": [],
        "boundary": analysis.BOUNDARY if production else original.analysis.BOUNDARY,
        "board_launch_attempted": True, "board_programmed": True, "hardware_timing_measured": True,
        "publication_performance_match": False, "final_figures_admitted": False,
        "profile": "original_g_external_port_v1", "source_modified": False, "physical_interconnect_changed": True,
        "runtime": {"device": {"bdf": "0000:01:00.1"}, "platform": {"name": "u55c"}, "pins": []},
        "device_index": 0, "repeats": 3, "rows": rows, "attempts": attempts, "pins": pins,
        "admission": {"status": "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD", "clock_topology_connectivity_equal": True}}
    summarize = analysis.summaries if production else original.analysis.summaries
    report["summaries"] = summarize(rows, NAMES, 3)
    (root / "results.json").write_text(json.dumps(report))
    return report, cases


def paired_fixture(root, *, wall_ms=0.01):
    old, cases = board_fixture(root / "old", production=False)
    new, _ = board_fixture(root / "new", production=True, wall_ms=wall_ms)
    library = root / "libxilinxopencl.so"
    library.write_text("same runtime")
    for report in (old, new):
        report["runtime"]["pins"] = [identity(library)]
        report["pins"].append(identity(library))
    new["pins"] += [case["packet"] for case in cases]
    by_name = {case["id"]: case for case in cases}
    for attempt in new["attempts"]:
        attempt["command"][5] = by_name[attempt["id"].split("_", 1)[1]]["packet"]["path"]
    return old, new, cases


def run_paired(root, old, new, cases, output="out"):
    for name, report in (("old", old), ("new", new)):
        (root / name / "results.json").write_text(json.dumps(report))
    with patch.object(comparison.inputs, "load", return_value=(None, cases, [])), \
            patch.object(comparison.original, "inputs", return_value=(None, cases, [])):
        return comparison.run(root / "old", root / "new", root, root, root / output,
            original_board_sha256=identity(root / "old/results.json")["sha256"],
            production_board_sha256=identity(root / "new/results.json")["sha256"],
            original_preflight_sha256="a" * 64, production_preflight_sha256="b" * 64)


class MatchedGComparisonTests(unittest.TestCase):
    def test_complete_run_keeps_match_separate_from_publication_and_figures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, new, cases = paired_fixture(root)
            report = run_paired(root, old, new, cases)
            self.assertEqual(report["errors"], [])
            self.assertEqual(len(report["rows"]), 8)
            self.assertTrue(report["hardware_timing_measured"])
            self.assertTrue(report["same_platform_resident_match"])
            self.assertTrue(report["same_platform_kernel_span_match"])
            self.assertEqual(report["mismatch_cases"], [])
            self.assertFalse(report["publication_performance_match"])
            self.assertFalse(report["final_figures_admitted"])

    def test_valid_mismatch_is_retained_not_promoted_or_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, new, cases = paired_fixture(root, wall_ms=0.02)
            report = run_paired(root, old, new, cases)
            self.assertEqual(report["errors"], [])
            self.assertFalse(report["same_platform_resident_match"])
            self.assertTrue(report["same_platform_kernel_span_match"])
            self.assertEqual(report["mismatch_cases"], list(NAMES))
            self.assertEqual(report["rows"][0]["resident_wall"]["production_over_original_time"], 2)
            self.assertFalse(report["publication_performance_match"])

    def test_paired_platform_runtime_and_repetition_mismatch_rejected(self):
        for key in ("device", "platform", "runtime", "repeats"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                old, new, cases = paired_fixture(root)
                if key in ("device", "platform"):
                    new["runtime"][key]["changed"] = True
                elif key == "runtime":
                    new["runtime"]["pins"] = []
                else:
                    new["repeats"] = 4
                with self.assertRaises(ValueError):
                    run_paired(root, old, new, cases)
                report = json.loads((root / "out/results.json").read_text())
                self.assertEqual(report["status"], "FAILED_RETAINED")
                self.assertFalse(report["hardware_timing_measured"])

    def test_complete_raw_matrices_replay_and_compare(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, cases = board_fixture(root / "old", production=False)
            new, new_cases = board_fixture(root / "new", production=True)
            for path, production in ((root / "old", False), (root / "new", True)):
                replayed, rows, pins = comparison.replay(path, identity(path / "results.json")["sha256"],
                                                       new_cases if production else cases,
                                                       production=production, host_pins=[])
                self.assertEqual(rows, replayed["rows"])
                self.assertEqual(len(pins), 59)
            result = comparison.compare_rows(old["rows"], new["rows"], cases, 3)
            self.assertEqual([row["case"] for row in result], list(NAMES))
            self.assertTrue(all(row["resident_wall"]["within_10_percent"] for row in result))
            self.assertEqual(result[0]["resident_wall"]["production_over_original_time"], 1)
            self.assertTrue(result[0]["production_publication_barrier_included"])

    def test_comparison_uses_launch_wait_not_inclusive_g_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, cases = board_fixture(root / "old", production=False)
            new, _ = board_fixture(root / "new", production=True)
            new["rows"][0]["analysis"]["observation"].update(launch_wait_ms=0.02, g_ready_wall_ms=100)
            new["rows"][8]["analysis"]["observation"].update(launch_wait_ms=0.03, g_ready_wall_ms=200)
            new["rows"][16]["analysis"]["observation"].update(launch_wait_ms=0.04, g_ready_wall_ms=300)
            result = comparison.compare_rows(old["rows"], new["rows"], cases, 3)
            self.assertEqual(result[0]["resident_wall"]["production_over_original_time"], 3)
            self.assertFalse(result[0]["resident_wall"]["within_10_percent"])
            self.assertTrue(result[0]["kernel_span"]["within_10_percent"])

    def test_empty_update_case_has_latency_but_no_throughput_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, cases = board_fixture(root / "old", production=False)
            new, _ = board_fixture(root / "new", production=True)
            cases[0]["facts"]["updates"] = 0
            row = comparison.compare_rows(old["rows"], new["rows"], cases, 3)[0]
            self.assertFalse(row["throughput_ratio_defined"])
            self.assertEqual(row["resident_wall"]["production_over_original_time"], 1)

    def test_ten_percent_endpoint_includes_float_roundoff_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, cases = board_fixture(root / "old", production=False)
            new, _ = board_fixture(root / "new", production=True, wall_ms=0.011)
            self.assertTrue(comparison.compare_rows(old["rows"], new["rows"], cases, 3)[0]
                            ["resident_wall"]["within_10_percent"])
            for row in new["rows"]:
                row["analysis"]["observation"]["launch_wait_ms"] = 0.01100001
            self.assertFalse(comparison.compare_rows(old["rows"], new["rows"], cases, 3)[0]
                             ["resident_wall"]["within_10_percent"])

    def test_incomplete_duplicate_and_invalid_timings_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, cases = board_fixture(root / "old", production=False)
            new, _ = board_fixture(root / "new", production=True)
            for changes in (new["rows"][:-1], new["rows"] + new["rows"][:1], new["rows"][:1] * 24):
                with self.assertRaises(ValueError):
                    comparison.compare_rows(old["rows"], changes, cases, 3)
            for value in (0, -1, True, float("inf"), float("nan")):
                changed = copy.deepcopy(new["rows"])
                changed[0]["analysis"]["observation"]["launch_wait_ms"] = value
                with self.subTest(value=value), self.assertRaises(ValueError):
                    comparison.compare_rows(old["rows"], changed, cases, 3)
            for count in (True, 2, 11):
                with self.assertRaises(ValueError):
                    comparison.compare_rows(old["rows"], new["rows"], cases, count)

    def test_report_schema_summary_raw_pins_and_affinity_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, cases = board_fixture(root / "new", production=True)
            for change in (
                lambda row: row.update(status="RUNNING"),
                lambda row: row.update(boundary="setup_inclusive"),
                lambda row: row.update(errors=["failure"]),
                lambda row: row.update(board_programmed=False),
                lambda row: row.update(final_figures_admitted=True),
                lambda row: row.update(pins=row["pins"][:-1]),
                lambda row: row["pins"].append({**row["pins"][0], "sha256": "0" * 64}),
                lambda row: row["runtime"].update(pins=[{"path": "/unpinned.so", "sha256": "0" * 64}]),
                lambda row: row["attempts"][0].update(exit_code=True),
                lambda row: row["attempts"][0].update(command=["host"]),
                lambda row: row["attempts"][0]["command"].__setitem__(5, "/different-input"),
                lambda row: row["attempts"][0]["command"].__setitem__(6, "/unpinned-artifact"),
                lambda row: row.update(device_index=True),
                lambda row: row["rows"][0]["analysis"]["observation"].update(launch_wait_ms=1),
                lambda row: row["summaries"][0].update(median_launch_wait_ms=1),
                lambda row: row["admission"].update(clock_topology_connectivity_equal=False),
            ):
                changed = copy.deepcopy(report)
                change(changed)
                (root / "new/results.json").write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    comparison.replay(root / "new", identity(root / "new/results.json")["sha256"], cases,
                                      production=True, host_pins=[])

    def test_original_source_modification_and_hidden_physical_change_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, cases = board_fixture(root / "old", production=False)
            for changes in ({"source_modified": True}, {"physical_interconnect_changed": False},
                            {"status": original.PASS}):
                (root / "old/results.json").write_text(json.dumps({**report, **changes}))
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    comparison.replay(root / "old", identity(root / "old/results.json")["sha256"],
                                      cases, production=False, host_pins=[])

    def test_report_digest_host_pins_and_raw_file_changes_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, cases = board_fixture(root / "new", production=True)
            digest = identity(root / "new/results.json")["sha256"]
            for supplied in ("latest", "0" * 64):
                with self.assertRaises(ValueError):
                    comparison.replay(root / "new", supplied, cases, production=True, host_pins=[])
            with self.assertRaises(ValueError):
                comparison.replay(root / "new", digest, cases, production=True,
                                  host_pins=[{"path": "/missing", "sha256": "a" * 64}])
            (root / "new/r0_empty_graph.stdout.txt").write_text("changed")
            with self.assertRaises(ValueError):
                comparison.replay(root / "new", digest, cases, production=True, host_pins=[])

    def test_run_retains_failure_before_reporting_measurement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(comparison.inputs, "load", side_effect=ValueError("host changed")):
                with self.assertRaisesRegex(ValueError, "host changed"):
                    comparison.run(root, root, root, root, root / "out", original_board_sha256="a" * 64,
                        production_board_sha256="a" * 64, original_preflight_sha256="a" * 64,
                        production_preflight_sha256="a" * 64)
            report = json.loads((root / "out/results.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertFalse(report["hardware_timing_measured"])
            self.assertFalse(report["publication_performance_match"])


if __name__ == "__main__":
    unittest.main()
