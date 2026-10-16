"""Wait for exact production-route/host invocations, then qualify the board path."""

import argparse
import json
import math
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from ..continuous_board.execution import study as board
from ..continuous_board.execution.supervisor import runner_pins, service_state, route_finished
from ..search_pipeline.synthesis import unchanged
from . import experiments, route as gate

PASS = "PRODUCTION_G_GR_BOARD_QUALIFICATION_PASS_NOT_BASELINE_ADMISSION"
POLICY = {"tree_memory_gib": 8, "reserve_gib": 24, "allow_bounded_builds": True}


def run(native_preflight, metadata_preflight, gr_preflight, route, original, output, *,
        route_unit, route_invocation, metadata_unit, metadata_invocation,
        device=0, repeats=3, maximum_wait=133200, poll_seconds=30):
    jobs = {"route": (route_unit, route_invocation), "metadata_host": (metadata_unit, metadata_invocation)}
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit) or
           not re.fullmatch(r"[0-9a-f]{32}", invocation) for unit, invocation in jobs.values()) or \
            route_unit == metadata_unit or type(device) is not int or device not in (0, 1) or \
            type(repeats) is not int or not 3 <= repeats <= 10 or any(
                type(value) not in (int, float) or not math.isfinite(value) or value <= 0
                for value in (maximum_wait, poll_seconds)):
        raise ValueError("distinct exact jobs, known board, 3--10 repeats and finite wait required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "states": [], "matrices": [],
              "jobs": jobs, "device_index": device, "repeats": repeats,
              "maximum_wait_seconds": maximum_wait, "poll_seconds": poll_seconds,
              "board_started": False, "board_correctness_measured": False, "policy": POLICY,
              **dict.fromkeys(board.CLAIMS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    lease = None
    save()
    try:
        report["containment"] = board.containment()
        frozen = gate.snapshot(route)
        atomic_write_json(output / "request.json", {"route_packet": frozen, "jobs": jobs})
        plans = experiments.plans(native_preflight, metadata_preflight, gr_preflight)
        pins = [identity(output / "request.json"), identity(original), *frozen["pins"], *runner_pins()]
        # The metadata preflight is still live; seal its terminal report only
        # after its exact service invocation succeeds and raw evidence replays.
        for name, preflight, spec, count in (plans[0], plans[2]):
            host, identities = spec.host_identity(preflight)
            if len(host["contract"]["cases"]) != count:
                raise ValueError("declared production board matrix scope changed: " + name)
            pins += identities
        report["pins"] = list({pin["path"]: pin for pin in pins}.values())
        started = time.monotonic()
        while True:
            unchanged(report["pins"])
            gate.unchanged_packet(route, frozen)
            states = {name: service_state(unit) for name, (unit, _) in jobs.items()}
            if not report["states"] or report["states"][-1] != states:
                report["states"].append(states)
            save()
            done = {name: route_finished(states[name], invocation) for name, (_, invocation) in jobs.items()}
            report.update(status="WAITING_FOR_EXACT_ROUTE_AND_METADATA_HOST",
                          waited_seconds=time.monotonic() - started)
            save()
            if all(done.values()):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("production prerequisites did not finish; no board requested")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        for name, preflight, spec, count in plans:
            host, identities = spec.host_identity(preflight)
            if len(host["contract"]["cases"]) != count:
                raise ValueError("declared production board matrix scope changed: " + name)
            pins += identities
        gate.unchanged_packet(route, frozen, complete=True)
        checked = gate.review(route, original, output / "routed_admission")
        report["admission"] = checked
        pins += [identity(route / "manifest.json"), *checked["pins"], checked["candidate"], checked["timing"]["report"]]
        report["pins"] = list({pin["path"]: pin for pin in pins}.values())
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", current())
        while True:
            unchanged(report["pins"])
            available = available_memory_bytes()
            # The shared case watchdog also retains its conservative 104-GiB
            # reserve. Meet it before acquiring the full peer-budget lease.
            enough = available >= 112 * 1024**3
            report["memory_admission"] = lease.sample(available, other_builds(), POLICY, commit=enough)
            report.update(status="WAITING_FOR_SAFE_BOARD_MEMORY", waited_seconds=time.monotonic() - started)
            save()
            if lease.held:
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("board memory budget did not fit; no board requested")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        for name, preflight, spec, count in plans:
            unchanged(report["pins"])
            for unit, invocation in jobs.values():
                if not route_finished(service_state(unit), invocation):
                    raise ValueError("production prerequisite is no longer terminal")
            matrix = {"name": name, "output": str(output / name), "status": "REQUESTED"}
            report["matrices"].append(matrix)
            report["status"] = "RUNNING_" + name
            save()
            result = board.run(preflight, route, original, output / name, device=device, repeats=repeats,
                               execute=True, experiment=spec)
            matrix.update(status=result["status"], report=identity(output / name / "results.json"))
            report["board_started"] = report["board_started"] or result["board_started"]
            save()
            if result["status"] != spec.pass_status or result["board_correctness_measured"] is not True or \
                    result["board_started"] is not True or len(result["attempts"]) != repeats * count or any(
                        result.get(key) is not False for key in board.CLAIMS):
                raise ValueError("incomplete production board correctness matrix: " + name)
        unchanged(report["pins"])
        report.update(status=PASS, board_correctness_measured=True)
    except BaseException as error:
        for matrix in report["matrices"]:
            child = Path(matrix["output"]) / "results.json"
            if child.is_file():
                try:
                    result = json.loads(child.read_text())
                    matrix.update(status=result["status"], report=identity(child))
                    report["board_started"] = report["board_started"] or result["board_started"]
                except (OSError, ValueError, KeyError, TypeError) as child_error:
                    report["errors"].append("child report unreadable: " + repr(child_error))
        report.update(status="FAILED_RETAINED")
        report["errors"].append(repr(error))
        raise
    finally:
        if lease is not None:
            lease.release()
        group = report.get("containment", {}).get("path")
        if group:
            report["memory_events_after"] = (Path(group) / "memory.events").read_text()
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("native-preflight", "metadata-preflight", "gr-preflight", "route", "original", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("route-unit", "route-invocation", "metadata-unit", "metadata-invocation"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--maximum-wait", type=float, default=133200)
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--execute", action="store_true", required=True)
    args = vars(parser.parse_args())
    args.pop("execute")
    for key, value in args.items():
        if isinstance(value, Path):
            args[key] = value.resolve()
    print(run(**args)["status"], flush=True)


if __name__ == "__main__":
    main()
