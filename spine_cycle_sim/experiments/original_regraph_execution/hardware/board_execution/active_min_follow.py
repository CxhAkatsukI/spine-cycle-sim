"""Wait for two pinned route jobs, then screen a single active-min R pair."""

import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, runner_pins, service_state,
)
from .. import artifact
from ..source_build import configuration, snapshot
from ..source_retention.runtime import check_memory, save
from . import active_min_pair


def ready(name, route, state, invocation, observed, algorithm):
    if state["LoadState"] == "loaded":
        finished = route_finished(state, invocation)
    elif observed and state["LoadState"] == "not-found" and not state["InvocationID"]:
        # systemd may garbage-collect a transient unit on successful exit.
        finished = True
    else:
        raise ValueError("route unit was never observed at its pinned invocation")
    if not finished:
        return False
    path = route / ("results.json" if name == "reference" else "execution/execution.json")
    expected = (configuration.routed_status("a4", algorithm=algorithm) if name == "reference"
                else "LINK_PASS_AWAITING_TIMING_AND_BOARD")
    if not path.is_file() or json.loads(path.read_text())["status"] != expected:
        raise ValueError(f"{name} route ended without successful artifact evidence")
    return True


def run(args):
    if not 1 <= args.wait_seconds <= 111600:
        raise ValueError("route wait must be bounded to 31 hours")
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "queue.json"
    report = {"status": "PREPARING", "routes": {}, "requested_pair": False}
    save(journal, report)
    try:
        check_memory()
        report["preflight_xrt_libraries"] = active_min_pair.paired_loader(args.reference_host, args.candidate_host)
        pins = [artifact.identity(path) for path in (*active_min_pair.input_paths(args),
                                                     args.candidate_route / "manifest.json")]
        pins += runner_pins()
        report["pins"] = pins
        for arm in ("reference", "candidate"):
            unit = getattr(args, arm + "_unit")
            invocation = getattr(args, arm + "_invocation")
            route = getattr(args, arm + "_route")
            if not (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit)
                    and re.fullmatch(r"[0-9a-f]{32}", invocation)):
                raise ValueError("each route needs an exact service and invocation ID")
            report["routes"][arm] = {"unit": unit, "invocation": invocation, "route": str(route), "observed": False}
        deadline = time.monotonic() + args.wait_seconds
        while True:
            report["status"] = "WAITING_FOR_BOTH_ROUTES"
            for arm, row in report["routes"].items():
                state = service_state(row["unit"])
                row["state"] = state
                row["observed"] |= state["LoadState"] == "loaded" and state["InvocationID"] == row["invocation"]
                row["ready"] = ready(arm, Path(row["route"]), state, row["invocation"], row["observed"], args.algorithm)
            save(journal, report)
            if all(row["ready"] for row in report["routes"].values()):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("both routes did not pass before the deadline")
            time.sleep(min(30, remaining))
        snapshot.unchanged(pins)
        report.update(status="REQUESTING_ONE_PAIRED_RUN", requested_pair=True)
        save(journal, report)
        args.output = args.output / "pair"
        measured = active_min_pair.run(args)
        report.update(status=measured["status"], result=artifact.identity(args.output / "results.json"),
                      retention_gate_pass=measured["retention_gate_pass"])
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(journal, report)
    return report


def wait_arguments(parser):
    for arm in ("reference", "candidate"):
        parser.add_argument(f"--{arm}-unit", required=True)
        parser.add_argument(f"--{arm}-invocation", required=True)
    parser.add_argument("--wait-seconds", type=int, default=108000)


if __name__ == "__main__":
    result = run(active_min_pair.parse_arguments(extend=wait_arguments))
    print(result["status"], flush=True)
    raise SystemExit(0 if result.get("retention_gate_pass") else 1)
