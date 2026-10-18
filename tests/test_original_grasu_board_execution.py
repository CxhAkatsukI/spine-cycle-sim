"""Original-G event/state parsing and exclusive-lease negatives; no XRT calls."""

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import configuration as config
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import analysis, execution


def output(root, *, damage=None):
    case = dict(facts=dict(updates=17), expected_slots_including_guards=128)
    events = [dict(role=role, queued=10, submitted=20, start=30, end=130) for role in sorted(analysis.ROLES)]
    observed = dict(status="FULL_STATE_PASS", bdf="0000:01:00.1", updates=17,
        checked_slots_including_guards=128, kernel_event_span_ns=100, readback_in_wall=False,
        host_preparation_in_wall=False, events=9, resident_wall_ms=0.1)
    if damage is not None:
        damage(events, observed)
    stdout, stderr = root / "stdout", root / "stderr"
    stdout.write_text("".join("ORIGINAL_G_EVENT " + json.dumps(row) + "\n" for row in events) +
                      "ORIGINAL_G_BOARD " + json.dumps(observed) + "\n")
    stderr.write_text("")
    return stdout, stderr, case


class OriginalGBoardExecutionTests(unittest.TestCase):
    def test_complete_event_span_and_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            checked = analysis.inspect(*output(Path(directory)), "0000:01:00.1")
        rows = [dict(case=name, repeat=rep, analysis=checked) for name in ("a", "b") for rep in range(3)]
        result = analysis.summaries(rows, ["a", "b"], 3)
        self.assertEqual(result[0]["median_kernel_event_span_ms"], 0.0001)
        for damaged in (rows[:-1], [*rows, rows[0]]):
            with self.assertRaises(ValueError):
                analysis.summaries(damaged, ["a", "b"], 3)

    def test_invalid_identity_state_timestamps_and_wall_rejected(self):
        mutations = [lambda e, o: e.pop(), lambda e, o: e[0].update(role=e[1]["role"]),
            lambda e, o: e[0].update(start=True), lambda e, o: e[0].update(end=29),
            lambda e, o: o.update(bdf="foreign"), lambda e, o: o.update(updates=1),
            lambda e, o: o.update(checked_slots_including_guards=0),
            lambda e, o: o.update(readback_in_wall=True), lambda e, o: o.update(host_preparation_in_wall=True),
            lambda e, o: o.update(kernel_event_span_ns=1), lambda e, o: o.update(resident_wall_ms=float("nan")),
            lambda e, o: o.update(resident_wall_ms=-1), lambda e, o: o.update(resident_wall_ms=True)]
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                analysis.inspect(*output(Path(directory), damage=mutation), "0000:01:00.1")

    def test_lease_wait_only_retries_acquisition_not_work(self):
        calls, sleeps, report = [], [], {}

        @contextmanager
        def lease(device):
            calls.append(device)
            if len(calls) == 1:
                raise BlockingIOError("held")
            yield Path("/render"), 7

        with patch.object(execution, "leased_board", lease), patch.object(execution, "unchanged"), \
                patch.object(execution, "available_memory_bytes", return_value=100 * 1024**3), \
                patch.object(execution.time, "sleep", side_effect=sleeps.append):
            with self.assertRaisesRegex(BlockingIOError, "body"):
                with execution.wait_for_board(0, report, lambda: None, []) as (_, fd):
                    self.assertEqual(fd, 7)
                    raise BlockingIOError("body must not be retried")
        self.assertEqual(calls, [0, 0])
        self.assertEqual(len(sleeps), 1)
        self.assertEqual(report["status"], "WAITING_FOR_EXCLUSIVE_BOARD_NOT_PROGRAMMED")

    def test_lease_wait_stops_on_memory_loss_or_deadline(self):
        for memory, error in ((0, MemoryError), (100 * 1024**3, TimeoutError)):
            with self.subTest(memory=memory), patch.object(execution, "unchanged"), \
                    patch.object(execution, "available_memory_bytes", return_value=memory), \
                    patch.object(execution, "leased_board", side_effect=BlockingIOError), self.assertRaises(error):
                with execution.wait_for_board(0, {}, lambda: None, [], maximum_wait=0):
                    self.fail("no board lease")

    def test_bad_admission_never_acquires_board(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            admitted = root / "admission"
            admitted.mkdir()
            (admitted / "summary.json").write_text(json.dumps(dict(status="LINK_ONLY", **dict.fromkeys(config.FLAGS, False))))
            with patch.object(execution, "current"), patch.object(execution, "verify", return_value={}), \
                    patch.object(execution, "inputs", return_value=(root / "host", [], [])), \
                    patch.object(execution, "leased_board") as lease, self.assertRaises(ValueError):
                execution.run(root, admitted, root / "out")
            lease.assert_not_called()
            report = json.loads((root / "out/results.json").read_text())
            self.assertFalse(report["board_launch_attempted"])
            self.assertTrue(all(report[flag] is False for flag in config.FLAGS))


if __name__ == "__main__":
    unittest.main()
