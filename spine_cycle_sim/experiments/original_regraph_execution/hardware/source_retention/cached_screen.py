"""Screen the exact fixed-publication cached ResPR route once, then test its G."""

import argparse
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    runner_pins, service_state,
)
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import candidate_board
from . import analysis, checkpoint, follow, study
from .runtime import check_memory, identity, save


def stopped(state, invocation):
    if state["InvocationID"] not in ("", invocation):
        raise ValueError("cached route invocation changed")
    if state["ActiveState"] in ("active", "activating", "deactivating"):
        if state["LoadState"] != "loaded" or state["InvocationID"] != invocation:
            raise ValueError("cached route lost its active identity")
        return False
    if (state["LoadState"] not in ("loaded", "not-found")
            or (state["ActiveState"], state["SubState"], state["MainPID"],
                state["Result"], state["ExecMainStatus"]) != ("inactive", "dead", "0", "success", "0")):
        raise ValueError("cached route did not terminate successfully")
    return True


def completed(route, planned, plan_pin, group):
    execution = route / "execution/execution.json"
    launch = route / "execution/manifest.json"
    launched = json.loads(launch.read_text())
    result = json.loads(execution.read_text())
    resources = result.get("resources", {})
    image = result.get("xclbin", {})
    launch_plan_pin = {key: plan_pin[key] for key in ("path", "sha256")}
    if (launched["command"] != planned["command"] or launch_plan_pin not in launched["pins"]
            or result["status"] != "LINK_PASS_AWAITING_TIMING_AND_BOARD" or result["kind"] != "LINK"
            or result["containment"]["path"] != str(group) or not result["admission"]["admitted"]
            or (resources.get("exit_code"), resources.get("stop_reason")) != (0, "process_exit")
            or "cleanup_snapshot_error" not in resources or resources["cleanup_snapshot_error"] is not None
            or image.get("path") != str(route / "candidate.hw.xclbin")):
        raise ValueError("cached route lacks a matching clean execution and hardware image")
    follow.unchanged([*planned["pins"], *launched["pins"], image])
    return [identity(execution), identity(launch), image]


def run(args, *, poll_seconds=30):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", args.unit)
            or not re.fullmatch(r"[0-9a-f]{32}", args.invocation)
            or not 1 <= args.maximum_wait <= 64800):
        raise ValueError("exact cached service identity and wait of at most 18 hours required")
    out, route = args.output, args.route
    out.mkdir(parents=True, exist_ok=False)
    record = out / "results.json"
    report = {"status": "PREPARING", "unit": args.unit, "invocation": args.invocation,
              "board_requested": False, "full_evaluation_started": False, "states": []}
    save(record, report)
    try:
        check_memory()
        state = service_state(args.unit)
        if stopped(state, args.invocation) or int(state["MainPID"]) <= 0:
            raise ValueError("must witness the live cached route before waiting")
        cgroup = next(line.removeprefix("0::") for line in
                      Path(f"/proc/{state['MainPID']}/cgroup").read_text().splitlines() if line.startswith("0::"))
        group = Path("/sys/fs/cgroup") / cgroup.lstrip("/")
        if group.name != args.unit or service_state(args.unit) != state:
            raise ValueError("cached route changed while binding its cgroup")
        report.update(route_cgroup=str(group), states=[state])
        plan_path = route / "manifest.json"
        plan_pin = identity(plan_path)
        planned = json.loads(plan_path.read_text())
        if planned["status"] != "CACHED_RETRY_PREPARED_NOT_ROUTED" or "tail_hosts" in planned:
            raise ValueError("only the fixed-publication cached retry is admitted")
        board, pins = follow.control(args.before, route, out / "board-once")
        pins += follow.matched_hosts(board, planned, args.hosts)
        pins += [plan_pin, identity(args.g_results), identity(args.g_reference),
                 identity(args.hosts / "manifest.json"), identity(Path(__file__)), *runner_pins()]
        report.update(status="WAITING_FOR_EXACT_ROUTE", pins=pins)
        save(record, report)
        deadline = time.monotonic() + args.maximum_wait
        while True:
            state = service_state(args.unit)
            if state != report["states"][-1]:
                report["states"].append(state)
                save(record, report)
            if stopped(state, args.invocation):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("cached route wait expired")
            time.sleep(min(poll_seconds, remaining))
        check_memory()
        follow.unchanged(pins)
        pins += completed(route, planned, plan_pin, group)
        report.update(status="SCREENING_R_ONCE", board_requested=True)
        save(record, report)
        study.run(board)
        analysis.analyze(args.g_results, board.output / "results.json", out / "analysis")
        summary = out / "analysis/summary.json"
        rows = [row for row in json.loads(summary.read_text())["pairs"] if row["stage"] == "R"]
        passed = len(rows) == 2 and all(row["at_most_15_percent_slower"] and row["clock_evidence_recorded"]
                                       for row in rows)
        checkpoint.checkpoint(board.output, out / "analysis", args.hosts, args.production, out / "delivery")
        follow.unchanged(pins)
        report.update(status=candidate_board.R_PASS if passed else "R_PERFORMANCE_GATE_FAILED_RETAINED",
                      supported_r_gate_pass=passed, analysis=identity(summary),
                      delivery=identity(out / "delivery/manifest.json"))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(record, report)
    # Keep the completed R receipt immutable for the independent same-image G check.
    return candidate_board.run(args.g_reference, args.g_host_dir, route, record, out / "g")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "route", "g-results", "hosts", "production", "output", "g-reference", "g-host-dir"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--invocation", required=True)
    parser.add_argument("--maximum-wait", type=int, default=64800)
    print(run(parser.parse_args())["status"], flush=True)
