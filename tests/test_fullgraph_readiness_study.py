import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import analysis, diagnostics, preparation, study


class StudyTests(unittest.TestCase):
    def invoke(self, root, *, samples=None, failed=None, sleep=None, compiler_notes=None):
        group = root / "cgroup"
        group.mkdir()
        (group / "memory.events").write_text("oom_kill 0\n")
        library = root / "xrt/lib/libxilinxopencl.so"
        library.parent.mkdir(parents=True)
        library.write_text("fake library, never loaded")
        rows = [{"dataset": d, "algorithm": a, "graph": str(root / "unused.graph"), "source": 0}
                for d in preparation.DATASETS for a in preparation.ALGORITHMS]
        output = root / "attempt"
        calls = []

        def execute(command, cwd, prefix, **kwargs):
            calls.append((prefix.name, command, kwargs))
            prefix.parent.mkdir(exist_ok=True)
            compilation = prefix.name.startswith("compile_")
            if compilation:
                Path(command[-1]).write_text("fake host, never executed")
            prefix.with_suffix(".stdout.txt").write_text("" if compilation else prefix.name)
            prefix.with_suffix(".stderr.txt").write_text(json.dumps(compiler_notes or []) if compilation else "")
            return {"exit_code": int(prefix.name == failed), "stop_reason": "process_exit",
                    "cleanup_snapshot_error": None, "cwd": str(cwd)}

        def analyze(row, stdout, stderr):
            return {"status": "PASS", "claim": "mock CPU scope, not actual execution"}

        with patch.object(study, "current", return_value=group), \
                patch.object(study, "verify", return_value={"limits": {"memory.max": str(24 * 1024**3)}}), \
                patch.object(study.preparation, "freeze", return_value={"revision": "fake-revision",
                    "rows": rows, "source": str(root / "source"), "pins": []}), \
                patch.object(study, "dependency_identities", return_value=[]), \
                patch.object(study.subprocess, "check_output", return_value="mock compiler version"), \
                patch.object(study, "Lease") as lease, \
                patch.object(study, "available_memory_bytes", return_value=160 * 1024**3), \
                patch.object(study, "other_builds", return_value=["123 vivado"]), \
                patch.object(study, "run_link", side_effect=execute), \
                patch.object(study.analysis, "analyze", side_effect=analyze), \
                patch.object(study.time, "monotonic", side_effect=[0, 0, 31]), \
                patch.object(study.time, "sleep", side_effect=sleep):
            lease.return_value.sample.side_effect = samples or [{"admitted": True}]
            try:
                result = study.run(root, root, output, root / "xrt", root, wait_seconds=30)
            except (ValueError, RuntimeError, TimeoutError):
                result = json.loads((output / "results.json").read_text())
            return result, calls, lease.return_value

    def test_admits_with_live_other_tools_and_smokes_before_all_24_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, lease = self.invoke(Path(directory))
            self.assertEqual(result["status"], analysis.PASS)
            self.assertEqual(len(calls), 30)
            self.assertTrue(all(c[0].startswith("compile_") for c in calls[:3]))
            self.assertTrue(all(c[0].startswith("SMOKE_") for c in calls[3:6]))
            self.assertEqual((len(result["smokes"]), len(result["cases"])), (3, 24))
            self.assertTrue(lease.sample.call_args.kwargs["commit"])
            lease.release.assert_called_once()
            self.assertFalse(result["board_programmed"])
            self.assertFalse(result["hardware_timing_measured"])
            self.assertEqual(calls[0][2]["tree_memory_gib"], 24)
            self.assertEqual(calls[0][2]["reserve_gib"], 32)
            self.assertNotIn("LD_PRELOAD", calls[0][2]["environment"])

    def test_waits_only_for_budget_then_runs_once(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, lease = self.invoke(Path(directory), samples=[{"admitted": False}, {"admitted": True}])
            self.assertEqual((result["status"], len(calls), lease.sample.call_count), (analysis.PASS, 30, 2))

    def test_reviewed_note_saved_without_changing_matrix_or_host_contract(self):
        note = {"kind": "note", "message": diagnostics.RENAME_MESSAGE, "children": [],
                "locations": [{"caret": {"file": "/usr/include/CL/cl2.hpp", "line": 18}}]}
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _ = self.invoke(Path(directory), compiler_notes=[note])
            self.assertEqual((result["status"], len(calls)), (analysis.PASS, 30))
            self.assertEqual(result["compiler_diagnostics"], {algorithm: [note] for algorithm in preparation.ALGORITHMS})
            self.assertFalse(result["board_programmed"])

    def test_unreviewed_diagnostic_stops_before_smokes_and_fullgraphs(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, lease = self.invoke(Path(directory), compiler_notes=[{"kind": "warning"}])
            self.assertEqual((result["status"], len(calls)), ("FAILED_RETAINED", 1))
            self.assertEqual((result["smokes"], result["cases"]), ([], []))
            lease.release.assert_called_once()

    def test_no_child_on_memory_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, lease = self.invoke(Path(directory), samples=[{"admitted": False}] * 2)
            self.assertEqual((result["status"], calls), ("FAILED_RETAINED", []))
            self.assertIn("deadline", result["errors"][0])
            lease.release.assert_called_once()

    def test_changed_dependency_while_waiting_launches_no_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, calls, _ = self.invoke(root, samples=[{"admitted": False}],
                sleep=lambda _: (root / "xrt/lib/libxilinxopencl.so").write_text("changed"))
            self.assertEqual((result["status"], calls), ("FAILED_RETAINED", []))
            self.assertIn("changed", result["errors"][0])

    def test_smoke_failure_stops_before_any_fullgraph_child(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _ = self.invoke(Path(directory), failed="SMOKE_weighted_sssp")
            self.assertEqual(result["status"], "FAILED_RETAINED")
            self.assertEqual(len(calls), 4)
            self.assertEqual(result["cases"], [])

    def test_one_large_failure_retained_and_rest_of_matrix_still_attempted(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _ = self.invoke(Path(directory), failed="SO_connected_components")
            self.assertEqual((result["status"], len(calls), len(result["cases"])), ("FAILED_RETAINED", 30, 24))
            self.assertEqual(sum(case["status"] == "FAILED_RETAINED" for case in result["cases"]), 1)

    def test_invalid_wait_or_existing_output_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "existing"
            output.mkdir()
            for wait in (0, -1, True, 1.5, 86401):
                with self.assertRaises(ValueError):
                    study.run(root, root, output, root, root, wait_seconds=wait)
            with self.assertRaises(FileExistsError):
                study.run(root, root, output, root, root)
            self.assertEqual(list(output.iterdir()), [])
