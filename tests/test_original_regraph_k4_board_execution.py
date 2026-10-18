"""No hardware: exercise actual-K4 matrix, qualification and failure-retention gates."""

import copy
from contextlib import contextmanager, ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.k4_control import (
    analysis, board_analysis, board_matrix, board_plan, board_study, board_worker,
)


def plan():
    cases = []
    for graph in board_plan.GRAPHS:
        reference = {"vertices": 10, "logical_edges": 20, "capacity_vertices": 65536,
                     "a4_published_vertices": 10, "duplicates": 64 if graph == "boundary_ring" else 0,
                     "first_duplicate": [352, 43409] if graph == "boundary_ring" else None}
        for binding in analysis.BINDINGS:
            case = {"graph": graph, "binding": binding, "input": "/input", "reference": reference,
                    "status": analysis.UNSUPPORTED if reference["duplicates"] else board_analysis.PREPARED}
            if not reference["duplicates"]:
                case.update(offline=analysis.profile(reference, binding), expected={"values": {"digest": graph}})
            cases.append(case)
    return {"boundary": board_plan.BOUNDARY, "repeats": 3, "policy": board_plan.POLICY,
            "cases": cases, "host": {"path": "/host", "sha256": "host"},
            "source_contract": {}, "pins": [], "device_index": 1,
            "xclbin": {"path": "/binary", "sha256": "binary"}, **dict.fromkeys(board_plan.CLAIMS, False)}


def rows(job):
    result = []
    for repeat in range(3):
        for case in job["cases"]:
            if case["status"] == analysis.UNSUPPORTED:
                result.append(board_matrix.unsupported(case, repeat))
            else:
                result.append({"graph": case["graph"], "binding": case["binding"], "repeat": repeat,
                    "status": board_analysis.PASS, "directory": "/synthetic-test-not-fpga",
                    "analysis": {"values": case["expected"]["values"], "event_union_ns": 10 + repeat,
                                 "event_span_ns": 20 + repeat, "enqueue_to_completion_ms": 0.1 + repeat}})
    return result


