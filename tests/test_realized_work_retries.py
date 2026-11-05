import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work import receipts


class RetryReceiptsTests(unittest.TestCase):
    def campaign(self, root, *, passed=False, plugin="plugin", memory=8):
        root.mkdir()
        profile = root / "profile.json"
        profile.write_text('{"architecture":"fixed"}')
        run = root / "runs"
        run.mkdir()
        case = dict(execution_id="case", inputs={}, out_dir=str(run), role="trace_holdout",
                    command=["runner", "--profile", str(profile), "--out-dir", str(run)])
        (root / "matrix.json").write_text(json.dumps(dict(cases=[case])))
        identity = dict(plugin_sha256=plugin, git_revision="head", compiler="compiler",
                        source_hashes={"core": "sha"}, memory=dict(gib=memory),
                        matrix_sha256=sha256_file(root / "matrix.json"))
        (root / "identity.json").write_text(json.dumps(identity))
        (root / "status.json").write_text(json.dumps({"case": "PASS" if passed else "FAIL: memory"}))
        if passed:
            (run / "case_result.json").write_text('{"checked":true}')
        return case

    def test_retry_may_change_only_memory_and_paths_and_retains_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, retry = (Path(temporary) / name for name in ("base", "retry"))
            self.campaign(base)
            self.campaign(retry, passed=True, memory=16)
            before = (base / "status.json").read_bytes()
            with patch.object(receipts, "admit", return_value={"checked": True}):
                _, _, rows, origins = receipts.select(base, (retry,))
            self.assertEqual(rows, [{"checked": True}])
            self.assertTrue(origins[0]["retried"])
            self.assertEqual(origins[0]["campaign"], str(retry))
            self.assertEqual((base / "status.json").read_bytes(), before)

    def test_reject_changed_plugin_and_replacement_of_a_passing_row(self):
        for plugin, base_passed, message in (("different", False, "implementation"),
                                              ("plugin", True, "previously failed")):
            with self.subTest(plugin=plugin, base_passed=base_passed), tempfile.TemporaryDirectory() as temporary:
                base, retry = (Path(temporary) / name for name in ("base", "retry"))
                self.campaign(base, passed=base_passed)
                self.campaign(retry, passed=True, plugin=plugin)
                with self.assertRaisesRegex(ValueError, message):
                    receipts.select(base, (retry,))

    def test_reject_changed_role_command_or_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, retry = (Path(temporary) / name for name in ("base", "retry"))
            original = self.campaign(base)
            other = self.campaign(retry, passed=True)
            receipts.equivalent(original, other)
            changed = copy.deepcopy(other)
            changed["role"] = "trace_calibration"
            with self.assertRaisesRegex(ValueError, "split"):
                receipts.equivalent(original, changed)
            changed = copy.deepcopy(other)
            changed["command"].append("--faster-mode")
            with self.assertRaisesRegex(ValueError, "command"):
                receipts.equivalent(original, changed)
            (retry / "profile.json").write_text('{"architecture":"different"}')
            with self.assertRaisesRegex(ValueError, "profile"):
                receipts.equivalent(original, other)


if __name__ == "__main__":
    unittest.main()
