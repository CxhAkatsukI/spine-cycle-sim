"""Pin helper handshakes and reject misleading successful tool exits."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.sharded_k4_stages.segment_schedule import (
    BENCH, BENCH_SHA, FILES, FLOW_HASH, RTL_HASHES, TRIALS, parse_trace, validate_inputs,
)
from spine_cycle_sim.experiments.campaign_runtime import sha256_file


def trace():
    lines, start = [], 11
    for offset, count, latency, delay, elapsed in TRIALS:
        done = start + elapsed
        first, last = (done - 2 * count + 1, done) if count else (-1, -1)
        lines.append(f"SEGMENT offset={offset} count={count} latency={latency} ready_delay={delay} "
                     f"start={start} exit={start + 2 * count + 1} "
                     f"first_packet={first} last_packet={last} done={done} elapsed={elapsed}")
        start = done + 7
    return "\n".join(lines + ["SEGMENT_PASS cases=12"])


class SegmentScheduleTests(unittest.TestCase):
    def test_complete_trace_and_pinned_bench(self):
        rows = parse_trace(trace())
        self.assertEqual(len(rows), 12)
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(sha256_file(root / "cpp/tests/routed_regraph" / BENCH), BENCH_SHA)

    def test_tool_exit_alone_cannot_establish_success(self):
        good = trace()
        for bad in (good.replace("SEGMENT_PASS cases=12", ""), good + "\nFatal: mismatch",
                    good + "\nERROR: partial", good + "\nSEGMENT malformed",
                    good + "\nSEGMENT_PASS cases=12", "\n".join(good.splitlines()[1:]),
                    good.replace("elapsed=75", "elapsed=74", 1)):
            with self.subTest(trace=bad[-80:]), self.assertRaises(ValueError):
                parse_trace(bad)

    def test_completion_and_payload_timeline_required(self):
        good = trace()
        for bad in (good.replace("exit=12", "exit=13", 1),
                    good.replace("done=84", "done=85", 1),
                    good.replace("first_packet=-1", "first_packet=70", 1),
                    good.replace("last_packet=166", "last_packet=165", 1),
                    good.replace("first_packet=165", "first_packet=164", 1),
                    good.replace("start=91 exit=94", "start=80 exit=83", 1)):
            with self.subTest(trace=bad[:220]), self.assertRaises(ValueError):
                parse_trace(bad)

    def test_routed_identity_and_unbounded_run_script_required(self):
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "run.tcl").write_text("run all\nquit\n")
            pins = {FILES[k]: RTL_HASHES["original"][k] for k in ("parent", "helper")}
            pins.update({FILES["flow"]: FLOW_HASH, BENCH: BENCH_SHA})
            target = "spine_cycle_sim.experiments.sharded_k4_stages.segment_schedule.sha256_file"
            with patch(target, side_effect=lambda p: pins[p.name]):
                validate_inputs(directory, "original")
                (directory / "run.tcl").write_text("run 10 ns\nquit\n")
                with self.assertRaises(ValueError):
                    validate_inputs(directory, "original")
            with patch(target, return_value="wrong"), self.assertRaises(ValueError):
                validate_inputs(directory, "original")


if __name__ == "__main__":
    unittest.main()
