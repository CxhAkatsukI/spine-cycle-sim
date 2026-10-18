"""Run the frozen three-batch G correctness matrix only after routed admission."""

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Callable

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.board import board_lease, require_idle_board
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, verify
from ...search_pipeline.synthesis import unchanged
from ..analysis import CLAIMS, PASS as HOST_PASS
from ..delivery import validate as validate_host
from . import events, resources, route, runtime

PASS = "CONTINUOUS_G_BOARD_MATRIX_PASS_NOT_BASELINE_ADMISSION"


@dataclass(frozen=True)
class Experiment:
    host_identity: Callable
    analyze: Callable
    pass_status: str
    boundary: str
    source_files: tuple[Path, ...] = ()
    route_review: Callable | None = None


def containment():
    bounded = verify(current(), memory_gib=8)
    if int(bounded["limits"]["memory.high"]) > 7 * 1024**3:
        raise ValueError("board execution requires memory.high at most 7 GiB")
    return bounded


def host_identity(preflight):
    report = json.loads((preflight / "results.json").read_text())
    validate_host(preflight, report)
    if report["status"] != HOST_PASS:
        raise ValueError("complete host-model preflight required before board execution")
    source = preflight / "source/continuous_board/xrt.hpp"
    if 'std::getenv("CONTINUOUS_G_EXPECT_BDF")' not in source.read_text() or \
            "CL_DEVICE_PCIE_BDF" not in source.read_text():
        raise ValueError("preflight binary predates the pre-programming device identity guard")
    cases = report["contract"]["cases"]
    if any(row["shards"] != 1 for row in cases) or report["contract"]["cache_capacity_per_half"] != 131072:
        raise ValueError("first board matrix requires full cache and single-shard native inputs")
    return report, [identity(preflight / "results.json"), identity(preflight / "probe"),
                    *report["source"], *report["dependencies"]]


def run(preflight, route_attempt, original, output, *, device=0, repeats=3, execute=False, experiment=None):
    if type(repeats) is not int or repeats < 3 or repeats > 10 or type(device) is not int or device not in (0, 1):
        raise ValueError("known device and 3--10 repetitions required")
    experiment = experiment or Experiment(host_identity, events.analyze, PASS,
        "isolated resident G ready-to-handoff; not algorithm convergence or complete G+R")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "attempts": [], "device_index": device,
              "repeats": repeats, "execution_requested": execute, "board_started": False,
              **dict.fromkeys(CLAIMS, False), "board_correctness_measured": False,
              "boundary": experiment.boundary,
              "resources": {"memory_max_gib": resources.POLICY["tree_memory_gib"], "memory_high_gib": 7,
                            "reserve_gib": resources.POLICY["reserve_gib"],
                            "swap_max_bytes": 0, "timeout_seconds_per_case": 600, "cpu_affinity": [124, 125]}}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        host, pins = experiment.host_identity(preflight)
        binary = preflight / "probe"
        runtime.require_clean_environment(binary, output)
        review = experiment.route_review or route.review
        checked = review(route_attempt, original, output / "routed_admission")
        report.update(contract=host["contract"], routed_admission=checked)
        pins += checked["pins"] + [checked["candidate"], checked["timing"]["report"]]
        pins += [identity(path) for path in sorted(Path(__file__).parent.glob("*.py"))]
        pins += [identity(path) for path in experiment.source_files]
        report["pins"] = list({pin["path"]: pin for pin in pins}.values())
        unchanged(report["pins"])
        report["status"] = "BOARD_PREPARED_NOT_EXECUTED"
        save()
        if not execute:
            return report
        report["containment"] = containment()
        with board_lease(device) as render:
            require_idle_board(render)
            captured = runtime.capture(binary, render, output / "runtime")
            report["runtime"] = captured
            report["pins"] += captured["pins"]
            environment = dict(os.environ, CONTINUOUS_G_EXPECT_BDF=captured["device"]["bdf"], MALLOC_ARENA_MAX="2")
            save()
            for repeat in range(repeats):
                for case in host["contract"]["cases"]:
                    unchanged(report["pins"])
                    runtime.unchanged(captured, render)
                    runtime.require_clean_environment(binary, output)
                    require_idle_board(render)
                    name = f"r{repeat}_{case['case']}"
                    command = ["taskset", "-c", "124,125", str(binary), "--board", case["input"],
                               checked["candidate"]["path"], str(device)]
                    report.update(status="RUNNING_" + name, board_started=True)
                    save()
                    step = run_link(command, output, output / name, timeout=600,
                                    tree_memory_gib=resources.POLICY["tree_memory_gib"],
                                    reserve_gib=resources.POLICY["reserve_gib"],
                                    poll_seconds=0.2, environment=environment)
                    attempt = {"case": case["case"], "repeat": repeat, "resources": step}
                    report["attempts"].append(attempt)
                    save()
                    if step["exit_code"] or step["stop_reason"] != "process_exit" or step["cleanup_snapshot_error"]:
                        raise ValueError("board attempt failed or hit its resource bound; no automatic reset")
                    attempt["analysis"] = experiment.analyze(case, (output / (name + ".stdout.txt")).read_text(),
                        (output / (name + ".stderr.txt")).read_text(), bdf=captured["device"]["bdf"])
                    save()
                    print(f"{name} board correctness PASS", flush=True)
            runtime.unchanged(captured, render)
            unchanged(report["pins"])
        report.update(status=experiment.pass_status, board_correctness_measured=True)
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
    save()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("preflight", "route", "original", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    result = run(*(path.resolve() for path in (args.preflight, args.route, args.original, args.output)),
                 device=args.device, repeats=args.repeats, execute=args.execute)
    print(result["status"], flush=True)


if __name__ == "__main__":
    main()
