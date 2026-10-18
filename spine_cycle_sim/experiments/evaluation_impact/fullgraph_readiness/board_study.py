"""Run one fixed algorithm's smoke and eight full graphs after routed admission."""

import os
from pathlib import Path
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.board import require_idle_board
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from ..common_g.continuous_board.execution import runtime
from . import board_access, board_analysis, board_preparation, board_protocol, preparation

PASS = "FULLGRAPH_ALGORITHM_BOARD_CONVERGENCE_PASS_NOT_SPINE_OR_PUBLICATION_MATCH"
POLICY = {"tree_memory_gib": 24, "reserve_gib": 32, "allow_bounded_builds": True}


def clean_environment(binary, output):
    runtime.require_clean_environment(binary, output)
    if any(os.environ.get(key) for key in (
            "GRASU_REGRAPH_EXPECT_BDF", "SPINE_EXPECT_BDF", "XCL_DEVICE_INDEX")):
        raise ValueError("board selection must come from the exclusive lease")


def run(preflight, admission, algorithm, output, *, device=0, repeats=3, execute=False,
        wait_seconds=3600, experiment=None):
    if type(device) is not int or device not in (0, 1) or type(repeats) is not int or not 3 <= repeats <= 10 or \
            type(wait_seconds) is not int or not 1 <= wait_seconds <= 86400:
        raise ValueError("known FPGA, 3--10 repetitions and bounded memory wait required")
    experiment = experiment or board_protocol.gr_experiment()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "attempts": [], "board_requested": False,
              "hardware_convergence_measured": False, "production_baseline_admitted": False,
              "spine_comparison": False, "publication_match": False, "device_index": device,
              "repeats": repeats, "policy": POLICY, "algorithm": algorithm,
              "boundary": experiment.boundary, "experiment": experiment.name,
              "execution_requested": execute}
    save = lambda: atomic_write_json(output / "results.json", report)
    lease = None
    save()
    try:
        plan = experiment.prepare(preflight, admission, algorithm)
        pins = plan["pins"]
        runners = {Path(module.__file__) for name, module in sys.modules.copy().items()
                   if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)}
        pins += [preparation.identity(path) for path in sorted(runners)]
        binary = Path(plan["binary"])
        report.update(plan=plan, pins=pins, cpu_affinity=sorted(os.sched_getaffinity(0)))
        if len(report["cpu_affinity"]) != 2:
            raise ValueError("fixed two-CPU affinity required")
        clean_environment(binary, output)
        preparation.unchanged(pins, full=True)
        report["status"] = "BOARD_PREPARED_NOT_EXECUTED"
        save()
        if not execute:
            return report
        report["containment"] = verify(current(), memory_gib=24)
        limits = report["containment"]["limits"]
        if int(limits["memory.max"]) != 24 * 1024**3 or int(limits["memory.high"]) > 22 * 1024**3:
            raise ValueError("exact 24-GiB max and at most 22-GiB high required")
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", current())
        deadline = time.monotonic() + wait_seconds
        while True:
            preparation.unchanged(pins)
            report["memory_admission"] = lease.sample(available_memory_bytes(), other_builds(), POLICY, commit=True)
            report["status"] = "WAITING_FOR_SAFE_MEMORY"
            save()
            if lease.held:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("full peer budgets and reserve did not fit; no board requested")
            time.sleep(min(10, remaining))
        def card_wait_progress():
            preparation.unchanged(pins)
            if available_memory_bytes() < POLICY["reserve_gib"] * 1024**3:
                raise MemoryError("system reserve lost while waiting for the card")
            report["status"] = "WAITING_FOR_EXCLUSIVE_CARD"
            save()

        with board_access.wait_for_card(device, wait_seconds, card_wait_progress) as render:
            require_idle_board(render)
            captured = runtime.capture(binary, render, output / "runtime")
            report["runtime"] = captured
            pins += board_preparation.stamp_pins(captured["pins"])
            environment = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LANG": "C", "LC_ALL": "C",
                           "MALLOC_ARENA_MAX": "2", "XILINX_XRT": "/opt/xilinx/xrt",
                           **experiment.environment(device, captured["device"]["bdf"])}
            report["environment"] = environment
            # A failed smoke or interrupted driver operation stops this matrix;
            # never reset hardware automatically or omit the unattempted rows.
            cases = [("smoke", row, index) for index, row in enumerate(
                plan.get("smokes", [plan["smoke"]]))] + [
                ("matrix", row, repeat) for repeat in range(repeats) for row in plan["rows"]]
            for scope, row, repeat in cases:
                preparation.unchanged(pins)
                runtime.unchanged(captured, render)
                clean_environment(binary, output)
                require_idle_board(render)
                name = f"{scope}_r{repeat}_{row['dataset']}"
                attempt = {"scope": scope, "dataset": row["dataset"], "repeat": repeat, "status": "RUNNING"}
                report["attempts"].append(attempt)
                report.update(status="RUNNING_" + name, board_requested=True)
                save()
                step = run_link(experiment.command(plan, row, output / (name + ".result.txt")),
                                output, output / "raw" / name, timeout=600 if scope == "smoke" else 1800,
                                tree_memory_gib=24, reserve_gib=32, environment=environment)
                attempt["resources"] = step
                save()
                if step["exit_code"] or step["stop_reason"] != "process_exit" or step["cleanup_snapshot_error"]:
                    attempt["status"] = "FAILED_RETAINED"
                    raise ValueError("board child failed or was stopped; no automatic reset or next case")
                attempt["analysis"] = experiment.analyze(row,
                    (output / "raw" / (name + ".stdout.txt")).read_text(),
                    (output / "raw" / (name + ".stderr.txt")).read_text(), bdf=captured["device"]["bdf"])
                if experiment.writes_result_file:
                    attempt["result_identity"] = preparation.identity(output / (name + ".result.txt"))
                attempt["status"] = "PASS"
                save()
                print(f"{name}: convergence and event ledger PASS", flush=True)
            runtime.unchanged(captured, render)
            preparation.unchanged(pins, full=True)
        report.update(status=experiment.pass_status, hardware_convergence_measured=True)
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        if report["attempts"] and report["attempts"][-1]["status"] == "RUNNING":
            report["attempts"][-1]["status"] = "FAILED_RETAINED"
        raise
    finally:
        if lease is not None:
            lease.release()
        group = report.get("containment", {}).get("path")
        if group:
            report["memory_events_after"] = (Path(group) / "memory.events").read_text()
            events = dict(line.split() for line in report["memory_events_after"].splitlines())
            if report["status"] == experiment.pass_status and any(int(events[key]) for key in ("max", "oom", "oom_kill", "oom_group_kill")):
                report.update(status="FAILED_RETAINED", hardware_convergence_measured=False)
                report["errors"].append("memory-limit or OOM events prevent acceptance")
        save()
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "admission", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--algorithm", choices=preparation.ALGORITHMS, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--wait-seconds", type=int, default=3600)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.preflight.resolve(), args.admission.resolve(), args.algorithm, args.output.resolve(),
                 device=args.device, repeats=args.repeats, execute=args.execute, wait_seconds=args.wait_seconds)
    print(report["status"], flush=True)
    return 0 if report["status"] in (PASS, "BOARD_PREPARED_NOT_EXECUTED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
