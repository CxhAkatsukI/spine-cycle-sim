"""Matched-input production G must fail closed before touching a device."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.matched_original import analysis as model
from spine_cycle_sim.experiments.evaluation_impact.common_g.matched_original.board import analysis, execution, follow, inputs


def fixture(updates=2):
    case = {"id": "mixed", "facts": {"vertices": 3, "segments": 1, "updates": updates, "route_updates": [updates, 0, 0, 0]}}
    events = [{"role": "update_dma", "shard": 0, "queued_ns": 10, "submit_ns": 20,
               "start_ns": 30, "end_ns": 40} for _ in range(min(4, updates))]
    events += [{"role": role, "shard": 0, "queued_ns": 100, "submit_ns": 200,
                "start_ns": 300, "end_ns": 10300} for role in sorted(analysis.ROLES)]
    row = {"status": "PASS", "updates": updates, "checked_words": model.expected(case)["checked_words"],
           "complete_state_pass": True, "metadata_pass": True, **dict.fromkeys(analysis.TIMES, 0.01)}
    row.update(g_ready_wall_ms=0.05)
    return case, events, row


def stdout(events, row):
    return "\n".join([*("MATCHED_G_EVENT " + json.dumps(event) for event in events),
                       "MATCHED_G_BOARD " + json.dumps(row)]) + "\n"


class MatchedGBoardAnalysisTests(unittest.TestCase):
    def test_empty_and_nonempty_replay(self):
        for updates in (0, 1, 2, 4, 50):
            with self.subTest(updates=updates):
                case, events, row = fixture(updates)
                result = analysis.inspect(stdout(events, row), "", case)
                self.assertEqual(result["observation"], row)
                self.assertEqual(result["producer_span_ms"], 0.01)
                self.assertIn("publication_barrier", result["boundary"])

    def test_typed_state_and_all_timing_fields(self):
        case, events, row = fixture()
        for key, value in (("updates", True), ("checked_words", True), ("complete_state_pass", 1),
                           ("metadata_pass", False), ("oracle_ms", float("nan")),
                           ("launch_wait_ms", -1), ("kernel_span_ms", 0.011), ("g_ready_wall_ms", 0.001)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.inspect(stdout(events, {**row, key: value}), "", case)
        with self.assertRaises(ValueError):
            analysis.inspect(stdout(events, {**row, "undeclared": True}), "", case)

    def test_raw_timestamps_roles_count_and_dma_order(self):
        case, events, row = fixture()
        for index, changes in ((-1, {"role": "update_dma"}), (-1, {"role": "cache0"}),
                               (0, {"end_ns": 101}), (-1, {"shard": True}),
                               (-1, {"start_ns": 10300}), (-1, {"end_ns": 20000000})):
            bad = copy.deepcopy(events)
            bad[index].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                analysis.inspect(stdout(bad, row), "", case)
        for out, err in ((stdout(events[:-1], row), ""), (stdout(events, row), "warning"),
                         (stdout(events, row) + "extra\n", "")):
            with self.assertRaises(ValueError):
                analysis.inspect(out, err, case)

    def test_frozen_six_significant_digit_precision(self):
        case, events, row = fixture()
        for event in events:
            if event["role"] != "update_dma":
                event["end_ns"] = 12345989
        row.update(kernel_busy_ms=12.3457, kernel_span_ms=12.3457, launch_wait_ms=13, g_ready_wall_ms=14)
        analysis.inspect(stdout(events, row), "", case)
        with self.assertRaises(ValueError):
            analysis.inspect(stdout(events, {**row, "kernel_span_ms": 12.34}), "", case)

    def test_complete_repeats_and_medians(self):
        case, events, row = fixture()
        result = analysis.inspect(stdout(events, row), "", case)
        rows = [{"case": "mixed", "repeat": repeat, "analysis": result} for repeat in range(3)]
        self.assertEqual(analysis.summaries(rows, ["mixed"], 3)[0]["median_launch_wait_ms"], 0.01)
        for bad in (rows[:-1], rows + rows[:1], [rows[0]] * 3):
            with self.assertRaises(ValueError):
                analysis.summaries(bad, ["mixed"], 3)


class MatchedGBoardGuardTests(unittest.TestCase):
    def test_invalid_configuration_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for kwargs in ({"device": True}, {"device": 2}, {"repeats": 2}, {"repeats": True},
                           {"receipt_sha256": "not-a-receipt"}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    execution.run(*([root] * 5), root / "output", **{"receipt_sha256": "a" * 64, **kwargs})
                self.assertFalse((root / "output").exists())

    def test_failed_host_prerequisite_never_requests_artifact_or_board(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(execution, "current", return_value=root), \
                    patch.object(execution, "verify", return_value={}), \
                    patch.object(inputs, "load", side_effect=ValueError("host changed")), \
                    patch.object(execution.admission, "review") as review, \
                    patch.object(execution, "wait_for_board") as board:
                with self.assertRaisesRegex(ValueError, "host changed"):
                    execution.run(*([root] * 5), root / "output", receipt_sha256="a" * 64)
            review.assert_not_called()
            board.assert_not_called()
            report = json.loads((root / "output/results.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertFalse(report["board_launch_attempted"])
            self.assertFalse(report["hardware_timing_measured"])

    def test_failed_routed_admission_never_acquires_device(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(execution, "current", return_value=root), \
                    patch.object(execution, "verify", return_value={}), \
                    patch.object(inputs, "load", return_value=(root / "probe", [], [])), \
                    patch.object(execution.admission, "review", side_effect=ValueError("timing failed")), \
                    patch.object(execution, "wait_for_board") as board:
                with self.assertRaisesRegex(ValueError, "timing failed"):
                    execution.run(*([root] * 5), root / "output", receipt_sha256="a" * 64)
            board.assert_not_called()
            report = json.loads((root / "output/results.json").read_text())
            self.assertFalse(report["board_launch_attempted"])


class MatchedGFollowTests(unittest.TestCase):
    def test_invalid_service_never_creates_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for changes in ({"invocation": "newest"}, {"unit": "wrong"}, {"maximum_wait": True},
                            {"device": True}, {"repeats": 1}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    follow.run(*([root] * 5), root / "output", **{
                        "unit": "producer.service", "invocation": "a" * 32, **changes})
                self.assertFalse((root / "output").exists())

    def test_failed_or_incomplete_qualifier_never_requests_board(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text('{"pins": []}')
            (root / "results.json").write_text('{"status": "RUNNING"}')
            for terminal in (ValueError("qualifier failed"), True):
                output = root / ("failed" if isinstance(terminal, Exception) else "incomplete")
                with patch.object(follow, "current", return_value=root), \
                        patch.object(follow, "verify", return_value={}), \
                        patch.object(inputs, "load", return_value=(root, [None] * 8, [])), \
                        patch.object(follow, "identity", return_value={}), \
                        patch.object(follow, "runner_pins", return_value=[]), \
                        patch.object(follow, "unchanged"), patch.object(follow, "service_state", return_value={}), \
                        patch.object(follow, "route_finished", side_effect=terminal if isinstance(terminal, Exception)
                                     else None, return_value=True), \
                        patch.object(execution, "run") as execute:
                    with self.assertRaises(ValueError):
                        follow.run(*([root] * 5), output, unit="producer.service", invocation="a" * 32)
                execute.assert_not_called()
                report = json.loads((output / "results.json").read_text())
                self.assertEqual(report["status"], "FAILED_RETAINED")
                self.assertFalse(report["board_launch_attempted"])


if __name__ == "__main__":
    unittest.main()
