"""Host compiler failures and changed inputs must remain visible, not pass."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import build
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import identity


class SourceRetentionBuildTest(unittest.TestCase):
    def fixture(self, root):
        repository, integration = root / "repository", root / "integration"
        source = repository / "cpp/tests/publication_sources/source_retention/main.cpp"
        source.parent.mkdir(parents=True)
        source.write_text("int main() { return 0; }\n")
        compiler = root / "compiler"
        compiler.write_bytes(b"fixed compiler")
        return repository, integration, root / "output", compiler, source

    def pin(self, path):
        if str(path) == "/opt/xilinx/xrt/lib/libxilinxopencl.so":
            return {"path": str(path), "sha256": "test-library", "bytes": 1}
        return identity(path)

    def compile(self, command, **_):
        Path(command[command.index("-o") + 1]).write_bytes(b"executable")
        return subprocess.CompletedProcess(command, 0)

    def execute(self, args, run, **options):
        with patch.object(build, "identity", side_effect=self.pin), \
                patch.object(build.subprocess, "check_output", return_value="test compiler v1"), \
                patch.object(build.subprocess, "run", side_effect=run):
            return build.build(*args, **options)

    def test_both_hosts_use_same_flags_and_preserve_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            report = self.execute(args[:4], self.compile)
            self.assertEqual(report["status"], "SINGLE_RUN_HOSTS_BUILD_PASS_NOT_BOARD")
            self.assertEqual([r["arm"] for r in report["builds"]], ["reference", "candidate"])
            self.assertFalse(report["board_tested"])
            for record in report["builds"]:
                self.assertEqual(record["status"], "COMPILED")
                self.assertIn("-O2", record["command"])
                self.assertIn("-DNDEBUG", record["command"])
                self.assertNotIn("-DSPINE_RETENTION_TAIL_PUBLICATION=1", record["command"])
            self.assertEqual(report["candidate_publication"], "fixed")
            self.assertEqual(report["candidate_dispatch"], "interleaved")
            with self.assertRaises(FileExistsError):
                self.execute(args[:4], self.compile)

    def test_tail_publication_is_recorded_and_does_not_change_reference_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            report = self.execute(args[:4], self.compile, tail_publication=True)
            self.assertEqual(report["candidate_publication"], "tail")
            reference, candidate = report["builds"]
            flag = "-DSPINE_RETENTION_TAIL_PUBLICATION=1"
            self.assertNotIn(flag, reference["command"])
            self.assertIn(flag, candidate["command"])

    def test_prebound_dispatch_is_opt_in_for_candidate_only(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            report = self.execute(args[:4], self.compile, tail_publication=True, prebound_dispatch=True)
            self.assertEqual(report["candidate_dispatch"], "prebound")
            reference, candidate = report["builds"]
            flag = "-DSPINE_RETENTION_PREBOUND_DISPATCH=1"
            self.assertNotIn(flag, reference["command"])
            self.assertIn(flag, candidate["command"])

    def test_compiler_failure_preserves_attempt_and_error_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            def failure(command, **_):
                raise subprocess.CalledProcessError(1, command)
            with self.assertRaises(subprocess.CalledProcessError):
                self.execute(args[:4], failure)
            report = json.loads((args[2] / "manifest.json").read_text())
            self.assertEqual(report["status"], "HOST_BUILD_FAILED_RETAINED")
            self.assertEqual(report["builds"][0]["arm"], "reference")
            self.assertIn("CalledProcessError", report["error"])
            self.assertTrue((args[2] / "reference.stderr.txt").is_file())

    def test_input_change_during_compile_rejects_both_binaries(self):
        with tempfile.TemporaryDirectory() as directory:
            args = self.fixture(Path(directory))
            def change(command, **kwargs):
                args[4].write_text("changed source\n")
                return self.compile(command, **kwargs)
            with self.assertRaisesRegex(ValueError, "dependency changed"):
                self.execute(args[:4], change)
            report = json.loads((args[2] / "manifest.json").read_text())
            self.assertEqual(report["status"], "HOST_BUILD_FAILED_RETAINED")
            self.assertEqual(len(report["builds"]), 2)


if __name__ == "__main__":
    unittest.main()
