import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.native_geometry import analysis, preparation, study


def output_fixture():
    setup = {key: analysis.CONTRACT[key] for key in
             ("vertices", "shards", "partition_vertices", "cache_segments_per_half",
              "reserved_operations", "executed_operations")}
    setup.update(hbm_bytes=128 * 1024**2, board=False)
    rows = []
    for registered in (0, 1):
        for batch in range(3):
            rows.append({"registered": registered, "batch": batch, "updates": 20 if batch else 0,
                         "edges": analysis.CONTRACT["edges_per_batch"][batch],
                         "packets": analysis.CONTRACT["packets_per_batch"],
                         **dict(zip(("hot_even", "cold_even", "hot_odd", "cold_odd"),
                                    [6, 4, 6, 4] if batch else [0] * 4)),
                         "complete_state_pass": True, "direct_handoff_pass": True, "metadata_pass": True,
                         "restored_pma": False, "board": False})
    return setup, rows


def transcript(setup, rows):
    return "\n".join(["NATIVE_G_SETUP " + json.dumps(setup),
                      *("NATIVE_G_ROW " + json.dumps(row) for row in rows), analysis.PASS]) + "\n"


def diagnostics():
    return "\n".join(analysis.WARNING_PAIR * 28)


class AnalysisTests(unittest.TestCase):
    def test_complete_fixed_matrix_is_source_only(self):
        setup, rows = output_fixture()
        self.assertEqual(analysis.analyze(transcript(setup, rows), diagnostics()), {"setup": setup, "rows": rows})
        self.assertIn("NOT_RTL_OR_BOARD", analysis.PASS)
        self.assertEqual(analysis.CONTRACT["reserved_operations"], 4 * setup["vertices"])
        self.assertEqual(analysis.CONTRACT["executed_operations"], 40)

    def test_rejects_changed_geometry_or_capacity(self):
        setup, rows = output_fixture()
        for key, value in (("cache_segments_per_half", 4), ("partition_vertices", 1024),
                           ("shards", 1), ("vertices", True), ("board", True),
                           ("hbm_bytes", 0), ("hbm_bytes", 24 * 512 * 1024**2), ("extra", 0)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                analysis.analyze(transcript({**setup, key: value}, rows), diagnostics())

    def test_rejects_missing_reordered_or_duplicate_rows(self):
        setup, rows = output_fixture()
        for changed in (rows[:-1], rows[::-1], rows + [rows[0]], [rows[0]] * 6):
            with self.assertRaises(ValueError):
                analysis.analyze(transcript(setup, changed), diagnostics())

    def test_rejects_forged_flags_ports_packet_counts_or_restoration(self):
        setup, rows = output_fixture()
        for key, value in (("cold_even", 0), ("packets", 1), ("edges", 1), ("updates", True),
                           ("complete_state_pass", False), ("direct_handoff_pass", False),
                           ("metadata_pass", False), ("restored_pma", True), ("board", True), ("extra", 0)):
            changed = copy.deepcopy(rows)
            changed[1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                analysis.analyze(transcript(setup, changed), diagnostics())

    def test_rejects_unknown_missing_or_extra_diagnostics(self):
        setup, rows = output_fixture()
        for stderr in ("", diagnostics() + "\nunknown warning", diagnostics() + analysis.WARNING_PAIR[0],
                       diagnostics().replace(analysis.WARNING_PAIR[0], "", 1)):
            with self.assertRaises(ValueError):
                analysis.analyze(transcript(setup, rows), stderr)

    def test_compile_retains_production_cache_and_native_source(self):
        argv = preparation.command(Path("/source"), Path("/vendor"), "g++", Path("/output/probe"))
        self.assertIn("/source/native_geometry/control.cpp", argv)
        self.assertNotIn("/source/host_prepared/control.cpp", argv)
        self.assertFalse(any("MAX_CACHE_SEGMENT" in flag for flag in argv))
        self.assertIn("-D_GLIBCXX_ASSERTIONS", argv)
        self.assertIn("-MD", argv)


class StudyTests(unittest.TestCase):
    def invoke(self, root, *, samples=None, failed=None, compile_stderr="", mutate=None):
        group = root / "group"
        group.mkdir()
        (group / "memory.events").write_text("oom 0\noom_kill 0\n")
        vendor = root / "vendor"
        vendor.mkdir()
        (vendor / "ap_int.h").write_text("mock header")
        output = root / "attempt"
        calls = []

        def prepare(target, upstream, integration):
            target.mkdir()
            (target / "source").mkdir()
            return []

        def execute(argv, cwd, prefix, **kwargs):
            calls.append((prefix.name, kwargs))
            prefix.parent.mkdir(exist_ok=True)
            if prefix.name == "compile":
                Path(argv[-1]).write_text("fake binary, not executed")
                stdout, stderr = "", compile_stderr
            else:
                stdout, stderr = transcript(*output_fixture()), diagnostics()
            prefix.with_suffix(".stdout.txt").write_text(stdout)
            prefix.with_suffix(".stderr.txt").write_text(stderr)
            return {"exit_code": int(prefix.name == failed), "stop_reason": "process_exit",
                    "cleanup_snapshot_error": None}

        with patch.object(study, "current", return_value=group), \
                patch.object(study, "verify", return_value={"limits": {"memory.max": str(4 * 1024**3)}}), \
                patch.object(study.preparation, "prepare", side_effect=prepare), \
                patch.object(study, "dependency_identities", return_value=[]), \
                patch.object(study, "run_link", side_effect=execute), \
                patch.object(study, "Lease") as lease, \
                patch.object(study, "available_memory_bytes", return_value=160 * 1024**3), \
                patch.object(study, "other_builds", return_value=["123 vivado"]), \
                patch.object(study.time, "monotonic", side_effect=[0, 0, 31]), \
                patch.object(study.time, "sleep", side_effect=mutate):
            lease.return_value.sample.side_effect = samples or [{"admitted": True}]
            try:
                result = study.run(output, root, root, vendor, wait_seconds=30)
            except (ValueError, RuntimeError, TimeoutError):
                result = json.loads((output / "results.json").read_text())
            return result, calls, lease.return_value

    def test_admits_while_other_tools_run_and_never_claims_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, lease = self.invoke(Path(directory))
            self.assertEqual((result["status"], len(result["rows"])), (analysis.PASS, 6))
            self.assertEqual([row[0] for row in calls], ["compile", "native"])
            self.assertEqual(calls[1][1]["timeout"], 1800)
            self.assertEqual(calls[1][1]["tree_memory_gib"], 4)
            self.assertTrue(lease.sample.call_args.kwargs["commit"])
            self.assertEqual(lease.sample.call_args.args[1], ["123 vivado"])
            self.assertTrue(all(result[key] is False for key in analysis.CLAIMS))
            lease.release.assert_called_once()

    def test_budget_wait_then_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, lease = self.invoke(Path(directory), samples=[{"admitted": False}, {"admitted": True}])
            self.assertEqual((result["status"], len(calls), lease.sample.call_count), (analysis.PASS, 2, 2))

    def test_no_child_on_budget_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, lease = self.invoke(Path(directory), samples=[{"admitted": False}] * 2)
            self.assertEqual((result["status"], calls), ("FAILED_RETAINED", []))
            self.assertIn("deadline", result["errors"][0])
            lease.release.assert_called_once()

    def test_compile_diagnostic_stops_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            result, calls, _ = self.invoke(Path(directory), compile_stderr="unknown warning")
            self.assertEqual((result["status"], len(calls)), ("FAILED_RETAINED", 1))

    def test_failed_child_retained(self):
        for label, count in (("compile", 1), ("native", 2)):
            with tempfile.TemporaryDirectory() as directory:
                result, calls, lease = self.invoke(Path(directory), failed=label)
                self.assertEqual((result["status"], len(calls)), ("FAILED_RETAINED", count))
                self.assertEqual(result["rows"], [])
                lease.release.assert_called_once()

    def test_invalid_wait_or_existing_output_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for wait in (0, -1, True, 1.5, 86401):
                with self.assertRaises(ValueError):
                    study.run(root, root, root, root, wait_seconds=wait)
            with self.assertRaises(FileExistsError):
                study.run(root, root, root, root)


if __name__ == "__main__":
    unittest.main()
