"""Wait for one frozen route, then run bounded G and resident G-to-SSSP checks."""

import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ...search_pipeline.synthesis import unchanged
from ...continuous_handoff import execution as handoff
from . import study as board

PASS = "COMPACT_G_GR_BOARD_CHECKS_PASS_NOT_BASELINE_ADMISSION"
FIELDS = ("LoadState", "ActiveState", "SubState", "InvocationID", "Result", "MainPID", "ExecMainStatus")


def service_state(unit):
    result = subprocess.run(["systemctl", "--user", "show", unit, "--no-pager",
        "--property=" + ",".join(FIELDS)], capture_output=True, text=True, timeout=10)
    rows = [line.split("=", 1) for line in result.stdout.splitlines()]
    if result.returncode or result.stderr or any(len(row) != 2 for row in rows):
        raise ValueError("cannot inspect the required route service")
    state = dict(rows)
    if set(state) != set(FIELDS) or len(rows) != len(FIELDS):
        raise ValueError("incomplete route service identity")
    return state


def route_finished(state, invocation):
    if state["LoadState"] != "loaded" or state["InvocationID"] != invocation:
        raise ValueError("route service disappeared or its invocation changed")
    terminal = (state["ActiveState"], state["SubState"]) in (("inactive", "dead"), ("active", "exited"))
    if not terminal and state["ActiveState"] in ("active", "activating", "deactivating"):
        return False
    if not terminal or state["Result"] != "success" or state["MainPID"] != "0" or state["ExecMainStatus"] != "0":
        raise ValueError("required route terminated unsuccessfully; no board execution")
    return True


def runner_pins():
    # Pin imported transitive owners as well as the two launch entry points.
    paths = {Path(module.__file__).resolve() for name, module in list(sys.modules.items())
             if name.startswith("spine_cycle_sim.") and (getattr(module, "__file__", "") or "").endswith(".py")}
    paths.add(Path(__file__).resolve())
    return [identity(path) for path in sorted(paths)]


def run(g_preflight, gr_preflight, route, original, output, *, route_unit, route_invocation,
        device=0, repeats=3, maximum_wait=86400, poll_seconds=30):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", route_unit) or \
            not re.fullmatch(r"[0-9a-f]{32}", route_invocation):
        raise ValueError("explicit route unit and invocation identity required")
    if type(device) is not int or device not in (0, 1) or type(repeats) is not int or not 3 <= repeats <= 10:
        raise ValueError("known device and 3--10 repetitions required")
    if any(type(value) not in (int, float) or not math.isfinite(value) or value <= 0
           for value in (maximum_wait, poll_seconds)):
        raise ValueError("positive finite route-wait bounds required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "route_states": [], "matrices": [],
              "route_unit": route_unit, "route_invocation": route_invocation,
              "device_index": device, "repeats": repeats, "maximum_wait_seconds": maximum_wait,
              "poll_seconds": poll_seconds, "board_started": False, "board_correctness_measured": False,
              **dict.fromkeys(board.CLAIMS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        report["containment"] = board.containment()
        g_host, g_pins = board.host_identity(g_preflight)
        gr_host, gr_pins = handoff.host_identity(gr_preflight)
        if len(g_host["contract"]["cases"]) != 6 or len(gr_host["contract"]["cases"]) != 9:
            raise ValueError("complete six-input G and nine-input handoff matrices required")
        manifest = json.loads((route / "manifest.json").read_text())
        pins = [identity(route / "manifest.json"), identity(original), *manifest["pins"],
                *g_pins, *gr_pins, *runner_pins()]
        report["pins"] = list({pin["path"]: pin for pin in pins}.values())
        started = time.monotonic()
        while True:
            unchanged(report["pins"])
            state = service_state(route_unit)
            if not report["route_states"] or report["route_states"][-1] != state:
                report["route_states"].append(state)
            report.update(status="WAITING_FOR_REQUIRED_ROUTE", waited_seconds=time.monotonic() - started)
            save()
            if route_finished(state, route_invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("required route wait expired; no board execution")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        # A successful systemd exit is not routed timing admission.
        report["admission"] = board.route.review(route, original, output / "routed_admission")
        checked = report["admission"]
        pins = report["pins"] + checked["pins"] + [checked["candidate"], checked["timing"]["report"]]
        report["pins"] = list({pin["path"]: pin for pin in pins}.values())
        report["status"] = "ROUTE_ADMITTED_BOARD_NOT_STARTED"
        save()
        plans = (("isolated_g", board.run, g_preflight, board.PASS, 6),
                 ("resident_gr", handoff.run, gr_preflight, handoff.BOARD_PASS, 9))
        for name, execute, preflight, expected, count in plans:
            unchanged(report["pins"])
            if not route_finished(service_state(route_unit), route_invocation):
                raise ValueError("required route is no longer terminal")
            matrix = {"name": name, "output": str(output / name), "status": "REQUESTED"}
            report["matrices"].append(matrix)
            report["status"] = "RUNNING_" + name
            save()
            result = execute(preflight, route, original, output / name,
                             device=device, repeats=repeats, execute=True)
            matrix.update(status=result["status"], report=identity(output / name / "results.json"))
            report["board_started"] = report["board_started"] or result["board_started"]
            save()
            if result["status"] != expected or result["board_correctness_measured"] is not True or \
                    result["board_started"] is not True or len(result["attempts"]) != repeats * count or \
                    any(result.get(key) is not False for key in board.CLAIMS):
                raise ValueError("board matrix did not complete its declared correctness scope")
        unchanged(report["pins"])
        report.update(status=PASS, board_correctness_measured=True)
    except BaseException as error:
        # Preserve child failure provenance, including whether programming was attempted.
        for matrix in report["matrices"]:
            child_path = Path(matrix["output"]) / "results.json"
            if child_path.is_file():
                try:
                    child = json.loads(child_path.read_text())
                    matrix.update(status=child["status"], report=identity(child_path))
                    report["board_started"] = report["board_started"] or child["board_started"]
                except (OSError, ValueError, KeyError, TypeError) as child_error:
                    report["errors"].append("child report unreadable: " + repr(child_error))
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
    save()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("g-preflight", "gr-preflight", "route", "original", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--route-unit", required=True)
    parser.add_argument("--route-invocation", required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--maximum-wait", type=float, default=86400)
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--execute", action="store_true", required=True)
    args = parser.parse_args(argv)
    result = run(*(path.resolve() for path in (args.g_preflight, args.gr_preflight, args.route,
        args.original, args.output)), route_unit=args.route_unit, route_invocation=args.route_invocation,
        device=args.device, repeats=args.repeats, maximum_wait=args.maximum_wait, poll_seconds=args.poll_seconds)
    print(result["status"], flush=True)


if __name__ == "__main__":
    main()
