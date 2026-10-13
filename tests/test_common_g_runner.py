import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g import runner
from spine_cycle_sim.experiments.evaluation_impact.common_g.cached_hot import study as cached


class CommonGRunnerTests(unittest.TestCase):
    def run_fixture(self, directory, failure=None):
        root = Path(directory)
        core = root / "core"
        for name in ("core/liboriginal_grasu_cycle.a", "core/libspine_cycle_core.a",
                     "core/CMakeCache.txt", "core/compile_commands.json", "cpp/CMakeLists.txt",
                     "cpp/sst/Makefile", "cpp/tests/grasu_cached_processor_tests.cpp", "previous.json"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}")
        output = root / "run"
        previous = root / "previous.json"
        commands = []

        def prepare(path):
            (path / "one").mkdir(parents=True)
            (path / "one/input").write_text("resident")

        def analyze(report, old):
            if old != {} or report["errors"]:
                raise ValueError("complete result required")
            self.assertEqual(report["rows"][0]["observation"], {"arm": "new", "cycles": 1})
            return {"marker": 12}

        study = runner.Study("toy", lambda: [(64, "one", 1, "new")], prepare,
                             analyze, {"hardware_timing_admitted": False}, "TOY_COMPLETE", ("marker",))

        def execute(command, cwd, base, **limits):
            commands.append(command)
            self.assertEqual(cwd, root)
            self.assertEqual(limits, {"timeout": 600, "memory_gib": 1, "reserve_gib": 8})
            base.parent.mkdir(parents=True, exist_ok=True)
            stdout, stderr = Path(str(base) + ".stdout.txt"), Path(str(base) + ".stderr.txt")
            stdout.write_text("")
            stderr.write_text("")
            if command[0] == "cmake":
                build = output / "build"
                build.mkdir(exist_ok=True)
                for name in ("CMakeCache.txt", "compile_commands.json", "common_g_execution"):
                    (build / name).write_text("fixed")
            if command[0] == "taskset":
                Path(command[5]).write_text("full state")
                stdout.write_text("COMMON_G_RESULT " + json.dumps({"arm": "new", "cycles": 1}))
                if failure == "pin": previous.write_text('{"changed":true}')
                if failure == "parse": stdout.write_text("wrong tag")
            return {"stdout": str(stdout), "stderr": str(stderr),
                    "exit_code": 1 if failure == "build" and base.name == "build" else 0,
                    "timed_out": False}

        with patch.object(runner, "ROOT", root), patch.object(runner, "run_bounded", execute):
            if failure:
                with self.assertRaises(ValueError): runner.run(output, core, previous, study)
                report = json.loads((output / "results.json").read_text())
                self.assertEqual(report["status"], "FAILED_RETAINED")
                self.assertIn("error", report)
                return report, commands
            report = runner.run(output, core, previous, study)
            self.assertEqual(json.loads((output / "results.json").read_text()), json.loads(json.dumps(report)))
            return report, commands

    def test_shared_runner_retains_bounded_fixed_binary_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            report, commands = self.run_fixture(directory)
        self.assertEqual(report["status"], "TOY_COMPLETE")
        self.assertEqual(len(report["rows"]), 1)
        self.assertEqual(len(commands), 5)
        self.assertFalse(report["hardware_timing_admitted"])

    def test_failure_and_changed_pin_are_saved_not_promoted(self):
        for failure in ("build", "parse", "pin"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                report, _ = self.run_fixture(directory, failure)
                if failure == "parse": self.assertEqual(len(report["errors"]), 1)

    def test_cached_public_wrapper_keeps_original_declaration_and_status(self):
        with patch.object(cached, "execute_study", return_value="delegated") as execute:
            self.assertEqual(cached.run("output", "core", "previous"), "delegated")
        spec = execute.call_args.args[3]
        self.assertEqual(len(spec.matrix()), 190)
        self.assertEqual(spec.status, "CACHED_G_PREDICTION_VALIDATED_REFERENCE_TIMING_OPEN")
        self.assertFalse(spec.metadata["production_baseline_admitted"])


if __name__ == "__main__":
    unittest.main()
