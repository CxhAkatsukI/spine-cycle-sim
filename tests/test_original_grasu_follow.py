"""Remote original-G follow scope and failed-child provenance; no real SSH/XRT."""

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import original_grasu_return_fixture as fixture
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import admission, configuration as config, follow


class OriginalGFollowTests(unittest.TestCase):
    def test_sealer_is_bounded_and_explicit_about_packet_service(self):
        remote = follow.GraSURemote("user@host", 23333, Path("/runner"), Path("/packet"), Path("/attempt"),
                                   Path("/return"), fixture.UNIT, fixture.INVOCATION)
        with patch.object(follow.GraSURemote, "command", return_value="a" * 64) as command:
            self.assertEqual(remote.seal(), "a" * 64)
        argv = command.call_args.args[0]
        self.assertIn("--property=MemoryMax=4G", argv)
        self.assertEqual(argv[argv.index("--packet") + 1], Path("/packet"))
        self.assertEqual(argv[argv.index("--invocation") + 1], fixture.INVOCATION)

    def test_remote_failure_stops_before_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = Mock(unit=fixture.UNIT, invocation=fixture.INVOCATION)
            remote.state.return_value = dict(fixture.STATE, Result="exit-code", ExecMainStatus="1")
            with patch.object(follow, "current"), patch.object(follow, "verify", return_value={}), \
                    patch.object(follow, "runner_pins", return_value=[]), self.assertRaises(ValueError):
                follow.run(remote, root / "out")
            remote.seal.assert_not_called()
            remote.transfer.assert_not_called()

    def test_failed_board_child_preserves_uncertain_programming_state(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            remote = Mock(unit=fixture.UNIT, invocation=fixture.INVOCATION, capsule=Path("/packet"), attempt=Path("/attempt"))
            remote.state.return_value = fixture.STATE
            remote.seal.return_value = "a" * 64
            receipt = dict(unit=fixture.UNIT, invocation=fixture.INVOCATION,
                           remote_packet="/packet", remote_attempt="/attempt")
            for name, options in (("current", {}), ("verify", dict(return_value={})),
                    ("runner_pins", dict(return_value=[])), ("board.inputs", dict(return_value=(root / "host", [], []))),
                    ("admission.delivery.verify", dict(return_value=receipt))):
                stack.enter_context(patch.object(follow, name, **options) if "." not in name else
                    patch(follow.__name__ + "." + name, **options))

            def review(returned, output, **kwargs):
                output.mkdir()
                (output / "summary.json").write_text("{}")
                return dict(status=admission.PASS)

            def board(preflight, admitted, output, **kwargs):
                output.mkdir()
                (output / "results.json").write_text(json.dumps(dict(status="FAILED_RETAINED", board_programmed=None,
                    hardware_timing_measured=False, board_launch_attempted=True)))
                raise RuntimeError("host timed out")

            stack.enter_context(patch.object(follow.admission, "review", side_effect=review))
            stack.enter_context(patch.object(follow.board, "run", side_effect=board))
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                follow.run(remote, root / "out", board_preflight=root)
            report = json.loads((root / "out/results.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertIsNone(report["board_programmed"])
            self.assertTrue(report["board_launch_attempted"])
            self.assertFalse(report["publication_performance_match"])


if __name__ == "__main__":
    unittest.main()
