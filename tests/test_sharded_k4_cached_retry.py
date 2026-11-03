"""The cached retry must retain the original route and reject live or non-timeout attempts."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import cached_retry as retry


class CachedRetryTest(unittest.TestCase):
    invocation = "a" * 32
    state = {"LoadState": "loaded", "InvocationID": invocation, "ActiveState": "failed",
             "SubState": "failed", "MainPID": "0"}

    def command(self, output):
        return ["v++", "--config", str(output / "link.cfg"), "-o", str(output / "candidate.hw.xclbin"),
                "/frozen/pma_to_regraph_adapter.hw.xo"]

    def fixture(self, root, *, reason="timeout", cleanup=None, reached_optimization=True):
        previous, production, packet = (root / name for name in ("previous", "production", "packet"))
        (previous / "execution").mkdir(parents=True)
        (previous / "manifest.json").write_text(json.dumps({
            "production": str(production), "packet": str(packet), "timeout_seconds": 21600, "pins": [],
            "command": self.command(previous),
        }))
        (previous / "execution/manifest.json").write_text(json.dumps({
            "command": self.command(previous), "pins": [retry.identity(previous / "manifest.json")],
        }))
        (previous / "execution/execution.json").write_text(json.dumps({
            "status": "FAILED_RETAINED", "kind": "LINK",
            "resources": {"stop_reason": reason, "cleanup_snapshot_error": cleanup},
        }))
        (previous / "execution/job.stdout.txt").write_text(
            "Starting logic optimization..\n" if reached_optimization else "Block-level synthesis in progress\n")
        for path, payload in ((previous, b"attempt"), (production, b"production")):
            (path / "ip_cache").mkdir(parents=True)
            (path / "ip_cache/checkpoint.dcp").write_bytes(payload)
        (production / "results.json").write_text(json.dumps({
            "status": "ROUTED_NOT_BOARD_TESTED", "steps": [{"exit_code": 0}],
        }))
        return previous, production, packet, root / "retry"

    def invoke(self, previous, output):
        return retry.prepare(previous, output, unit="route.service", invocation=self.invocation)

    def test_copy_uses_previous_cache_only_after_block_synthesis_completed(self):
        for reached in (True, False):
            with self.subTest(reached=reached), tempfile.TemporaryDirectory() as folder:
                previous, production, packet, output = self.fixture(Path(folder), reached_optimization=reached)

                def prepare(*args):
                    self.assertEqual(args, (production, packet, output))
                    output.mkdir()
                    return {"pins": [], "command": self.command(output)}

                with patch.object(retry, "service_state", return_value=self.state), \
                        patch.object(retry.replacement, "prepare", side_effect=prepare):
                    result = self.invoke(previous, output)
                source = (previous if reached else production) / "ip_cache/checkpoint.dcp"
                copied = output / "ip_cache/checkpoint.dcp"
                self.assertEqual(copied.read_bytes(), source.read_bytes())
                self.assertFalse(copied.samefile(source))
                self.assertEqual(result["timeout_seconds"], 43200)
                self.assertEqual(result["command"], self.command(output))
                self.assertEqual(result["pins"][-1], retry.identity(output / "ip-cache-seed.json"))
                self.assertEqual(json.loads((previous / "manifest.json").read_text())["timeout_seconds"], 21600)
                with patch.object(retry.replacement, "run") as run:
                    retry.run(output)
                    run.assert_called_once_with(output, admission_wait=0)
                    run.reset_mock()
                    retry.run(output, admission_wait=21600)
                    run.assert_called_once_with(output, admission_wait=21600)
                    copied.write_bytes(b"changed checkpoint")
                    with self.assertRaisesRegex(ValueError, "content changed"):
                        retry.run(output)
                    run.assert_called_once_with(output, admission_wait=21600)

    def test_live_service_and_failed_cleanup_never_prepare(self):
        for state, reason, cleanup in (
            (dict(self.state, ActiveState="active", SubState="running"), "timeout", None),
            (self.state, "process_exit", None),
            (self.state, "timeout", "unknown worker"),
        ):
            with self.subTest(state=state, reason=reason, cleanup=cleanup), tempfile.TemporaryDirectory() as folder:
                previous, _, _, output = self.fixture(Path(folder), reason=reason, cleanup=cleanup)
                with patch.object(retry, "service_state", return_value=state), \
                        patch.object(retry.replacement, "prepare") as prepare, self.assertRaises(ValueError):
                    self.invoke(previous, output)
                prepare.assert_not_called()
                self.assertFalse(output.exists())

    def test_cache_symlink_and_unfinished_plan_cannot_be_used(self):
        with tempfile.TemporaryDirectory() as folder:
            previous, _, _, output = self.fixture(Path(folder))
            source = previous / "ip_cache"
            (source / "alias").symlink_to(source / "checkpoint.dcp")
            with self.assertRaisesRegex(ValueError, "regular files"):
                retry.seed_cache(source, output)
            output.mkdir()
            (output / "manifest.json").write_text(json.dumps({"status": "PREPARED_NOT_ROUTED"}))
            with patch.object(retry.replacement, "run") as run, self.assertRaisesRegex(ValueError, "cache seed"):
                retry.run(output)
            run.assert_not_called()
