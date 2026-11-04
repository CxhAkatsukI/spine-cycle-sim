"""After one exact R repair route, screen R once without launching a full matrix."""

import argparse
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, runner_pins, service_state,
)
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.tail_publication import host_pair
from . import analysis, checkpoint, clocks, returned_route, study
from .runtime import check_memory, identity, save


def unchanged(pins):
    for pin in pins:
        if not {"path", "sha256"} <= pin.keys() <= {"path", "sha256", "bytes"}:
            raise ValueError("path and SHA-256 input identity required")
        actual = identity(pin["path"])
        if any(actual[key] != value for key, value in pin.items()):
            raise ValueError("frozen repair control or runner changed")


def control(before, route, output):
    report = json.loads(before.read_text())
    if report["status"] != "BOARD_EXECUTION_PASS_PENDING_ANALYSIS" or report["matrix"]["stages"] != ["R"]:
        raise ValueError("completed R-only control required")
    supported = [row for row in report["rows"] if "stdout" in row]
    if (len(supported) != 4 or any(row.get("repetitions") != 1 for row in supported)
            or {(row["case"], row["arm"]) for row in supported} != {
                (case, arm) for case in ("skewed_sources", "amazon") for arm in ("reference", "current")}):
        raise ValueError("one measured run per declared supported R arm required")
    roots = {Path(p["path"]).parent.parent for group in report["input_pins"].values() for p in group}
    if len(roots) != 1:
        raise ValueError("one frozen R input root required")
    pins = [identity(before), *report["pins"].values(),
            *[pin for group in report["input_pins"].values() for pin in group]]
    unchanged(pins)
    args = argparse.Namespace(**{key: Path(pin["path"]) for key, pin in report["pins"].items()},
                              r_inputs=roots.pop(), output=output, device=report["device"],
                              bdf=report["bdf"], stages=["R"], r_single_run=True)
    args.r_predecessor = args.r_current
    args.r_current = route / "candidate.hw.xclbin"
    return args, pins


def matched_hosts(args, route_manifest, hosts):
    manifest = hosts / "manifest.json"
    build = json.loads(manifest.read_text())
    if "tail_hosts" not in route_manifest:
        if build.get("candidate_publication", "fixed") != "fixed":
            raise ValueError("fixed-publication route requires a fixed host")
        return []
    if route_manifest["tail_hosts"] != {key: value for key, value in identity(manifest).items() if key != "bytes"}:
        raise ValueError("tail route and paired host manifest do not match")
    binaries = host_pair(manifest)
    if binaries["reference"]["sha256"] != identity(args.r_host)["sha256"]:
        raise ValueError("the original R control binary must be unchanged")
    args.r_host = Path(binaries["reference"]["path"])
    args.r_candidate = Path(binaries["candidate"]["path"])
    return list(binaries.values())


