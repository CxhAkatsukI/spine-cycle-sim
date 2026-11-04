from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import active_min_follow, pair_resources


class ActiveMinQueueTests(unittest.TestCase):
    def test_public_cc_return_requires_verified_collector_pin(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            route = root / "returned"
            route.mkdir()
            image = route / active_min_follow.portable_return.BINARY
            image.write_bytes(b"public cc")
            transfer = root / "transfer.json"
            invocation, digest = "1" * 32, "a" * 64
            service = dict(LoadState="loaded", InvocationID=invocation, ActiveState="active",
                           SubState="exited", MainPID="0", Result="success", ExecMainStatus="0")
            transfer.write_text(json.dumps(dict(status=active_min_follow.portable_return.STATUS,
                                                receipt_sha256=digest, pins=[artifact.identity(image)])))
            self.assertEqual(active_min_follow.returned_ready("reference", route, digest, service, invocation, True),
                             artifact.identity(transfer))
            image.write_bytes(b"substituted public cc")
            with self.assertRaisesRegex(ValueError, "verified collector receipt"):
                active_min_follow.returned_ready("reference", route, digest, service, invocation, True)

    def test_dependency_requires_exact_invocation_and_terminal_receipt(self):
        with TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "queue.json"
            row = {"unit": "sparse.service", "invocation": "1" * 32, "journal": str(receipt), "observed": False}
            running = dict(LoadState="loaded", InvocationID=row["invocation"], MainPID="50",
                           ActiveState="active", SubState="running")
            gone = dict(LoadState="not-found", InvocationID="")
            with patch.object(active_min_follow, "service_state", return_value=gone):
                with self.assertRaisesRegex(ValueError, "never observed"):
                    active_min_follow.prior_finished(row)
            with patch.object(active_min_follow, "service_state", return_value=running):
                self.assertFalse(active_min_follow.prior_finished(row))
            with patch.object(active_min_follow, "service_state", return_value=gone):
                receipt.write_text(json.dumps({"status": "WAITING_FOR_BOTH_ROUTES"}))
                with self.assertRaisesRegex(ValueError, "terminal receipt"):
                    active_min_follow.prior_finished(row)
                receipt.write_text(json.dumps({"status": "PAIRED_ACTIVE_MIN_R_GATE_FAILED_RETAINED"}))
                self.assertTrue(active_min_follow.prior_finished(row))
            self.assertEqual(row["receipt"], artifact.identity(receipt))

    def test_dense_fixture_rejects_substituted_input(self):
        with TemporaryDirectory() as tmp:
            receipt, data = (Path(tmp) / name for name in ("fixture.json", "input"))
            data.write_bytes(b"dense")
            receipt.write_text(json.dumps({"frontier": "odd-vertices",
                "status": "ACTIVE_MIN_COMPONENT_INPUTS_OFFLINE_PASS", "input_pins": [artifact.identity(data)]}))
            pin = artifact.identity(receipt)
            args = SimpleNamespace(odd_fixture=(str(receipt), pin["sha256"]))
            self.assertEqual(active_min_follow.fixture_pin(args, [artifact.identity(data)]), pin)
            data.write_bytes(b"wrong")
            with self.assertRaisesRegex(ValueError, "frozen receipt"):
                active_min_follow.fixture_pin(args, [artifact.identity(data)])

    def test_releases_memory_before_board_retry_but_never_retries_body(self):
        events = []

        class Memory:
            held = False

            def sample(self, *_args, **_kwargs):
                self.held = True
                events.append("reserve")
                return {}

            def release(self):
                self.held = False
                events.append("release")

        @contextmanager
        def lease(*_args):
            events.append("lock")
            if events.count("lock") == 1:
                raise BlockingIOError("card reserved")
            yield Path("/dev/dri/renderD128"), 42

        with patch.object(pair_resources.concurrent, "Lease", return_value=Memory()), \
                patch.object(pair_resources.containment, "verify", return_value={"limits": {"memory.max": 8 * 2**30}}), \
                patch.object(pair_resources.containment, "other_builds", return_value=[]), \
                patch.object(pair_resources, "available_memory_bytes", return_value=128 * 2**30), \
                patch.object(pair_resources, "lease", lease), \
                patch.object(pair_resources.subprocess, "run",
                             return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=b"")), \
                patch.object(pair_resources.time, "sleep", side_effect=lambda _: events.append("sleep")), \
                self.assertRaisesRegex(BlockingIOError, "started arm"):
            with pair_resources.admit(0, "0000:82:00.1", Path("/test"), 60,
                                      lambda status, _: events.append(status)):
                raise BlockingIOError("started arm")
        self.assertEqual(events, ["reserve", "lock", "WAITING_FOR_BOARD", "release", "sleep",
                                  "reserve", "lock", "BOARD_ADMITTED", "release"])
