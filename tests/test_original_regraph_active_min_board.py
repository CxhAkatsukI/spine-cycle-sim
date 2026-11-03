import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware import artifact
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import active_min


class ActiveMinReferenceTests(unittest.TestCase):
    def test_replays_raw_events_and_all_published_buffers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            offline = {"algorithm": "cc", "topology": "a4", "iterations": 1, "vertices": 2,
                       "logical_edges": 1, "physical_edges": 8, "tasks": 1}
            bdf = "0000:c1:00.1"
            (root / "execution.u32le").write_bytes(
                struct.pack("<16I", 0x3447524F, 1, 2, 1, 65536, 65536, 1, 1, 0, 0, 3, 0, 65536, 0, 16, 0))
            for name in ("expected", "apply_property", *(f"replica{i}" for i in range(4))):
                (root / (name + ".u32le")).write_bytes(b"correct")
            expected = artifact.identity(root / "expected.u32le")
            events = [
                {"role": role, "ordinal": 0, "lane": lane, "queued_ns": 0, "submitted_ns": 1,
                 "start_ns": start, "end_ns": stop}
                for role, lane, start, stop in (("hbm_wrapper", 0, 2, 100), ("apply", 0, 3, 80),
                                                ("little", 3, 4, 79))
            ]
            result = {**offline, "bdf": bdf, "events": events, "status": "A4_ACTIVE_MIN_BOARD_PASS",
                      "hardware_timing_measured": True, "enqueue_to_completion_ms": 1.0,
                      "event_span_ns": 98, "event_union_ns": 98}
            result_path = root / "result.json"
            result_path.write_text(json.dumps(result))
            self.assertEqual(active_min.inspect(root, offline, expected, root, bdf)["event_span_ns"], 98)
            for changes in ({"iterations": True}, {"algorithm": "weighted_sssp"}, {"event_span_ns": 99},
                            {"events": [*events[:-1], {**events[-1], "lane": 2}]}):
                with self.subTest(changes=changes), self.assertRaises(ValueError):
                    result_path.write_text(json.dumps({**result, **changes}))
                    active_min.inspect(root, offline, expected, root, bdf)
            result_path.write_text(json.dumps(result))
            for name in ("apply_property", "replica3"):
                path = root / (name + ".u32le")
                path.write_bytes(b"wrong")
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "offline CSR oracle"):
                    active_min.inspect(root, offline, expected, root, bdf)
                path.write_bytes(b"correct")

    def test_route_failure_cannot_launch_or_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "memory.high").write_text(str(7 * 2**30))
            host = root / "host"
            host.touch()
            for name in active_min.INPUTS + active_min.STATE["cc"]:
                (root / f"{name}.u32le").touch()
            output = root / "output"
            with patch.object(active_min, "check_memory", return_value=root), \
                    patch.object(active_min.admission, "review", side_effect=ValueError("unrouted")) as review, \
                    patch.object(active_min, "lease") as lease, \
                    self.assertRaisesRegex(ValueError, "unrouted"):
                active_min.run(root, host, root, output, algorithm="cc", device=1, bdf="0000:c1:00.1")
            review.assert_called_once_with(root, output / "routed_admission", topology="a4", algorithm="cc")
            lease.assert_not_called()
            report = json.loads((output / "results.json").read_text())
            self.assertEqual(report["status"], "FAILED_RETAINED")
            self.assertFalse(report["board_launch_attempted"])
            self.assertFalse(report["hardware_timing_measured"])
