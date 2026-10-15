import copy
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_handoff import analysis, events, execution
from tests import test_grasu_continuous_handoff as fixtures
from tests.test_grasu_continuous_execution import BDF, mutate


def case():
    result = fixtures.ContinuousHandoffTests().case()
    return {**result, "input": "input.txt", "partition_vertices": 65536,
            "expected_active_counts": [[0], [2, 1, 0], [2, 1, 0]]}


def output():
    setup, rows = fixtures.ContinuousHandoffTests().output()
    setup.update(board=True, device_bdf=BDF, hbm_bytes=20000000)
    lines = ["CONTINUOUS_GR_SETUP " + json.dumps(setup)]
    for row in rows:
        base = (row["batch"] + 1) * 1000000
        raw = []

        def event(stage, role, index, queued, first, last):
            raw.append({"batch": row["batch"], "stage": stage, "role": role, "index": index,
                        "queued_ns": base + queued, "submit_ns": base + queued + 10,
                        "start_ns": base + first, "end_ns": base + last})

        for _ in range(min(4, row["updates"])):
            event("transfer", "update_dma", 0, 0, 20, 100)
        for i, role in enumerate(sorted(events.G_ROLES)):
            event("G", role, 0, 200, 300 + i * 10, 800 + i * 10)
        role = "fallback_dma" if row["fallback"] else "seed_dma"
        for _ in range(3 if row["fallback"] else 2 * row["seed_sources"]):
            event("transfer", role, 0, 1000, 1100, 1200)
        for round in range(row["rounds"]):
            for i, role in enumerate(sorted(events.R_ROLES)):
                event("R", role, round, 2000 + 1000 * round, 2200 + 1000 * round + i * 10,
                      2500 + 1000 * round + i * 10)
            event("transfer", "active_readback", round, 2700 + 1000 * round,
                  2800 + 1000 * round, 2900 + 1000 * round)
        last = 2000 + 1000 * row["rounds"]
        event("transfer", "result_readback", 0, last, last + 100, last + 200)
        row.update(board=True, host_preparation_ms=0.1, g_ready_wall_ms=1.0, host_inclusive_e2e_ms=2.0,
                   g_busy_ms=events.window([event for event in raw if event["stage"] == "G"])[0],
                   r_busy_ms=events.window([event for event in raw if event["stage"] == "R"])[0])
        lines.extend("CONTINUOUS_GR_EVENT " + json.dumps(event) for event in raw)
        lines.append("CONTINUOUS_GR_ROW " + json.dumps(row))
    return "\n".join([*lines, events.BOARD_MARKER])


