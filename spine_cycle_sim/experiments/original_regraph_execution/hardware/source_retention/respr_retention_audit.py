"""Recompute the same-clock ResPR stage gates from the original board receipts."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import active_min_candidate as g_control
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.candidate_board import (
    native_host_sha256, wait_for_image,
)
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.native_profile import update_only_profile
from . import clocks
from .analysis import profiled_runs, summarize
from .follow import unchanged
from .runtime import identity, save


CASES = ("skewed_sources", "amazon")
G_PASS = "G_GATE_PASS_FOR_AU_RES_PR_IMAGE"


def r_controls(board, frozen):
    if (board["status"] != "BOARD_EXECUTION_PASS_PENDING_ANALYSIS"
            or g_control.BOARDS.get(board["bdf"]) != board["device"]
            or board["matrix"]["stages"] != ["R"]
            or board["r_profile"] != frozen["r_profile"]
            or board["input_pins"] != frozen["input_pins"]
            or board["pins"]["r_reference"] != frozen["pins"]["r_reference"]):
        raise ValueError("R must use the frozen public A4 image, fixtures, and one-superstep profile")
    pins = [board["pins"][k] for k in ("r_reference", "r_current", "r_host", "r_candidate")]
    pins += [pin for group in board["input_pins"].values() for pin in group]
    unchanged(pins)
    result = {}
    for case in CASES:
        selected = [row for row in board["rows"] if row["stage"] == "R" and row["case"] == case]
        if (len(selected) != 2 or {r["arm"] for r in selected} != {"reference", "current"}
                or any(r["repetitions"] != 1 for r in selected)):
            raise ValueError("expected one original and one repaired R execution for " + case)
        rows = {row["arm"]: row for row in selected}
        runs, driver_mhz = {}, {}
        for arm, row in rows.items():
            runs[arm] = profiled_runs(row)
            binary = board["pins"]["r_" + arm]
            roots = {Path(pin["path"]).parent for pin in board["input_pins"][case]}
            if len(roots) != 1:
                raise ValueError("expected one pinned R fixture directory")
            fixture = str(roots.pop())
            device = str(board["device"])
            if arm == "reference":
                expected = [board["pins"]["r_host"]["path"], "board", fixture, "a4", "csr_degree",
                            row["result_directory"], binary["path"], device]
            else:
                expected = [board["pins"]["r_candidate"]["path"], binary["path"], fixture, device, "1"]
            if row["command"][-len(expected):] != expected:
                raise ValueError("R command does not match the pinned arm")
            if "clock_evidence" in row:
                clock = clocks.replay(row["clock_evidence"])
                if (clock["bdf"], clock["binary"]) != (board["bdf"], binary):
                    raise ValueError("R clock record does not match its arm")
                driver_mhz[arm] = clock["driver_reported_mhz"]
        matched = len(driver_mhz) == 2 and driver_mhz["reference"] == driver_mhz["current"]
        timing = summarize(runs["reference"], runs["current"], repetitions=1)
        result[case] = dict(timing, driver_mhz=driver_mhz, equal_driver_reported_clocks=matched,
                            retention_gate_pass=matched and timing["at_most_15_percent_slower"])
    return result


def g_gate(report, reference_path, image, host):
    graph, config, ref_clock, ref_runs, _, _ = g_control.reference_arm(reference_path)
    row = report["row"]
    bdf = ref_clock["bdf"]
    unchanged([*report["pins"].values(), row["stdout"], row["stderr"], row["oracle"]])
    if (report["pins"]["host"] != host or report["pins"]["reference"] != identity(reference_path)
            or report["pins"]["input"] != graph or report["repetitions"] != 1
            or report["board_launch_attempted"] is not True
            or (report["bdf"], report["device"]) != (bdf, g_control.BOARDS[bdf])
            or row["command"][-5:] != [host["path"], "--update-only", image["path"], graph["path"],
                                       row["oracle"]["path"]]):
        raise ValueError("G candidate command is not the exact image, host and frozen AU batch")
    profile = update_only_profile(Path(row["stdout"]["path"]).read_text(),
                                  Path(row["oracle"]["path"]).read_text(),
                                  bdf=bdf, reference=config)
    clock = clocks.replay(row["clock_evidence"])
    if bdf == g_control.QUALIFIED_BDF:
        g_control.matched_hbm.validate_after(report["clock_preparation"], row["clock_evidence"], 450, nominal=True)
    if clock["binary"] != image or profile != report["profile"] or profile["config"]["static_edges"] != "390847":
        raise ValueError("G clock or PMA oracle replay does not match the candidate")
    decision = g_control.compare(ref_runs, profile, ref_clock, clock)
    if any(decision[key] != value for key, value in report["comparison"].items()):
        raise ValueError("G raw event replay differs from the saved timing")
    return dict(decision, driver_mhz={"reference": ref_clock["driver_reported_mhz"],
                                     "current": clock["driver_reported_mhz"]})


def run(args):
    if args.output.exists():
        raise FileExistsError(args.output)
    fields = (args.route, args.r_report, args.g_report, args.g_reference, args.host)
    if any(fields) and not all(fields):
        raise ValueError("provide the route, R/G receipts, G reference and resident host together")
    pins = [identity(args.r_board), identity(args.frozen_r_board)]
    board, frozen = (json.loads(Path(pin["path"]).read_text()) for pin in pins)
    r = r_controls(board, frozen)
    admitted = all(row["retention_gate_pass"] for row in r.values())
    result = {"status": "R_ADMITTED_G_NOT_REPLAYED" if admitted else "R_NOT_ADMITTED",
              "inputs": pins, "image": board["pins"]["r_current"], "r": r}
    if all(fields):
        image, _, stage_pins = wait_for_image(args.route, args.r_report, 0, bdf=board["bdf"])
        image, host = identity(image), identity(args.host)
        if image != result["image"] or pins[0] not in stage_pins or host["sha256"] != native_host_sha256(args.route):
            raise ValueError("audited R receipt is not the exact route screen consumed by G")
        g_pin = identity(args.g_report)
        g = json.loads(args.g_report.read_text())
        if g["r_pins"] != stage_pins or g["bdf"] != board["bdf"]:
            raise ValueError("G did not screen the audited R route")
        pins.extend([*stage_pins, g_pin, identity(args.g_reference), host])
        result["g"] = g_gate(g, args.g_reference, image, host)
        mhz = result["g"]["driver_mhz"]["current"]
        result["matched_candidate_clocks"] = all(row["driver_mhz"].get("current") == mhz for row in r.values())
        result["status"] = ("BASELINE_STAGES_ADMITTED_NOT_CONVERGENCE"
                            if admitted and result["g"]["retention_gate_pass"] and result["matched_candidate_clocks"]
                            and g["status"] == G_PASS else "BASELINE_STAGES_NOT_ADMITTED")
    unchanged(pins)
    save(args.output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("r-board", "frozen-r-board", "output"):
        parser.add_argument("--" + name, required=True, type=lambda value: Path(value).resolve())
    for name in ("route", "r-report", "g-report", "g-reference", "host"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve())
    print(run(parser.parse_args())["status"], flush=True)


if __name__ == "__main__":
    main()
