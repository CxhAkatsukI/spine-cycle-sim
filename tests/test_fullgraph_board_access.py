"""Lock retries are bounded and cannot retry an interrupted FPGA operation."""

from contextlib import contextmanager, nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import board_access


class CardAccessTests(unittest.TestCase):
    def setUp(self):
        self.measurement = patch.object(board_access, "measurement_lease", side_effect=nullcontext)
        self.measurement.start()
        self.addCleanup(self.measurement.stop)

    def test_busy_cooperative_owner_then_success(self):
        progress = Mock()

        @contextmanager
        def available(_device):
            yield Path("/dev/mock")

        with patch.object(board_access, "board_lease", side_effect=[BlockingIOError(), available(1)]) as lease, \
                patch.object(board_access.time, "monotonic", side_effect=[0, 1]), \
                patch.object(board_access.time, "sleep") as sleep:
            with board_access.wait_for_card(1, 10, progress) as render:
                self.assertEqual(render, Path("/dev/mock"))
            self.assertEqual(lease.call_count, 2)
            progress.assert_called_once()
            sleep.assert_called_once_with(9)

    def test_timeout_and_pin_or_reserve_failure_never_enter_body(self):
        for failure in (None, ValueError("pins drifted"), MemoryError("reserve lost")):
            progress = Mock(side_effect=failure)
            with patch.object(board_access, "board_lease", side_effect=BlockingIOError()), \
                    patch.object(board_access.time, "monotonic", side_effect=[0, 11]), \
                    self.assertRaises(type(failure) if failure else TimeoutError):
                with board_access.wait_for_card(1, 10, progress):
                    self.fail("must not operate on an occupied card")

    def test_board_body_failure_is_not_retried(self):
        @contextmanager
        def available(_device):
            yield Path("/dev/mock")

        with patch.object(board_access, "board_lease", side_effect=available) as lease, \
                self.assertRaises(BlockingIOError):
            with board_access.wait_for_card(1, 10, Mock()):
                raise BlockingIOError("driver failed after lock acquisition")
        lease.assert_called_once_with(1)

    def test_measurement_lock_excludes_other_matrix_then_releases(self):
        self.measurement.stop()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(board_access, "MEASUREMENT_LOCK", Path(directory) / "measurement.lock"):
            with board_access.measurement_lease():
                with self.assertRaises(BlockingIOError):
                    with board_access.measurement_lease():
                        self.fail("another matrix acquired the timing lease")
            with board_access.measurement_lease():
                pass


if __name__ == "__main__":
    unittest.main()
