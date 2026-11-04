"""Queue the remaining frozen CC pairs on the balanced resident wall hosts."""

import argparse
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    runner_pins, service_state,
)
from . import active_min_admission, active_min_resident as resident, active_min_resident_follow as follow
from . import cc_resident_wall, resident_matrix, spine_cc_layout
from .follow import unchanged
from .resident_matrix import stage_jobs
from .runtime import identity, save


SMALL = ("AU", "SU", "WK")
LARGE = ("SO", "PK", "LJ", "LJ08")


def load(path):
    return json.loads(path.read_text())


def layout_packet(args, ds, small, campaign, template, row):
    if ds in SMALL:
        inputs, stdout = small[ds]
        expected = []
    else:
        if ds.lower() not in campaign["rows"]:
            raise ValueError("large host layout did not complete")
        expected = campaign["rows"][ds.lower()]
        inputs = args.large_inputs / ds.lower() / "inputs.json"
        stdout = args.large_layout / ds.lower() / "layout.stdout.txt"
    packet = args.output / f"{ds.lower()}.packet.json"
    save(packet, dict(template, inputs=str(inputs)))
    case, frozen = resident.frozen_case(args.previous, "cc", ds)
    configured, pins = cc_resident_wall.configure(argparse.Namespace(algorithm="cc", cc_wall_packet=packet),
                                                  case, frozen)
    log = identity(stdout)
    counts = spine_cc_layout.layout_counts(stdout.read_text(), case["updates"])
    if expected:
        command = [configured["spine_host"], "--layout-only", "--hot", "balanced", "--slice",
                   configured["graph_slice"], "--update", configured["update_slice"]]
        run = expected["execution"]
        if (expected["input"] != load(inputs) or expected["counts"] != counts or
                (run["command"], run["exit_code"], run["stop_reason"], run["cleanup_snapshot_error"])
                != (command, 0, "process_exit", None)):
            raise ValueError("large layout receipt does not match the balanced host and frozen inputs")
    row.update(case=configured, layout=counts, pins=[*frozen, *pins, log])
    return packet


def wait_for_layout(args, deadline):
    path = args.large_layout / "results.json"
    while True:
        if path.is_file():
            report = load(path)
            if report["status"] in ("LAYOUT_PASS_OFFLINE", "FAILED_RETAINED"):
                pin = identity(path)
                if load(path) != report or report["host"]["sha256"] != cc_resident_wall.SPINE_HOST:
                    raise ValueError("unexpected large layout report or host")
                return report, pin
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("large offline layout campaign did not finish")
        time.sleep(min(30, remaining))


