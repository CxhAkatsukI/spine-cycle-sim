"""Exercise board sequencing with mocks, never with a real FPGA."""

from contextlib import ExitStack, contextmanager, nullcontext
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import board_study as study, preparation


class BoardStudyTests(unittest.TestCase):
    def invoke(self, root, *, execute=True, failed=None, admission=True, memory_event=False,
               drift=False, busy=False, affinity=(0, 1), spine=False):
        group = root / "group"
        group.mkdir()
        (group / "memory.events").write_text("max 0\noom 0\noom_kill 0\noom_group_kill 0\n")
        binary = root / "host"
        binary.write_text("mock executable; never run")
        inputs = root / "input"
        inputs.write_text("mock pinned input")
        rows = [{"dataset": dataset, "algorithm": "weighted_sssp", "graph": str(inputs), "source": 0}
                for dataset in preparation.DATASETS]
        plan = {"binary": str(binary), "candidate": {"path": str(root / "fake.xclbin")},
                "pins": [preparation.identity(inputs)], "rows": rows,
                "smoke": {**rows[0], "dataset": "SMOKE"}}
        experiment = None
        if spine:
            from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.spine_resident.__main__ import experiment as spine_experiment
            from dataclasses import replace
            plan["smokes"] = [{**rows[0], "dataset": "LEGACY", "legacy": True}, plan["smoke"]]
            experiment = replace(spine_experiment(), prepare=lambda *_: plan,
                                 analyze=lambda *_args, **_kwargs: {"status": "PASS"})
        output = root / "attempt"
        calls = []

        @contextmanager
        def board(_):
            yield Path("/dev/dri/mock")

        def child(command, cwd, prefix, **kwargs):
            calls.append((prefix.name, command, kwargs))
            prefix.parent.mkdir(exist_ok=True)
            prefix.with_suffix(".stdout.txt").write_text("mock log, analyzer replaced")
            prefix.with_suffix(".stderr.txt").write_text("")
            if not spine:
                Path(command[3]).write_text("mock result, no hardware")
            if drift:
                inputs.write_text("changed input")
            if memory_event:
                (group / "memory.events").write_text("max 1\noom 0\noom_kill 0\noom_group_kill 0\n")
            return {"exit_code": int(prefix.name == failed), "stop_reason": "process_exit",
                    "cleanup_snapshot_error": None}

        with ExitStack() as stack:
            for name, value in (("current", group), ("available_memory_bytes", 160 * 1024**3),
                    ("other_builds", ["bounded vivado peer"]),
                    ("verify", {"path": str(group), "limits": {"memory.max": str(24 * 1024**3),
                                                             "memory.high": str(22 * 1024**3)}})):
                stack.enter_context(patch.object(study, name, return_value=value))
            stack.enter_context(patch.object(study.board_preparation, "prepare", return_value=plan))
            stack.enter_context(patch.object(study.os, "sched_getaffinity", return_value=set(affinity)))
            stack.enter_context(patch.object(study, "clean_environment"))
            stack.enter_context(patch.object(study.board_access, "measurement_lease", side_effect=nullcontext))
            stack.enter_context(patch.object(study.board_access, "board_lease", side_effect=board))
            idle = stack.enter_context(patch.object(study, "require_idle_board",
                                                    side_effect=ValueError("busy") if busy else None))
            stack.enter_context(patch.object(study.runtime, "capture", return_value={"pins": [],
                                                         "device": {"bdf": "0000:01:00.1"}}))
            stack.enter_context(patch.object(study.runtime, "unchanged"))
            stack.enter_context(patch.object(study, "run_link", side_effect=child))
            stack.enter_context(patch.object(study.board_analysis, "analyze", return_value={"status": "PASS"}))
            stack.enter_context(patch.object(study.time, "monotonic", side_effect=[0, 2]))
            lease = stack.enter_context(patch.object(study, "Lease"))
            lease.return_value.held = admission
            lease.return_value.sample.return_value = {"admitted": admission}
            try:
                result = study.run(root, root / "admission", "weighted_sssp", output,
                                   execute=execute, wait_seconds=1, experiment=experiment)
            except (ValueError, TimeoutError):
                result = json.loads((output / "results.json").read_text())
            return result, calls, lease.return_value, idle

    def test_smoke_then_exact_eight_graphs_three_times_with_bounded_peer(self):
        with tempfile.TemporaryDirectory() as directory:
            report, calls, lease, idle = self.invoke(Path(directory))
            self.assertEqual(report["status"], study.PASS)
            self.assertEqual(len(calls), 25)
            self.assertEqual(calls[0][0], "smoke_r0_SMOKE")
            self.assertEqual([c[0] for c in calls[1:]],
                             [f"matrix_r{r}_{d}" for r in range(3) for d in preparation.DATASETS])
            self.assertTrue(report["hardware_convergence_measured"])
            self.assertFalse(report["production_baseline_admitted"])
            self.assertFalse(report["spine_comparison"])
            self.assertFalse(report["publication_match"])
            self.assertEqual(calls[0][2]["environment"]["GRASU_REGRAPH_EXPECT_BDF"], "0000:01:00.1")
            self.assertNotIn("LD_PRELOAD", calls[0][2]["environment"])
            self.assertEqual(calls[0][2]["environment"]["XILINX_XRT"], "/opt/xilinx/xrt")
            self.assertEqual(calls[0][2]["tree_memory_gib"], 24)
            self.assertEqual(calls[0][2]["reserve_gib"], 32)
            self.assertEqual(idle.call_count, 26)
            lease.release.assert_called_once()

    def test_prepare_only_acquires_neither_board_nor_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            report, calls, lease, idle = self.invoke(Path(directory), execute=False)
            self.assertEqual((report["status"], calls), ("BOARD_PREPARED_NOT_EXECUTED", []))
            self.assertFalse(report["board_requested"])
            lease.sample.assert_not_called()
            idle.assert_not_called()

    def test_spine_contract_shares_executor_but_not_gr_commands_or_result_files(self):
        from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.spine_resident.analysis import PASS
        with tempfile.TemporaryDirectory() as directory:
            report, calls, lease, idle = self.invoke(Path(directory), spine=True)
            self.assertEqual(report["status"], PASS)
            self.assertEqual(report["experiment"], "fixed_spine_resident")
            self.assertEqual(len(calls), 26)
            self.assertEqual([call[0] for call in calls[:2]], ["smoke_r0_LEGACY", "smoke_r1_SMOKE"])
            self.assertNotIn("--resident-benchmark", calls[0][1])
            self.assertTrue(all("--resident-benchmark" in call[1] for call in calls[1:]))
            self.assertEqual(calls[0][2]["environment"]["SPINE_EXPECT_BDF"], "0000:01:00.1")
            self.assertNotIn("GRASU_REGRAPH_EXPECT_BDF", report["environment"])
            self.assertTrue(all("result_identity" not in row for row in report["attempts"]))
            self.assertFalse(report["spine_comparison"])
            lease.release.assert_called_once()

    def test_memory_timeout_busy_board_or_wrong_affinity_never_launches_child(self):
        for kwargs in ({"admission": False}, {"busy": True}, {"affinity": (0,)}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as directory:
                report, calls, _, _ = self.invoke(Path(directory), **kwargs)
                self.assertEqual((report["status"], calls), ("FAILED_RETAINED", []))
                self.assertFalse(report["board_requested"])

    def test_smoke_or_matrix_failure_does_not_continue_or_reset(self):
        for failed, count in (("smoke_r0_SMOKE", 1), ("matrix_r0_SO", 5)):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as directory:
                report, calls, lease, _ = self.invoke(Path(directory), failed=failed)
                self.assertEqual((report["status"], len(calls)), ("FAILED_RETAINED", count))
                self.assertFalse(report["hardware_convergence_measured"])
                self.assertEqual(report["attempts"][-1]["status"], "FAILED_RETAINED")
                lease.release.assert_called_once()

    def test_input_drift_stops_before_next_child_and_memory_event_rejects_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            report, calls, _, _ = self.invoke(Path(directory), drift=True)
            self.assertEqual((report["status"], len(calls)), ("FAILED_RETAINED", 1))
        with tempfile.TemporaryDirectory() as directory:
            report, calls, _, _ = self.invoke(Path(directory), memory_event=True)
            self.assertEqual((report["status"], len(calls)), ("FAILED_RETAINED", 25))
            self.assertFalse(report["hardware_convergence_measured"])

    def test_inherited_loader_and_device_overrides_rejected(self):
        for name in ("LD_PRELOAD", "XRT_INI_PATH", "XCL_DEVICE_INDEX", "GRASU_REGRAPH_EXPECT_BDF", "SPINE_EXPECT_BDF"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                with patch.dict(os.environ, {name: "uncontrolled"}), self.assertRaises(ValueError):
                    study.clean_environment(Path(directory) / "host", Path(directory))


if __name__ == "__main__":
    unittest.main()
