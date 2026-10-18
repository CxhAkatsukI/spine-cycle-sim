"""Return one exact remote algorithm link and admit it without requesting a board."""

from dataclasses import asdict, dataclass
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, verify
from ....continuous_board.execution.supervisor import route_finished, runner_pins
from ....search_pipeline.synthesis import unchanged
from ..remote.transport import Remote
from . import admission, artifacts, inputs

MODULE = "spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.algorithm_build"
PASS = "ALGORITHM_REMOTE_RETURN_ADMITTED_NOT_BOARD_OR_PUBLICATION"


@dataclass(frozen=True)
class AlgorithmRemote(Remote):
    compilation: Path

    def __post_init__(self):
        super().__post_init__()
        if not self.compilation.is_absolute() or ".." in self.compilation.parts:
            raise ValueError("explicit absolute remote compilation required")

    def seal(self):
        result = self.command(["systemd-run", "--user", "--wait", "--pipe", "--quiet", "--collect",
            "--property=MemoryMax=4G", "--property=MemoryHigh=3G", "--property=MemorySwapMax=0",
            "--property=OOMPolicy=kill", "--property=RuntimeMaxSec=1800", "env",
            "PYTHONPATH=" + str(self.runner), "python3", "-m", MODULE, "seal-route",
            "--compilation", self.compilation, "--route", self.attempt, "--output", self.returned,
            "--unit", self.unit, "--invocation", self.invocation], timeout=1860).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", result):
            raise ValueError("remote algorithm sealer did not return one receipt digest")
        return result


def run(remote, sources, algorithm, output, *, maximum_wait=133200, poll_seconds=30):
    if algorithm not in inputs.ALGORITHMS or type(maximum_wait) is not int or not 1 <= maximum_wait <= 133200 or \
            type(poll_seconds) is not int or not 1 <= poll_seconds <= 300:
        raise ValueError("declared algorithm and bounded wait/poll required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "algorithm": algorithm, "states": [],
              "remote": {key: str(value) if isinstance(value, Path) else value for key, value in asdict(remote).items()},
              "board_requested": False, "maximum_wait_seconds": maximum_wait,
              **dict.fromkeys(artifacts.FLAGS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        report["containment"] = verify(current(), memory_gib=4)
        manifest = inputs.verify(sources)
        report["pins"] = [identity(sources / "sources.json"), *runner_pins()]
        report["integration_revision"] = manifest["integration_revision"]
        started = time.monotonic()
        while True:
            unchanged(report["pins"])
            state = remote.state()
            if not report["states"] or report["states"][-1] != state:
                report["states"].append(state)
            report.update(status="WAITING_FOR_EXACT_REMOTE_ROUTE", waited_seconds=time.monotonic() - started)
            save()
            if route_finished(state, remote.invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("exact remote algorithm route did not finish")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        report["status"] = "SEALING_REMOTE_RETURN"
        save()
        report["receipt_sha256"] = remote.seal()
        save()
        remote.transfer(output / "returned")
        receipt = artifacts.verify(output / "returned", report["receipt_sha256"])
        if receipt["algorithm"] != algorithm or receipt["integration_revision"] != manifest["integration_revision"] or \
                receipt["unit"] != remote.unit or receipt["invocation"] != remote.invocation:
            raise ValueError("returned algorithm/source/service differs from the requested build")
        unchanged(report["pins"])
        if not route_finished(remote.state(), remote.invocation):
            raise ValueError("remote algorithm service changed after transport")
        report["status"] = "CHECKING_LOCAL_ADMISSION"
        save()
        result = admission.review(output / "returned", sources, output / "admission",
                                  receipt_sha256=report["receipt_sha256"])
        unchanged(report["pins"])
        if result["status"] != "ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD" or \
                result["algorithm"] != algorithm:
            raise ValueError("strict algorithm admission incomplete")
        report.update(status=PASS, admission=identity(output / "admission/summary.json"))
    except BaseException as error:
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
    for name in ("runner", "capsule", "attempt", "returned", "compilation", "sources", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--port", type=int, default=23333)
    parser.add_argument("--algorithm", choices=inputs.ALGORITHMS, required=True)
    parser.add_argument("--maximum-wait", type=int, default=133200)
    args = parser.parse_args(argv)
    remote = AlgorithmRemote(args.target, args.port, args.runner, args.capsule, args.attempt, args.returned,
                             args.unit, args.invocation, args.compilation)
    print(run(remote, args.sources.resolve(), args.algorithm, args.output.resolve(),
              maximum_wait=args.maximum_wait)["status"], flush=True)


if __name__ == "__main__":
    main()
