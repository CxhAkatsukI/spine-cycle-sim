"""Wait for exact offline/return services, then run the admitted full-graph matrices."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity as digest_identity
from ..common_g.complete_pipeline.hardware.algorithm_build import follow
from ..common_g.complete_pipeline.hardware.remote import qualification
from ..common_g.continuous_board.execution.supervisor import route_finished, runner_pins, service_state
from . import analysis, board_preparation, board_study, preparation, recheck

PASS = "THREE_ALGORITHM_FULLGRAPH_BOARD_PASS_NOT_SPINE_OR_PUBLICATION_MATCH"


def validate_service(unit, invocation):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit) or \
            not re.fullmatch(r"[0-9a-f]{32}", invocation):
        raise ValueError("explicit service and invocation required")


@dataclass(frozen=True)
class Request:
    algorithm: str
    unit: str
    invocation: str
    returned: Path
    admission: Path
    device: int

    def __post_init__(self):
        validate_service(self.unit, self.invocation)
        if self.algorithm not in preparation.ALGORITHMS or type(self.device) is not int or self.device not in (0, 1) or \
                any(not path.is_absolute() or ".." in path.parts for path in (self.returned, self.admission)) or \
                not self.admission.is_relative_to(self.returned):
            raise ValueError("known algorithm/card and admission within its absolute return attempt required")


def ready(request):
    state = service_state(request.unit)
    if not route_finished(state, request.invocation):
        return state, None
    path = request.returned / "results.json"
    result = json.loads(path.read_text())
    if result.get("errors") != []:
        raise ValueError("returned-artifact prerequisite has errors")
    if request.algorithm == "weighted_sssp":
        if result.get("status") != qualification.PASS or result.get("board_correctness_measured") is not True or \
                request.admission != request.returned / "board/routed_admission/summary.json":
            raise ValueError("SSSP production G/metadata/continuous-handoff qualification required")
        pinned = board_preparation.stamp_pins([result["board_report"]])[0]
        board = json.loads(Path(pinned["path"]).read_text())
        if board.get("admission") != json.loads(request.admission.read_text()):
            raise ValueError("SSSP qualification must bind the exact admitted artifact")
    elif result.get("status") != follow.PASS or result.get("algorithm") != request.algorithm or \
            result.get("admission") != digest_identity(request.admission):
        raise ValueError("algorithm return must bind the exact admitted artifact")
    return state, preparation.identity(path)


def run(preflight, output, requests, *, preflight_unit, preflight_invocation,
        maximum_wait=133200, poll_seconds=30, completed_preflight_sha256=None):
    validate_service(preflight_unit, preflight_invocation)
    if completed_preflight_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", completed_preflight_sha256):
        raise ValueError("explicit completed preflight SHA-256 required")
    if sorted(item.algorithm for item in requests) != sorted(preparation.ALGORITHMS) or \
            len(requests) != 3 or type(maximum_wait) is not int or not 1 <= maximum_wait <= 133200 or \
            type(poll_seconds) is not int or not 1 <= poll_seconds <= 300:
        raise ValueError("exact three-algorithm matrix and finite wait required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "WAITING_FOR_OFFLINE_PREPARATION", "errors": [], "matrices": [],
              "board_requested": False, "hardware_convergence_measured": False,
              "production_baseline_admitted": False, "spine_comparison": False, "publication_match": False,
              "requests": [{key: str(value) if isinstance(value, Path) else value for key, value in asdict(item).items()}
                           for item in requests], "states": {}, "maximum_wait_seconds": maximum_wait,
              "preflight_unit": preflight_unit, "preflight_invocation": preflight_invocation}
    report["completed_preflight_sha256"] = completed_preflight_sha256
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        pins = [preparation.identity(Path(pin["path"])) for pin in runner_pins()]
        if completed_preflight_sha256 is not None:
            # systemd may collect a successful transient unit. Re-admit its
            # complete frozen evidence, not the missing unit's default status.
            pin = preparation.identity(preflight / "results.json")
            if pin["sha256"] != completed_preflight_sha256:
                raise ValueError("completed offline report SHA-256 differs")
            offline = json.loads((preflight / "results.json").read_text())
            if offline.get("status") != analysis.PASS:
                raise ValueError("offline full-graph preparations failed")
            report["offline_replay"] = recheck.recheck(offline, lambda name: (preflight / name).read_text())
            preparation.unchanged(offline["pins"], full=True)
            report["preflight"] = pin
            report["offline_acceptance"] = "PINNED_COMPLETE_REPORT_REPLAY_NOT_SERVICE_EXIT_ATTESTATION"
            pins.append(pin)
        started = time.monotonic()
        pending = list(requests)
        while pending:
            preparation.unchanged(pins)
            offline_state = service_state(preflight_unit)
            report["states"][preflight_unit] = offline_state
            if completed_preflight_sha256 is not None and offline_state["LoadState"] == "not-found":
                offline_ready = True
            else:
                offline_ready = route_finished(offline_state, preflight_invocation)
            if offline_ready:
                offline = json.loads((preflight / "results.json").read_text())
                if offline.get("status") != analysis.PASS:
                    raise ValueError("offline full-graph preparations failed")
                if "preflight" not in report:
                    pin = preparation.identity(preflight / "results.json")
                    pins.append(pin)
                    report["preflight"] = pin
                report["status"] = "WAITING_FOR_ADMITTED_ARTIFACTS"
                for request in list(pending):
                    state, pin = ready(request)
                    report["states"][request.unit] = state
                    if pin is None:
                        continue
                    pins.append(pin)
                    matrix = {"algorithm": request.algorithm, "status": "REQUESTED",
                              "output": str(output / request.algorithm)}
                    report["matrices"].append(matrix)
                    report.update(status="RUNNING_" + request.algorithm, board_requested=True)
                    save()
                    child = board_study.run(preflight, request.admission, request.algorithm,
                        output / request.algorithm, device=request.device, repeats=3, execute=True)
                    matrix.update(status=child["status"], report=preparation.identity(
                        output / request.algorithm / "results.json"))
                    preparation.unchanged(pins, full=True)
                    if child["status"] != board_study.PASS or child["hardware_convergence_measured"] is not True:
                        raise ValueError("full-graph board matrix did not complete")
                    pending.remove(request)
                    save()
            report["waited_seconds"] = time.monotonic() - started
            report["pins"] = pins
            save()
            if pending:
                if report["waited_seconds"] >= maximum_wait:
                    raise TimeoutError("offline/returned prerequisites did not finish within the declared wait")
                time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        report.update(status=PASS, hardware_convergence_measured=True)
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        for matrix in report["matrices"]:
            path = Path(matrix["output"]) / "results.json"
            if path.exists():
                matrix.update(report=preparation.identity(path), status=json.loads(path.read_text())["status"])
        raise
    finally:
        save()
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "output", "requests"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("preflight-unit", "preflight-invocation"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--completed-preflight-sha256",
                        help="replay complete pinned evidence if systemd collected the finished preflight")
    args = parser.parse_args(argv)
    requests = [Request(**{**row, "returned": Path(row["returned"]), "admission": Path(row["admission"])})
                for row in json.loads(args.requests.read_text())]
    print(run(args.preflight.resolve(), args.output.resolve(), requests,
        preflight_unit=args.preflight_unit, preflight_invocation=args.preflight_invocation,
        completed_preflight_sha256=args.completed_preflight_sha256)["status"], flush=True)


if __name__ == "__main__":
    main()