def run(before, route, g_results, hosts, production, output, *, unit, invocation,
        maximum_wait=21600, poll_seconds=30, returned_candidate=None, board=None):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit)
            or not re.fullmatch(r"[0-9a-f]{32}", invocation)
            or type(maximum_wait) is not int or not 1 <= maximum_wait <= 43200
            or type(poll_seconds) is not int or not 1 <= poll_seconds <= 300):
        raise ValueError("exact route identity and bounded wait required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "unit": unit, "invocation": invocation,
              "errors": [], "states": [], "board_requested": False, "publication_match": False,
              "maximum_wait_seconds": maximum_wait, "poll_seconds": poll_seconds,
              "full_evaluation_started": False}
    write = lambda: save(output / "results.json", report)
    write()
    try:
        check_memory(require_live_reserve=False)
        args, pins = control(before, route, output / "board-once")
        if board is not None:
            if not returned_candidate or board != (0, "0000:82:00.1"):
                raise ValueError("board override requires the qualified card and a verified return")
            args.device, args.bdf = board
        report.update(device=args.device, bdf=args.bdf)
        predecessor = args.r_predecessor
        route_file = route / "manifest.json"
        route_manifest = json.loads(route_file.read_text())
        pins += matched_hosts(args, route_manifest, hosts)
        pins += [identity(route_file), identity(g_results), identity(hosts / "manifest.json"),
                 identity(Path(__file__)), *runner_pins()]
        report["pins"] = pins
        started = time.monotonic()
        while True:
            check_memory(require_live_reserve=False)
            unchanged(pins)
            state = service_state(unit)
            if not report["states"] or report["states"][-1] != state:
                report["states"].append(state)
            report.update(status="WAITING_FOR_EXACT_ROUTE", waited_seconds=time.monotonic() - started)
            write()
            if route_finished(state, invocation):
                break
            if report["waited_seconds"] >= maximum_wait:
                raise TimeoutError("R repair route wait expired")
            time.sleep(min(poll_seconds, maximum_wait - report["waited_seconds"]))
        if returned_candidate:
            returned, capsule, platform = returned_candidate
            args.r_current, image, proof = returned_route.admit(
                route, returned, capsule, platform, predecessor, output / "returned-admission")
            pins += [image, proof]
            report["returned_admission"] = proof
            args.board_wait_seconds = 21600
            args.strict_nominal_clocks = True
        else:
            execution = route / "execution/execution.json"
            routed = json.loads(execution.read_text())
            if (routed["status"] != "LINK_PASS_AWAITING_TIMING_AND_BOARD"
                    or Path(routed["xclbin"]["path"]) != args.r_current):
                raise ValueError("route exit lacks a matching completed hardware image")
            pins += [identity(execution), routed["xclbin"]]
        unchanged(pins)
        unchanged(route_manifest["pins"])
        report.update(status="SCREENING_R_ONCE", board_requested=True)
        write()
        measured = study.run(args)
        analysis.analyze(g_results, args.output / "results.json", output / "analysis")
        summary = json.loads((output / "analysis/summary.json").read_text())
        r_rows = [row for row in summary["pairs"] if row["stage"] == "R"]
        passed = len(r_rows) == 2 and all(row["at_most_15_percent_slower"] and row["clock_evidence_recorded"]
                                         for row in r_rows)
        if returned_candidate:
            observed = [clocks.replay(row["clock_evidence"]) for row in measured["rows"] if "stdout" in row]
            matched = len(observed) == 4 and all(row["bdf"] == args.bdf
                                                 and row["driver_reported_mhz"] == [150, 500, 450, 0]
                                                 for row in observed)
            report["all_four_arms_at_nominal_clocks"] = matched
            passed &= matched
        checkpoint.checkpoint(args.output, output / "analysis", hosts, production, output / "delivery")
        unchanged(pins)
        report.update(status="SUPPORTED_R_GATE_PASS_AWAITING_SPINE" if passed else "R_PERFORMANCE_GATE_FAILED_RETAINED",
                      supported_r_gate_pass=passed, analysis=identity(output / "analysis/summary.json"),
                      delivery=identity(output / "delivery/manifest.json"))
    except BaseException as error:
        report.update(status="FAILED_RETAINED")
        report["errors"].append(repr(error))
        raise
    finally:
        write()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "route", "g-results", "hosts", "production", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--unit", required=True)
    parser.add_argument("--invocation", required=True)
    parser.add_argument("--maximum-wait", type=int, default=21600)
    parser.add_argument("--returned-candidate", type=Path, nargs=3, metavar=("RETURNED", "CAPSULE", "XPFM"))
    parser.add_argument("--board", action="store_true", help="use qualified U55C at 0000:82:00.1")
    args = parser.parse_args()
    print(run(*(getattr(args, name).resolve() for name in
                ("before", "route", "g_results", "hosts", "production", "output")),
              unit=args.unit, invocation=args.invocation, maximum_wait=args.maximum_wait,
              returned_candidate=[p.resolve() for p in args.returned_candidate] if args.returned_candidate else None,
              board=(0, "0000:82:00.1") if args.board else None
              )["status"], flush=True)
