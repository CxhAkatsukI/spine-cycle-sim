from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact, control_analysis
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import (
    admission, analysis, preparation, supervisor, worker,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_build import configuration as config


def plan(topology=config.DEFAULT_TOPOLOGY):
    little, big = config.counts(topology)
    return {"configuration": topology, "boundary": preparation.BOUNDARY, "repeats": 3, "policy": preparation.POLICY,
            "publication_match": False, "convergence_measured": False, "host_inclusive_measured": False,
            "device_index": 1, "pins": [], "host": {"path": "/host"}, "xclbin": {"path": "/binary"},
            "cases": [{"graph": graph, "binding": binding, "input": "/input", "offline": {
                "little": little, "big": big, "topology": topology, "binding": binding}}
                for graph in preparation.GRAPHS for binding in control_analysis.BINDINGS]}


class BoardPlanTests(unittest.TestCase):
    def test_a4_requires_explicit_selected_topology_and_new_host_validation(self):
        preparation.validate_plan(plan("a4"))
        for changes in ({"little": 11}, {"big": 3}, {"big": False}, {"topology": "original_example"}):
            changed = plan("a4")
            changed["cases"][0]["offline"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                preparation.validate_plan(changed)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit, control = root / "audit", root / "control"
            audit.mkdir()
            control.mkdir()
            (audit / "results.json").write_text(json.dumps({"status": preparation.study.STATUS, "errors": []}))
            (control / "results.json").write_text("{}")
            with patch.object(preparation.control_delivery, "terminal"), \
                    self.assertRaisesRegex(ValueError, "A4-capable host"):
                preparation.prepare(audit, control, root / "route", topology="a4")

    def test_exact_scope_and_no_promoted_claims(self):
        preparation.validate_plan(plan())
        for changes in ({"repeats": 2}, {"repeats": True}, {"boundary": "convergence"}, {"policy": {}},
                        {"publication_match": True}, {"host_inclusive_measured": True},
                        {"convergence_measured": True}, {"cases": plan()["cases"][:-1]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                preparation.validate_plan({**plan(), **changes})
        for changes in ({"little": 4}, {"big": 0}, {"topology": "a4"}, {"binding": "other"}):
            changed = plan()
            changed["cases"][0]["offline"].update(changes)
            with self.assertRaises(ValueError):
                preparation.validate_plan(changed)

    def test_unique_pins_reject_conflicting_identity(self):
        pin = {"path": "/fixed", "sha256": "one"}
        self.assertEqual(preparation.unique([pin, pin]), [pin])
        with self.assertRaises(ValueError):
            preparation.unique([pin, {**pin, "sha256": "two"}])

    def test_wait_arguments_reject_unknown_device_unit_and_unbounded_time(self):
        args = ("route.service", "a" * 32, 1, 86400, 30)
        supervisor.validate(*args)
        for index, bad in ((0, "--help"), (1, "other"), (2, True), (2, 2), (3, float("inf")), (4, 0)):
            changed = list(args)
            changed[index] = bad
            with self.assertRaises(ValueError):
                supervisor.validate(*changed)


class BoardAdmissionTests(unittest.TestCase):
    def retained_report(self):
        return {"status": "FAILED_RETAINED", "configuration": config.DEFAULT_TOPOLOGY,
                "errors": [admission.RETAINED_TOPOLOGY_ERROR], "board_programmed": False,
                "hardware_timing_measured": False, "publication_match": False,
                "extraction": {"exit_code": 0, "timed_out": False}}

    def test_retained_review_is_explicit_and_rejects_every_other_failure(self):
        report = self.retained_report()
        self.assertTrue(admission.validate_result(report, config.DEFAULT_TOPOLOGY, True))
        for changes in ({}, {"errors": []}, {"errors": ["timing failure"]},
                        {"errors": [admission.RETAINED_TOPOLOGY_ERROR, "second failure"]},
                        {"analysis": {}}, {"extraction": {"exit_code": 1, "timed_out": False}},
                        {"extraction": {"exit_code": 0, "timed_out": True}},
                        {"board_programmed": True}, {"hardware_timing_measured": True},
                        {"publication_match": True}, {"configuration": "a4"}):
            enabled = bool(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                admission.validate_result({**report, **changes}, config.DEFAULT_TOPOLOGY, enabled)
        for invalid in (1, "true", None):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "explicit boolean"):
                admission.validate_result(report, config.DEFAULT_TOPOLOGY, invalid)

    def test_failed_route_or_incomplete_steps_never_extract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = {"status": admission.STATUS, "errors": [], "board_programmed": False,
                      "hardware_timing_measured": False, "publication_match": False, "pins": [],
                      "steps": [], "xos": []}
            for changes in ({"status": "FAILED_RETAINED"}, {"board_programmed": True}, {}):
                (root / "results.json").write_text(json.dumps({**report, **changes}))
                with patch.object(admission, "run_bounded") as extract, self.assertRaises(ValueError):
                    admission.review(root, root / "admission")
                extract.assert_not_called()

    def test_all_six_objects_and_fresh_metadata_are_rechecked(self):
        self.check_artifacts(config.DEFAULT_TOPOLOGY)

    def test_a4_requires_four_selected_objects_and_its_own_routed_binary(self):
        self.check_artifacts("a4")

    def test_retained_review_rechecks_every_artifact_without_rewriting_result(self):
        for topology in config.TOPOLOGIES:
            with self.subTest(topology=topology):
                self.check_artifacts(topology, retained=True)

    def check_artifacts(self, topology, retained=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = config.kernels(topology)
            binary = root / config.binary_name(topology)
            utility, xo, hls, timing = [root / name for name in ("utility", "xo-file", "hls-file", "timing-file")]
            for path in (binary, utility, xo, hls, timing):
                path.write_text(path.name)
            records = [{"abi": {"kernel": name, "xo": artifact.identity(xo)},
                        "hls": {"report": artifact.identity(hls)}} for name in names]
            routed = {"timing": {"report": artifact.identity(timing)}}
            report = {"status": config.routed_status(topology), "configuration": topology,
                      "errors": [], "board_programmed": False,
                      "hardware_timing_measured": False, "publication_match": False,
                      "pins": [artifact.identity(utility)], "xclbin": artifact.identity(binary), "analysis": routed,
                      "steps": [{"id": name, "exit_code": 0, "stop_reason": "process_exit",
                                 "cleanup_snapshot_error": None} for name in
                                ["compile_" + name for name in names] + ["route"]], "xos": records}
            if retained:
                report.update(status="FAILED_RETAINED", errors=[admission.RETAINED_TOPOLOGY_ERROR],
                              extraction={"exit_code": 0, "timed_out": False})
                del report["analysis"]
            result_path = root / "results.json"
            result_path.write_text(json.dumps(report))
            frozen_result = artifact.identity(result_path)
            options = {"review_retained_analysis_failure": True} if retained else {}
            with patch.object(admission.checkpoint_run, "UTILITY", utility), \
                    patch.object(admission.gates, "inspect_xo", side_effect=lambda path, name, **kwargs:
                        next(row["abi"] for row in records if row["abi"]["kernel"] == name)) as abi, \
                    patch.object(admission.gates, "inspect_hls", return_value={"report": artifact.identity(hls)}) as synthesis, \
                    patch.object(admission, "run_bounded", return_value={"exit_code": 0, "timed_out": False}) as extract, \
                    patch.object(admission.gates, "inspect_routed", return_value=routed) as final:
                checked = admission.review(root, root / "admission", topology=topology, **options)
                self.assertEqual(checked["xclbin"], report["xclbin"])
                self.assertEqual(checked["configuration"], topology)
                self.assertEqual(abi.call_count, len(names))
                self.assertEqual(synthesis.call_count, len(names))
                self.assertTrue(all(call.kwargs["topology"] == topology for call in abi.call_args_list))
                self.assertEqual(final.call_args.kwargs["configuration"], topology)
                self.assertIn("SYSTEM_METADATA:RAW:", " ".join(extract.call_args.args[0]))
                self.assertEqual(artifact.identity(result_path), frozen_result)
                if retained:
                    self.assertEqual(checked["retained_analysis_failure"]["result"], frozen_result)
                    self.assertFalse(checked["retained_analysis_failure"]["original_result_modified"])
                    self.assertEqual(json.loads(result_path.read_text())["status"], "FAILED_RETAINED")
                with self.assertRaisesRegex(ValueError, "successful fresh-source route"):
                    admission.review(root, root / "wrong", topology="a4" if topology == config.DEFAULT_TOPOLOGY
                                     else config.DEFAULT_TOPOLOGY, **options)
                if retained:
                    final.side_effect = ValueError("strict routed setup timing failed")
                    with self.assertRaisesRegex(ValueError, "strict routed setup timing failed"):
                        admission.review(root, root / "changed", topology=topology, **options)
                    report["steps"][-1]["exit_code"] = 1
                    result_path.write_text(json.dumps(report))
                    with self.assertRaisesRegex(ValueError, "complete selected-topology"):
                        admission.review(root, root / "incomplete", topology=topology, **options)
                    report["steps"][-1]["exit_code"] = 0
                    result_path.write_text(json.dumps(report))
                else:
                    final.return_value = {"changed": True}
                    with self.assertRaisesRegex(ValueError, "timing differs"):
                        admission.review(root, root / "changed", topology=topology)
            utility.write_text("drift")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                admission.review(root, root / "drift", topology=topology, **options)


class BoardSupervisorTests(unittest.TestCase):
    def fixture(self, stack, root):
        group = root / "cgroup"
        group.mkdir()
        (group / "memory.events").write_text("oom 0\noom_kill 0\n")
        stack.enter_context(patch.object(supervisor, "current", return_value=group))
        stack.enter_context(patch.object(supervisor, "verify", return_value={"limits": {"memory.high": str(7 * 1024**3)}}))
        prepare = stack.enter_context(patch.object(supervisor.preparation, "prepare", return_value=plan()))
        state = {"LoadState": "loaded", "ActiveState": "inactive", "SubState": "dead", "Result": "success",
                 "MainPID": "0", "ExecMainStatus": "0", "InvocationID": "a" * 32}
        service = stack.enter_context(patch.object(supervisor.waiting, "service_state", return_value=state))
        lease = stack.enter_context(patch.object(supervisor, "Lease"))
        lease.return_value.sample.return_value = {"admitted": True}
        stack.enter_context(patch.object(supervisor, "available_memory_bytes", return_value=132 * 1024**3))
        stack.enter_context(patch.object(supervisor, "other_builds", return_value=[]))
        review = stack.enter_context(patch.object(supervisor.admission, "review", return_value={
            "pins": [], "xclbin": {"path": "/binary"}}))
        execute = stack.enter_context(patch.object(supervisor, "run_link"))
        return service, lease, review, execute, prepare

    def run_supervisor(self, root, **options):
        return supervisor.run(root / "audit", root / "control", root / "route", root / "run",
                              route_unit="route.service", route_invocation="a" * 32, **options)

    def test_only_exact_clean_exit_one_is_eligible_for_retained_review(self):
        state = {"LoadState": "loaded", "ActiveState": "failed", "SubState": "failed",
                 "Result": "exit-code", "MainPID": "0", "ExecMainStatus": "1", "InvocationID": "a" * 32}
        self.assertTrue(supervisor.route_finished(state, "a" * 32, True))
        for changes in ({}, {"InvocationID": "b" * 32}, {"ExecMainStatus": "137"},
                        {"Result": "oom-kill"}, {"MainPID": "100"}, {"LoadState": "not-found"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                supervisor.route_finished({**state, **changes}, "a" * 32, bool(changes))

    def test_retained_failure_is_rechecked_before_memory_and_forwarded_explicitly(self):
        for unknown_error in (False, True):
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                service, lease, review, execute, _ = self.fixture(stack, root)
                service.return_value.update(ActiveState="failed", SubState="failed", Result="exit-code",
                                            ExecMainStatus="1")
                route = root / "route"
                route.mkdir()
                report = BoardAdmissionTests().retained_report()
                if unknown_error:
                    report["errors"].append("unknown failure")
                (route / "results.json").write_text(json.dumps(report))
                review.side_effect = ValueError("strict timing failed")
                with self.assertRaises(ValueError):
                    self.run_supervisor(root, review_retained_analysis_failure=True)
                execute.assert_not_called()
                if unknown_error:
                    lease.assert_not_called()
                    review.assert_not_called()
                else:
                    review.assert_called_once_with(route, root / "run/routed_admission",
                        topology=config.DEFAULT_TOPOLOGY, review_retained_analysis_failure=True)
                    lease.return_value.release.assert_called_once()

    def test_nonboolean_retained_review_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "explicit boolean"):
                self.run_supervisor(root, review_retained_analysis_failure=1)
            self.assertFalse((root / "run").exists())

    def test_failed_or_changed_route_cannot_acquire_memory_or_board(self):
        for changes in ({"Result": "exit-code", "ActiveState": "failed"}, {"InvocationID": "b" * 32}):
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                service, lease, review, execute, _ = self.fixture(stack, root)
                service.return_value.update(changes)
                with self.assertRaises(ValueError):
                    self.run_supervisor(root)
                lease.assert_not_called()
                review.assert_not_called()
                execute.assert_not_called()
                self.assertFalse(json.loads((root / "run/results.json").read_text())["board_launch_attempted"])

    def test_memory_or_route_readmission_failure_never_starts_worker(self):
        for failure in ("memory", "source", "restart"):
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                service, lease, review, execute, _ = self.fixture(stack, root)
                if failure == "memory":
                    lease.return_value.sample.return_value = {"admitted": False}
                elif failure == "source":
                    review.side_effect = ValueError("source changed")
                else:
                    service.side_effect = [service.return_value, {**service.return_value, "InvocationID": "b" * 32}]
                with self.assertRaises(ValueError):
                    self.run_supervisor(root)
                execute.assert_not_called()
                lease.return_value.release.assert_called_once()

    def test_worker_timeout_retains_uncertain_programming_without_reset(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            _, lease, _, execute, _ = self.fixture(stack, root)

            def failed(*args, **kwargs):
                destination = root / "run/board"
                destination.mkdir()
                (destination / "results.json").write_text(json.dumps({"board_launch_attempted": True,
                    "board_programmed": None, "hardware_timing_measured": False}))
                return {"exit_code": -9, "stop_reason": "timeout", "cleanup_snapshot_error": None}

            execute.side_effect = failed
            with self.assertRaises(ValueError):
                self.run_supervisor(root)
            report = json.loads((root / "run/results.json").read_text())
            self.assertTrue(report["board_launch_attempted"])
            self.assertIsNone(report["board_programmed"])
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertEqual(execute.call_args.kwargs["tree_memory_gib"], 8)
            lease.return_value.release.assert_called_once()

    def test_success_rechecks_every_raw_row_and_complete_summary(self):
        for drift in (None, "raw", "analysis", "summary"):
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                _, lease, _, execute, _ = self.fixture(stack, root)
                inspect = stack.enter_context(patch.object(supervisor.analysis, "inspect"))
                checked = {"independent_oracle": {"expected_sha256": "fixed"},
                           "enqueue_to_completion_ms": 1, "event_union_ns": 10, "event_span_ns": 20}
                inspect.return_value = checked

                def complete(*args, **kwargs):
                    destination = root / "run/board"
                    destination.mkdir()
                    rows = []
                    for repeat in range(3):
                        for case in plan()["cases"]:
                            case_output = destination / f"r{repeat}_{case['graph']}_{case['binding']}"
                            case_output.mkdir()
                            (case_output / "result.json").write_text(json.dumps({"measured": True}))
                            rows.append({"graph": case["graph"], "binding": case["binding"], "repeat": repeat,
                                "directory": str(case_output), "observation": {"measured": True}, "analysis": checked})
                    child = {"status": analysis.PASS, "errors": [], "board_launch_attempted": True,
                             "board_programmed": True, "hardware_timing_measured": True,
                             "publication_match": False, "convergence_measured": False,
                             "host_inclusive_measured": False, "pins": [], "rows": rows,
                             "summaries": analysis.matrix(rows), "runtime": {"device": {"bdf": "fixed"}}}
                    if drift == "raw":
                        (Path(rows[0]["directory"]) / "result.json").write_text("{}")
                    elif drift == "analysis":
                        rows[0]["analysis"] = {"changed": True}
                    elif drift == "summary":
                        child["summaries"] = []
                    (destination / "results.json").write_text(json.dumps(child))
                    return {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}

                execute.side_effect = complete
                if drift is None:
                    report = self.run_supervisor(root)
                    self.assertEqual(report["status"], analysis.PASS)
                    self.assertEqual(inspect.call_count, 18)
                    self.assertEqual(len(report["summaries"]), 6)
                    self.assertTrue(report["hardware_timing_measured"])
                    self.assertFalse(report["publication_match"])
                else:
                    with self.assertRaises(ValueError):
                        self.run_supervisor(root)
                    report = json.loads((root / "run/results.json").read_text())
                    self.assertEqual(report["status"], "FAILED_RETAINED")
                lease.return_value.release.assert_called_once()


class BoardWorkerTests(unittest.TestCase):
    def test_complete_matrix_keeps_one_lease_and_rechecks_runtime_each_run(self):
        self.check_worker(config.DEFAULT_TOPOLOGY)

    def test_a4_worker_forwards_selected_topology_and_retains_all_checks(self):
        self.check_worker("a4")

    def check_worker(self, topology):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(plan(topology)))
            fd = os.open(root / "lock", os.O_CREAT | os.O_RDWR, 0o600)
            stack.callback(os.close, fd)

            @contextmanager
            def leased(device):
                self.assertEqual(device, 1)
                yield root / "render", fd

            lease = stack.enter_context(patch.object(worker, "leased_board", side_effect=leased))
            idle = stack.enter_context(patch.object(worker, "require_idle_board"))
            stack.enter_context(patch.object(worker.runtime, "capture", return_value={
                "pins": [], "device": {"bdf": "fixed"}}))
            runtime_check = stack.enter_context(patch.object(worker.runtime, "unchanged"))
            stack.enter_context(patch.object(worker.runtime, "require_clean_environment"))
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            stack.enter_context(patch.object(worker.analysis, "inspect", return_value={
                "pins": [], "independent_oracle": {"expected_sha256": "fixed"},
                "enqueue_to_completion_ms": 1, "event_union_ns": 10, "event_span_ns": 20}))

            def measured(command, **kwargs):
                destination = Path(command[-3])
                destination.mkdir(parents=True)
                (destination / "result.json").write_text('{"measured":true}')
                self.assertEqual(kwargs["pass_fds"], (fd,))
                self.assertEqual(kwargs["env"]["ORIGINAL_R_EXPECT_BDF"], "fixed")
                self.assertEqual(command[-1], "1")
                self.assertEqual(command[-5], topology)
                return subprocess.CompletedProcess(command, 0)

            execute = stack.enter_context(patch.object(worker.subprocess, "run", side_effect=measured))
            report = worker.run(manifest, root / "run")
            self.assertEqual(report["status"], analysis.pass_status(topology))
            self.assertEqual(report["configuration"], topology)
            self.assertEqual(len(report["rows"]), 18)
            self.assertEqual(len(report["summaries"]), 6)
            self.assertEqual(execute.call_count, 18)
            self.assertEqual(lease.call_count, 1)
            self.assertEqual(idle.call_count, 19)
            self.assertEqual(runtime_check.call_count, 19)
            self.assertTrue(report["board_programmed"])
            self.assertFalse(report["publication_match"])

    def test_regular_nonblocking_lease_is_exclusive_and_forwardable(self):
        real_path = worker.Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            render, lock = root / "render", root / "lock"
            render.touch()

            def paths(value):
                return render if str(value).startswith("/dev/dri/") else lock if str(value).startswith("/tmp/") else real_path(value)

            with patch.object(worker, "Path", side_effect=paths):
                with worker.leased_board(1) as (selected, fd):
                    self.assertEqual(selected, render)
                    with self.assertRaises(BlockingIOError):
                        with worker.leased_board(1):
                            self.fail("busy board must not be leased")
                    subprocess.run(["/usr/bin/python3", "-c",
                        "import fcntl,os,sys; fd=int(sys.argv[1]); os.fstat(fd); fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)",
                        str(fd)], pass_fds=(fd,), check=True, timeout=5)
                lock.unlink()
                os.mkfifo(lock)
                with self.assertRaisesRegex(ValueError, "regular"):
                    with worker.leased_board(1):
                        self.fail("FIFO must not be leased")
                lock.unlink()
                lock.symlink_to(render)
                with self.assertRaises(OSError):
                    with worker.leased_board(1):
                        self.fail("symlink must not be leased")

    def test_timeout_forwards_fixed_bdf_and_lease_but_does_not_retry(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(plan()))
            fd = os.open(root / "lock", os.O_CREAT | os.O_RDWR, 0o600)

            @contextmanager
            def lease(device):
                self.assertEqual(device, 1)
                yield root / "render", fd

            stack.callback(os.close, fd)
            stack.enter_context(patch.object(worker, "leased_board", side_effect=lease))
            stack.enter_context(patch.object(worker, "require_idle_board"))
            stack.enter_context(patch.object(worker.runtime, "capture", return_value={"pins": [], "device": {"bdf": "0000:82:00.1"}}))
            stack.enter_context(patch.object(worker.runtime, "unchanged"))
            stack.enter_context(patch.object(worker.runtime, "require_clean_environment"))
            execute = stack.enter_context(patch.object(worker.subprocess, "run", side_effect=subprocess.TimeoutExpired("host", 600)))
            stack.enter_context(patch.dict(os.environ, {}, clear=True))
            with self.assertRaises(subprocess.TimeoutExpired):
                worker.run(manifest, root / "run")
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.kwargs["pass_fds"], (fd,))
            self.assertEqual(execute.call_args.kwargs["env"]["ORIGINAL_R_EXPECT_BDF"], "0000:82:00.1")
            self.assertEqual(execute.call_args.args[0][-1], "1")
            report = json.loads((root / "run/results.json").read_text())
            self.assertTrue(report["attempts"][0]["timed_out"])
            self.assertIsNone(report["board_programmed"])
            self.assertFalse(report["hardware_timing_measured"])


if __name__ == "__main__":
    unittest.main()