class K4BoardPlanTests(unittest.TestCase):
    def test_fixed_scope_rejects_missing_controls_or_promoted_claims(self):
        board_plan.validate(plan())
        for changes in ({"cases": plan()["cases"][:-1]}, {"repeats": 2}, {"repeats": True},
                        {"boundary": "convergence"}, {"policy": {}},
                        *[{claim: True} for claim in board_plan.CLAIMS]):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                board_plan.validate({**plan(), **changes})
        for changes in ({"graph_channels": 32}, {"iterations": 2}, {"source_prepare_skipped": False}):
            job = plan()
            job["cases"][2]["offline"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                board_plan.validate(job)
        job = plan()
        job["cases"][0]["status"] = board_analysis.PREPARED
        with self.assertRaises(ValueError):
            board_plan.validate(job)

    def test_source_contract_records_distinct_apply_revisions_without_claiming_equivalence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            members = (*board_plan.HEADERS, "kernels/regraph_pagerank_apply/regraph_pagerank_apply.cpp")
            records, pinned = [], []
            for name in members:
                path = root / "source/integration" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
                digest = artifact.identity(path)["sha256"]
                original = {"path": "/production/" + name, "sha256": digest}
                pinned.append(original)
                records.append({"member": "source/integration/" + name, "original": original, "sha256": digest})
            manifest = {"integration_revision": "old-routed", "files": records}
            preflight = {"pins": pinned, "source_review": {"production_revision": "new-prepared",
                "pins": [{**pinned[-1], "sha256": "different-packed-apply"}]}}
            with patch.object(board_plan.source_inputs, "verify", return_value=manifest):
                contract, pins = board_plan.source_contract(preflight, root)
                self.assertEqual(len(pins), 4)
                self.assertFalse(contract["apply_source_identical"])
                self.assertFalse(contract["source_revision_equivalence_claim"])
                self.assertFalse(contract["latest_revision_performance_claim"])
                self.assertEqual(contract["routed_revision"], "old-routed")
                preflight["pins"] = [{**pin, "sha256": "drift"} if pin == pinned[0] else pin for pin in pinned]
                with self.assertRaisesRegex(ValueError, "headers differ"):
                    board_plan.source_contract(preflight, root)

    def test_offline_only_or_incomplete_preflight_is_not_board_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for report in ({}, {"status": board_plan.study.STATUS},
                           {"status": board_plan.study.HOST_STATUS, "errors": [], "board_host_preflight": True}):
                (root / "results.json").write_text(json.dumps(report))
                with self.assertRaisesRegex(ValueError, "24-row"):
                    board_plan.prepare(root, root / "sources")


class K4BoardMatrixTests(unittest.TestCase):
    def test_all_eighteen_rows_preserve_six_unsupported_without_timing(self):
        job = plan()
        summary = board_matrix.summarize(rows(job), job["cases"])
        self.assertEqual(len(summary), 6)
        self.assertEqual(sum(row["status"] == analysis.UNSUPPORTED for row in summary), 2)
        measured = next(row for row in summary if row["status"] == board_analysis.PASS)
        self.assertEqual(measured["event_span_ns"], {"minimum": 20, "median": 21, "maximum": 22})
        self.assertNotIn("event_span_ns", summary[0])

    def test_missing_duplicate_changed_output_and_false_unsupported_timing_reject(self):
        job = plan()
        for change in ("missing", "duplicate", "bool_repeat", "unsupported_time", "unsupported_programmed", "values"):
            observed = rows(job)
            if change == "missing":
                observed.pop()
            elif change == "duplicate":
                observed[-1] = copy.deepcopy(observed[-2])
            elif change == "bool_repeat":
                observed[0]["repeat"] = False
            elif change == "unsupported_time":
                observed[0]["event_span_ns"] = 10
            elif change == "unsupported_programmed":
                observed[0]["board_programmed"] = True
            else:
                observed[2]["analysis"]["values"] = {"wrong": True}
            with self.subTest(change=change), self.assertRaises(ValueError):
                board_matrix.summarize(observed, job["cases"])

    def test_nonfinite_negative_bool_or_inconsistent_board_times_reject(self):
        for field, value in (("enqueue_to_completion_ms", float("nan")),
                             ("enqueue_to_completion_ms", float("inf")),
                             ("enqueue_to_completion_ms", 0), ("event_union_ns", True),
                             ("event_union_ns", -1), ("event_union_ns", 100),
                             ("event_span_ns", 1000000000)):
            job = plan()
            observed = rows(job)
            observed[2]["analysis"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                board_matrix.summarize(observed, job["cases"])


class K4BoardExecutionTests(unittest.TestCase):
    def test_local_and_remote_fullpr_returns_require_unchanged_admission_and_pins(self):
        for status in (board_study.follow.PASS, board_study.local_follow.PASS):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, admitted = root / "source", root / "admission.json"
                source.write_text("synthetic pinned source; not FPGA evidence")
                admitted.write_text("synthetic admission; re-reviewed before launch")
                report = {"status": status, "errors": [], "algorithm": "full_pagerank",
                    "board_requested": False, "pins": [artifact.identity(source)],
                    "admission": artifact.identity(admitted),
                    **dict.fromkeys(board_study.follow.artifacts.FLAGS, False)}
                path = root / "results.json"
                path.write_text(json.dumps(report))
                self.assertEqual(board_study.returned_result(root), (report, artifact.identity(path)))
                for target in (source, admitted):
                    original = target.read_text()
                    target.write_text("changed synthetic pin")
                    with self.assertRaises(ValueError):
                        board_study.returned_result(root)
                    target.write_text(original)

    def test_local_return_status_does_not_bypass_algorithm_errors_or_false_claims(self):
        valid = {"status": board_study.local_follow.PASS, "errors": [],
                 "algorithm": "full_pagerank", "board_requested": False,
                 **dict.fromkeys(board_study.follow.artifacts.FLAGS, False)}
        for changes in ({"status": "LINK_COMPLETE"}, {"errors": ["timing failed"]},
                        {"algorithm": "residual_pagerank"}, {"board_requested": True},
                        {"board_requested": None},
                        *[{key: True} for key in board_study.follow.artifacts.FLAGS]):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "results.json").write_text(json.dumps({**valid, **changes}))
                with self.assertRaisesRegex(ValueError, "strictly admitted FullPR"):
                    board_study.returned_result(root)

    def fixture(self, stack, root):
        group = root / "cgroup"
        group.mkdir()
        (group / "memory.events").write_text("oom 0\noom_kill 0\n")
        stack.enter_context(patch.object(board_study, "current", return_value=group))
        stack.enter_context(patch.object(board_study, "verify", return_value={"limits": {"memory.high": str(7 * 1024**3)}}))
        stack.enter_context(patch.object(board_study.board_plan, "prepare", return_value=plan()))
        stack.enter_context(patch.object(board_study, "unchanged"))
        state = {"LoadState": "loaded", "ActiveState": "active", "SubState": "exited", "Result": "success",
                 "MainPID": "0", "ExecMainStatus": "0", "InvocationID": "a" * 32}
        service = stack.enter_context(patch.object(board_study.waiting, "service_state", return_value=state))
        lease = stack.enter_context(patch.object(board_study, "Lease"))
        lease.return_value.sample.return_value = {"admitted": True}
        stack.enter_context(patch.object(board_study, "available_memory_bytes", return_value=100 * 1024**3))
        stack.enter_context(patch.object(board_study, "other_builds", return_value=[]))
        returned = stack.enter_context(patch.object(board_study, "returned_result", return_value=(
            {"pins": [], "admission": {"path": "/admission", "sha256": "a"}, "receipt_sha256": "b" * 64},
            {"path": "/returned", "sha256": "r"})))
        admission = stack.enter_context(patch.object(board_study.admission, "review"))
        launch = stack.enter_context(patch.object(board_study, "run_link"))
        return service, lease, returned, admission, launch

    def invoke(self, root, **kwargs):
        return board_study.run(root / "preflight", root / "sources", root / "return", root / "run",
            return_unit="return.service", return_invocation="a" * 32, **kwargs)

    def test_prepare_only_never_inspects_return_reserves_or_launches_board(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            service, lease, returned, admission, launch = self.fixture(stack, root)
            report = self.invoke(root)
            self.assertEqual(report["status"], board_study.READY)
            for mock in (service, lease, returned, admission, launch):
                mock.assert_not_called()
            self.assertFalse(report["board_programmed"])

    def test_failed_or_different_return_never_admits_or_programs(self):
        for changes in ({"InvocationID": "c" * 32}, {"ActiveState": "failed", "SubState": "failed", "Result": "exit-code"}):
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                service, lease, returned, admission, launch = self.fixture(stack, root)
                service.return_value.update(changes)
                with self.assertRaises(ValueError):
                    self.invoke(root, execute=True)
                for mock in (lease, returned, admission, launch):
                    mock.assert_not_called()
                self.assertEqual(json.loads((root / "run/results.json").read_text())["status"], "FAILED_RETAINED")

    def test_return_or_global_timing_failure_never_launches_worker(self):
        for failure in ("return", "timing"):
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                _, lease, returned, admission, launch = self.fixture(stack, root)
                (returned if failure == "return" else admission).side_effect = ValueError("strict " + failure)
                with self.assertRaisesRegex(ValueError, "strict"):
                    self.invoke(root, execute=True)
                launch.assert_not_called()
                if failure == "return":
                    lease.assert_not_called()
                else:
                    lease.return_value.release.assert_called_once()
                    self.assertEqual(admission.call_args.kwargs["receipt_sha256"], "b" * 64)

    def test_unpinned_bitstream_rejects_before_board_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(plan()))
            with patch.object(board_worker, "leased_board") as lease, self.assertRaisesRegex(ValueError, "frozen"):
                board_worker.run(manifest, root / "output")
            lease.assert_not_called()
            self.assertFalse(json.loads((root / "output/results.json").read_text())["board_launch_attempted"])

    def test_success_rechecks_all_raw_runs_and_releases_memory_reservation(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            _, lease, _, admission, launch = self.fixture(stack, root)
            candidate = {"path": "/binary", "sha256": "binary"}

            def admit(_returned, _sources, destination, **kwargs):
                destination.mkdir()
                (destination / "summary.json").write_text("synthetic qualification fixture, not FPGA")
                return {"algorithm": "full_pagerank", "pins": [], "candidate": candidate}

            def execute(*args, **kwargs):
                job = json.loads((root / "run/manifest.json").read_text())
                observed = rows(job)
                for index, row in enumerate(observed):
                    if row["status"] == analysis.UNSUPPORTED:
                        continue
                    path = root / "synthetic-readbacks" / str(index)
                    path.mkdir(parents=True)
                    row.update(directory=str(path), observation={"synthetic_index": index})
                    (path / "result.json").write_text(json.dumps(row["observation"]))
                attempts = [{"name": f"r{row['repeat']}_{row['graph']}_{row['binding']}",
                    "exit_code": 0, "timed_out": False, "lease_fd_forwarded": True}
                    for row in observed if row["status"] != analysis.UNSUPPORTED]
                child = {"status": board_matrix.PASS, "errors": [], "board_launch_attempted": True,
                    "board_programmed": True, "hardware_timing_measured": True,
                    "source_contract": job["source_contract"], "routed_candidate": candidate,
                    "attempts": attempts, "rows": observed, "pins": [],
                    "runtime": {"device": {"bdf": "synthetic-bdf"}},
                    "summaries": board_matrix.summarize(observed, job["cases"]),
                    **dict.fromkeys(board_plan.CLAIMS, False)}
                (root / "run/board").mkdir()
                (root / "run/board/results.json").write_text(json.dumps(child))
                return {"exit_code": 0, "stop_reason": "process_exit", "cleanup_snapshot_error": None}

            def readback(observation, path, case, bdf):
                self.assertEqual(bdf, "synthetic-bdf")
                index = observation["synthetic_index"]
                return rows(plan())[index]["analysis"]

            admission.side_effect, launch.side_effect = admit, execute
            checked = stack.enter_context(patch.object(board_study.board_analysis, "readback", side_effect=readback))
            report = self.invoke(root, execute=True)
            self.assertEqual(report["status"], board_matrix.PASS)
            self.assertEqual(checked.call_count, 12)
            self.assertEqual(len(report["summaries"]), 6)
            self.assertTrue(report["hardware_timing_measured"])
            self.assertTrue(all(report[key] is False for key in board_plan.CLAIMS))
            lease.return_value.release.assert_called_once()

    def test_failed_worker_preserves_programming_and_timeout_report(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            _, lease, _, admission, launch = self.fixture(stack, root)
            qualified = root / "run/routed_admission"

            def admit(*args, **kwargs):
                qualified.mkdir()
                (qualified / "summary.json").write_text("synthetic fixture, not FPGA")
                return {"algorithm": "full_pagerank", "pins": [], "candidate": plan()["xclbin"]}

            def execute(*args, **kwargs):
                (root / "run/board").mkdir()
                (root / "run/board/results.json").write_text(json.dumps({"status": "FAILED_RETAINED",
                    "board_launch_attempted": True, "board_programmed": None,
                    "hardware_timing_measured": False}))
                return {"exit_code": -9, "stop_reason": "timeout", "cleanup_snapshot_error": None}

            admission.side_effect, launch.side_effect = admit, execute
            with self.assertRaisesRegex(ValueError, "worker failed"):
                self.invoke(root, execute=True)
            report = json.loads((root / "run/results.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertTrue(report["board_launch_attempted"])
            self.assertIsNone(report["board_programmed"])
            self.assertFalse(report["hardware_timing_measured"])
            lease.return_value.release.assert_called_once()


class K4BoardWorkerTests(unittest.TestCase):
    def test_busy_lease_times_out_before_programming(self):
        @contextmanager
        def busy(_device):
            raise BlockingIOError("synthetic busy lease")
            yield

        report = {"board_launch_attempted": False}
        with patch.object(board_worker, "leased_board", side_effect=busy), \
                patch.object(board_worker.time, "monotonic", side_effect=[0, 0, 2]), \
                patch.object(board_worker.time, "sleep"), self.assertRaises(TimeoutError):
            with board_worker.wait_for_lease(1, report, lambda: None, timeout=1):
                self.fail("busy device must not reach programming")
        self.assertFalse(report["board_launch_attempted"])

    def test_full_worker_matrix_uses_forwarded_lease_and_fresh_outputs(self):
        @contextmanager
        def leased(_device, _report, _save):
            yield Path("/synthetic-render-not-a-device"), 12345

        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            job = plan()
            job["pins"] = [job["host"], job["xclbin"]]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(job))
            stack.enter_context(patch.object(board_worker, "unchanged"))
            stack.enter_context(patch.object(board_worker, "wait_for_lease", side_effect=leased))
            stack.enter_context(patch.object(board_worker, "require_idle_board"))
            stack.enter_context(patch.object(board_worker.runtime, "require_clean_environment"))
            stack.enter_context(patch.object(board_worker.runtime, "unchanged"))
            stack.enter_context(patch.object(board_worker.runtime, "capture", return_value={
                "device": {"bdf": "synthetic-bdf"}, "pins": []}))
            stack.enter_context(patch("builtins.print"))
            stack.enter_context(patch.dict(board_worker.os.environ, {}, clear=True))

            def execute(command, **kwargs):
                self.assertEqual(kwargs["pass_fds"], (12345,))
                self.assertEqual(kwargs["env"]["ORIGINAL_R_EXPECT_BDF"], "synthetic-bdf")
                self.assertEqual(kwargs["env"]["ORIGINAL_R_LEASE_FD"], "12345")
                path = Path(command[7])
                path.mkdir(parents=True, exist_ok=False)
                (path / "result.json").write_text("{}")
                return subprocess.CompletedProcess(command, 0)

            def check(_observation, _path, case, _bdf):
                return {"values": case["expected"]["values"], "event_union_ns": 10,
                        "event_span_ns": 20, "enqueue_to_completion_ms": 0.1, "pins": []}

            launch = stack.enter_context(patch.object(board_worker.subprocess, "run", side_effect=execute))
            checked = stack.enter_context(patch.object(board_worker.board_analysis, "readback", side_effect=check))
            report = board_worker.run(manifest, root / "worker")
            self.assertEqual(report["status"], board_matrix.PASS)
            self.assertEqual(len(report["rows"]), 18)
            self.assertEqual(len(report["attempts"]), 12)
            self.assertEqual(launch.call_count, 12)
            self.assertEqual(checked.call_count, 12)
            self.assertTrue(report["board_programmed"])
            self.assertFalse(report["latest_revision_performance_claim"])


if __name__ == "__main__":
    unittest.main()