def run(args):
    small = {ds: (Path(inputs).resolve(), Path(log).resolve()) for ds, inputs, log in args.small}
    if (args.algorithm, args.dataset) != ("cc", "R19") or args.cc_wall_packet is None or (
            len(args.small) != len(SMALL) or set(small) != set(SMALL)):
        raise ValueError("provide the R19 wall packet as template and all three small layout inputs")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,75}", args.child_prefix)
            or not 1 <= args.stage_wait_seconds <= 111600 or not 0 <= args.wait_seconds <= 21600):
        raise ValueError("expected a valid service prefix and bounded waits")
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "matrix.json"
    include_r19 = getattr(args, "include_r19", False)
    datasets = (*SMALL, *LARGE, "R19") if include_r19 else (*SMALL, *LARGE)
    rows = {ds: {"status": "NOT_REQUESTED"} for ds in datasets}
    report = dict(status="WAITING_FOR_G_AND_BOTH_R_GATES", cases=rows,
                  repetitions_per_arm=1, warmups=0)
    if not include_r19:
        report["r19_not_repeated"] = str(args.r19_output)
    save(journal, report)
    try:
        jobs = stage_jobs(args)
        report["stages"] = jobs
        pins = [*runner_pins(), *(identity(module.__file__) for module in
                 (resident, resident_matrix, cc_resident_wall, spine_cc_layout, follow)),
                identity(__file__), identity(args.cc_wall_packet)]
        template = load(args.cc_wall_packet)
        packets = {ds: layout_packet(args, ds, small, None, template, rows[ds]) for ds in SMALL}
        if include_r19:
            case, frozen = resident.frozen_case(args.previous, "cc", "R19")
            configured, packet_pins = cc_resident_wall.configure(args, case, frozen)
            rows["R19"].update(case=configured, pins=[*frozen, *packet_pins])
            packets["R19"] = args.cc_wall_packet
        deadline = time.monotonic() + args.stage_wait_seconds
        while True:
            for key, job in jobs.items():
                if not job.get("ready"):
                    job["ready"] = follow.ready(job, service_state(job["unit"]),
                                                follow.STAGE_PASS["r" if key == "odd" else key], "cc")
            save(journal, report)
            if all(job["ready"] for job in jobs.values()):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("G and both R gates did not pass before deadline")
            time.sleep(min(30, remaining))
        pins.extend(job["receipt"] for job in jobs.values())
        unchanged(pins)
        gate = active_min_admission.admit("cc", args.route, args.host, args.r_report,
                                          args.r_inputs, args.g_report, args.g_reference)
        odd, odd_pins = resident_matrix.admitted_odd(args, gate)
        resident_matrix.check_stage_receipts(jobs, gate, odd)
        pins.extend([*odd_pins, gate["host"], gate["image"], gate["g"]["reference"]])
        report.update(status="RUNNING_SINGLE_PASS", baseline=gate, odd_r=odd)
        campaign = None
        for ds, row in rows.items():
            if ds in LARGE:
                if campaign is None:
                    report["status"] = "WAITING_FOR_LARGE_LAYOUT"
                    save(journal, report)
                    try:
                        campaign, layout_pin = wait_for_layout(args, deadline)
                        pins.append(layout_pin)
                        report.update(status="RUNNING_SINGLE_PASS", large_layout=layout_pin)
                    except TimeoutError as error:
                        campaign = {"rows": {}, "error": str(error)}
                try:
                    packets[ds] = layout_packet(args, ds, small, campaign, template, row)
                except (OSError, ValueError) as error:
                    row.update(status="LAYOUT_NOT_ADMITTED", error=campaign.get("error", str(error)))
                    continue
            unchanged([*pins, *row["pins"]])
            output = args.output / ds.lower()
            command = resident_matrix.child_command(args, ds, row["case"]["memory_gib"], output,
                                                    packet=packets[ds])
            row.update(status="REQUESTED", command=command)
            save(journal, report)
            row.update(resident_matrix.run_child(command, args.output / f"{ds.lower()}.service.log",
                                                 output, ds, gate, cc_resident_wall.BOUNDARY))
            save(journal, report)
        report["status"] = ("MEASURED_REMAINING_CC_PAIRS" if
                            all(row["status"] == resident_matrix.MEASURED for row in rows.values())
                            else "CC_MATRIX_WITH_FAILURES")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(journal, report)
    return report


def arguments(parser):
    follow.arguments(parser)
    parser.add_argument("--small", nargs=3, action="append", required=True, metavar=("DATASET", "INPUTS", "STDOUT"))
    for name in ("odd-output", "odd-inputs", "large-inputs", "large-layout"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    r19 = parser.add_mutually_exclusive_group(required=True)
    r19.add_argument("--r19-output", type=lambda value: Path(value).resolve(), help="record a separate R19 queue")
    r19.add_argument("--include-r19", action="store_true", help="run R19 once in this matrix using the template packet")
    parser.add_argument("--odd-unit", required=True)
    parser.add_argument("--odd-invocation", required=True)
    parser.add_argument("--odd-fixture", nargs=2, required=True, metavar=("MANIFEST", "SHA256"))
    parser.add_argument("--child-prefix", required=True)


if __name__ == "__main__":
    status = run(resident.parse_arguments(extend=arguments))["status"]
    print(status, flush=True)
    raise SystemExit(0 if status == "MEASURED_REMAINING_CC_PAIRS" else 1)
