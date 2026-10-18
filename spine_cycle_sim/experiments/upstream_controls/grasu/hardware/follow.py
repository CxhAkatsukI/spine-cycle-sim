"""Return one exact original-G build, strictly admit it, optionally run a board."""

from dataclasses import dataclass
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote.transport import Remote
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import route_finished, runner_pins
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, verify
from . import admission, configuration as config
from .board import execution as board

MODULE = "spine_cycle_sim.experiments.upstream_controls.grasu.hardware"
PASS = "ORIGINAL_G_REMOTE_RETURN_ADMITTED_NOT_BOARD_OR_PUBLICATION"


@dataclass(frozen=True)
class GraSURemote(Remote):
    def seal(self):
        result = self.command(["systemd-run", "--user", "--wait", "--pipe", "--quiet", "--collect",
            "--property=MemoryMax=4G", "--property=MemoryHigh=3G", "--property=MemorySwapMax=0",
            "--property=OOMPolicy=kill", "--property=RuntimeMaxSec=1800", "env",
            "PYTHONPATH=" + str(self.runner), "python3", "-m", MODULE, "seal",
            "--packet", self.capsule, "--attempt", self.attempt, "--output", self.returned,
            "--unit", self.unit, "--invocation", self.invocation], timeout=1860).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", result):
            raise ValueError("original G sealer did not return one receipt digest")
        return result


def run(remote, output, *, board_preflight=None, device=0, maximum_wait=133200, poll_seconds=30):
    if type(maximum_wait) is not int or not 1 <= maximum_wait <= 133200 or \
            type(poll_seconds) is not int or not 1 <= poll_seconds <= 300:
        raise ValueError("bounded original G route wait required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "states": [], "board_requested": False,
              "remote_unit": remote.unit, "remote_invocation": remote.invocation,
              **dict.fromkeys(config.FLAGS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        report["containment"] = verify(current(), memory_gib=4)
        pins = runner_pins()
        if board_preflight is not None:
            _, _, host_pins = board.inputs(board_preflight)
            pins += host_pins
        report["pins"] = pins
        started = time.monotonic()
        while True:
            unchanged(pins)
            state = remote.state()
            if not report["states"] or report["states"][-1] != state:
                report["states"].append(state)
            report.update(status="WAITING_FOR_EXACT_ORIGINAL_G_ROUTE", waited_seconds=time.monotonic() - started)
            save()
            if route_finished(state, remote.invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("original G remote route did not finish")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        report.update(status="RETURNING_ORIGINAL_G", receipt_sha256=remote.seal())
        save()
        remote.transfer(output / "returned")
        receipt = admission.delivery.verify(output / "returned", report["receipt_sha256"])
        if receipt["unit"] != remote.unit or receipt["invocation"] != remote.invocation or \
                receipt["remote_packet"] != str(remote.capsule) or receipt["remote_attempt"] != str(remote.attempt):
            raise ValueError("original G returned service or source packet changed")
        unchanged(pins)
        if not route_finished(remote.state(), remote.invocation):
            raise ValueError("original G service changed after transport")
        result = admission.review(output / "returned", output / "admission", receipt_sha256=report["receipt_sha256"])
        if result["status"] != admission.PASS:
            raise ValueError("original G strict admission incomplete")
        report.update(status=PASS, admission=identity(output / "admission/summary.json"))
        save()
        if board_preflight is not None:
            unchanged(pins)
            report.update(status="REQUESTING_ORIGINAL_G_BOARD", board_requested=True)
            save()
            result = board.run(board_preflight, output / "admission", output / "board", device=device)
            if result["status"] != board.PASS:
                raise ValueError("original G complete repeated board matrix required")
            report.update(status=board.PASS, board_report=identity(output / "board/results.json"),
                          board_programmed=True, hardware_timing_measured=True)
    except BaseException as error:
        child_path = output / "board/results.json"
        if child_path.is_file():
            try:
                child = json.loads(child_path.read_text())
                report.update(board_report=identity(child_path), board_programmed=child["board_programmed"],
                              hardware_timing_measured=child["hardware_timing_measured"],
                              board_launch_attempted=child["board_launch_attempted"])
            except (OSError, ValueError, KeyError, TypeError) as child_error:
                report["errors"].append("child report unreadable: " + repr(child_error))
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save()
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("target", "unit", "invocation"):
        parser.add_argument("--" + name, required=True)
    for name in ("runner", "packet", "attempt", "returned", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--board-preflight", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--device", type=int, choices=(0, 1), default=0)
    parser.add_argument("--port", type=int, default=23333)
    parser.add_argument("--maximum-wait", type=int, default=133200)
    args = parser.parse_args(argv)
    if args.execute != (args.board_preflight is not None):
        parser.error("board execution requires both --execute and --board-preflight")
    remote = GraSURemote(args.target, args.port, args.runner, args.packet, args.attempt, args.returned,
                         args.unit, args.invocation)
    print(run(remote, args.output.resolve(), board_preflight=args.board_preflight,
              device=args.device, maximum_wait=args.maximum_wait)["status"], flush=True)


if __name__ == "__main__":
    main()