class HandoffEventTests(unittest.TestCase):
    def test_complete_fallback_and_warm_batches_preserve_event_unions(self):
        result = events.analyze(case(), output(), "", bdf=BDF)
        self.assertEqual(len(result["rows"]), 3)
        self.assertEqual([row["rounds"] for row in result["rows"]], [1, 3, 3])
        for stage, key in (("G", "g_busy_ms"), ("R", "r_busy_ms")):
            raw = [event for event in result["events"] if event["stage"] == stage and event["batch"] == 1]
            self.assertLess(result["rows"][1][key], sum((event["end_ns"] - event["start_ns"]) / 1e6 for event in raw))

    def test_missing_duplicate_wrong_stage_and_round_events_fail(self):
        lines = output().splitlines()
        candidates = ["\n".join(lines[:1] + lines[2:]), "\n".join(lines[:2] + lines[1:])]
        candidates += [mutate(output(), "CONTINUOUS_GR_EVENT ", 0, key, value)
                       for key, value in (("stage", "R"), ("index", 1), ("batch", True),
                                          ("role", "unknown"), ("end_ns", 0), ("queued_ns", -1))]
        for text in candidates:
            with self.subTest(text=text[:80]), self.assertRaises(ValueError):
                events.analyze(case(), text, "", bdf=BDF)

    def test_changed_convergence_policy_and_invented_times_fail(self):
        for key, value in (("fallback", True), ("seed_sources", 1), ("active_counts", [1, 0]),
                           ("rounds", True), ("g_busy_ms", 1.0), ("r_busy_ms", 1.0),
                           ("host_inclusive_e2e_ms", 0), ("g_ready_wall_ms", 0),
                           ("host_preparation_ms", 10), ("state_pass", False), ("restored_pma", True),
                           ("checked_words", False), ("checked_vertices", 0), ("oracle_ms", float("nan"))):
            text = mutate(output(), "CONTINUOUS_GR_ROW ", 0, key, value)
            with self.subTest(key=key), self.assertRaises(ValueError):
                events.analyze(case(), text, "", bdf=BDF)
        changed = case()
        changed["expected_active_counts"][1] = [3, 1, 0]
        with self.assertRaisesRegex(ValueError, "trajectory"):
            events.analyze(changed, output(), "", bdf=BDF)

    def test_early_convergence_readback_and_cross_batch_overlap_fail(self):
        result = events.analyze(case(), output(), "", bdf=BDF)
        selected = next(i for i, event in enumerate(result["events"]) if event["role"] == "active_readback")
        text = mutate(output(), "CONTINUOUS_GR_EVENT ", selected, "queued_ns", 1002200)
        with self.assertRaisesRegex(ValueError, "ordering"):
            events.analyze(case(), text, "", bdf=BDF)
        selected = next(i for i, event in enumerate(result["events"]) if event["batch"] == 1)
        text = mutate(output(), "CONTINUOUS_GR_EVENT ", selected, "queued_ns", 1)
        with self.assertRaisesRegex(ValueError, "cross-batch"):
            events.analyze(case(), text, "", bdf=BDF)

    def test_missing_seed_or_result_and_extra_output_fail(self):
        lines = output().splitlines()
        for role in ("seed_dma", "fallback_dma", "active_readback", "result_readback"):
            selected = next(i for i, line in enumerate(lines) if line.startswith("CONTINUOUS_GR_EVENT ") and
                            json.loads(line.removeprefix("CONTINUOUS_GR_EVENT "))["role"] == role)
            with self.subTest(role=role), self.assertRaises(ValueError):
                events.analyze(case(), "\n".join(lines[:selected] + lines[selected + 1:]), "", bdf=BDF)
        for text, err in ((output() + "\nEXTRA", ""), (output(), "warning"),
                          (output().replace(events.BOARD_MARKER, analysis.PASS), "")):
            with self.assertRaises(ValueError):
                events.analyze(case(), text, err, bdf=BDF)

    def test_wrong_device_cold_scope_and_boolean_setup_fail(self):
        for key, value in (("device_bdf", "0000:c1:00.1"), ("initial_state", "cold"),
                           ("source", False), ("shards", 2), ("round_limit", 1), ("hbm_bytes", 0)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                events.analyze(case(), mutate(output(), "CONTINUOUS_GR_SETUP ", 0, key, value), "", bdf=BDF)
        with self.assertRaisesRegex(ValueError, "single-partition"):
            events.analyze({**case(), "shards": 2}, output(), "", bdf=BDF)


class HandoffRunnerTests(unittest.TestCase):
    def test_host_identity_requires_new_reported_device_and_preserves_trajectories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            guard = root / "source/continuous_board/xrt.hpp"
            control = root / "source/continuous_handoff/control.cpp"
            guard.parent.mkdir(parents=True)
            control.parent.mkdir(parents=True)
            guard.write_text('std::getenv("CONTINUOUS_G_EXPECT_BDF") CL_DEVICE_PCIE_BDF')
            control.write_text("device->session.bdf")
            (root / "probe").write_text("binary")
            _, rows = fixtures.ContinuousHandoffTests().output()
            report = {"status": analysis.PASS, "source": [], "dependencies": [],
                      "contract": {"algorithm": "weighted SSSP", "source_vertex": 0, "round_limit": 2048,
                                   "initial_state": "old_graph_converged", "cache_capacity_per_half": 131072,
                                   "warm_controls": "declared", "cases": [case()]},
                      "cases": [{"case": case()["case"], "rows": rows}]}
            (root / "results.json").write_text(json.dumps(report))
            with patch.object(execution, "validate"):
                actual, pins = execution.host_identity(root)
                self.assertEqual(actual["contract"]["cases"][0]["expected_active_counts"], case()["expected_active_counts"])
                self.assertEqual(len(pins), 2)
                control.write_text("old binary without reported device identity")
                with self.assertRaisesRegex(ValueError, "identity guards"):
                    execution.host_identity(root)

    def test_unfinished_route_rejected_before_board_lease(self):
        board = execution.board
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(execution, "host_identity", return_value=({"contract": {}}, [])), \
                    patch.object(board.runtime, "require_clean_environment"), \
                    patch.object(board.route, "review", side_effect=ValueError("unfinished route")), \
                    patch.object(board, "board_lease") as lease:
                with self.assertRaisesRegex(ValueError, "unfinished"):
                    execution.run(root, root, root, root / "output", execute=True)
                lease.assert_not_called()
            report = json.loads((root / "output/results.json").read_text())
            self.assertFalse(report["board_started"])
            self.assertFalse(report["board_correctness_measured"])
            self.assertEqual(report["status"], "FAILED_RETAINED")

    def test_shared_runner_uses_handoff_analyzer_and_does_not_promote_claims(self):
        board = execution.board
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checked = {"pins": [], "candidate": {"path": "candidate", "sha256": "hash"},
                       "timing": {"report": {"path": "timing", "sha256": "hash"}}}
            captured = {"device": {"bdf": BDF}, "pins": []}

            def launch(command, cwd, prefix, **kwargs):
                self.assertEqual(kwargs["environment"]["CONTINUOUS_G_EXPECT_BDF"], BDF)
                self.assertEqual(kwargs["tree_memory_gib"], 8)
                prefix.with_suffix(".stdout.txt").write_text(output())
                prefix.with_suffix(".stderr.txt").write_text("")
                return {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}

            with patch.object(execution, "host_identity", return_value=({"contract": {"cases": [case()]}}, [])), \
                    patch.object(board.runtime, "require_clean_environment"), \
                    patch.object(board.route, "review", return_value=checked), patch.object(board, "unchanged"), \
                    patch.object(board, "containment", return_value={}), \
                    patch.object(board, "board_lease", return_value=nullcontext(Path("render"))), \
                    patch.object(board, "require_idle_board"), patch.object(board.runtime, "capture", return_value=captured), \
                    patch.object(board.runtime, "unchanged"), patch.object(board, "run_link", side_effect=launch):
                report = execution.run(root, root, root, root / "output", execute=True)
            self.assertEqual(report["status"], execution.BOARD_PASS)
            self.assertEqual(len(report["attempts"]), 3)
            self.assertTrue(report["board_correctness_measured"])
            self.assertTrue(all(report[key] is False for key in analysis.CLAIMS))
            self.assertTrue(any(pin["path"].endswith("continuous_handoff/events.py") for pin in report["pins"]))


if __name__ == "__main__":
    unittest.main()
