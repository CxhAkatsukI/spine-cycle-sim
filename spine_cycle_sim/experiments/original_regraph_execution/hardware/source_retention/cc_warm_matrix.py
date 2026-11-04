"""Continue the pinned warm CC AU screen without measuring AU again."""

import argparse
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    runner_pins, service_state,
)
from . import active_min_resident as resident, active_min_resident_follow as follow
from . import cc_resident_wall as wall, resident_matrix as matrix
from .follow import unchanged
from .runtime import identity, save


DATASETS = ("SU", "WK", "R19", "SO", "PK", "LJ", "LJ08")


def load(path):
    return json.loads(Path(path).read_text())


def retained_au(parent, gate, controls):
    unchanged([parent["receipt"]])
    queue = load(parent["report_path"])
    pin = queue["result"]
    unchanged([parent["receipt"], pin])
    child = load(pin["path"])
    jobs = queue["stages"]
    receipts = {"g": gate["g"]["report"], "r": gate["r"]["report"],
                "spine": child["retained_spine"], **{key: row["report"] for key, row in controls.items()}}
    if (queue["requested_pair"] is not True or queue["dataset"] != "AU"
            or set(jobs) != set(receipts)
            or any(not jobs[key]["ready"] or jobs[key]["receipt"] != pin for key, pin in receipts.items())
            or (child["status"], child["algorithm"], child["dataset"], child["boundary"],
                child["warmups"], child["repetitions_per_arm"], child["attempts"],
                child["stage_gates"], child["additional_r_gates"]) != (
                    matrix.MEASURED, "cc", "AU", wall.BOUNDARY, 0, 1, ["gr"], gate, controls)):
        raise ValueError("warm CC AU did not use the exact admitted one-shot protocol")
    unchanged([parent["receipt"], pin, *receipts.values()])
    return child, {"status": matrix.MEASURED, "result": pin, "attempts": ["gr"], "reused": True}, jobs


def wait_for_layout(path, deadline):
    while True:
        if path.is_file():
            report = load(path)
            if report["status"] == "LAYOUT_PASS_OFFLINE":
                return
            if report["status"] == "FAILED_RETAINED":
                raise ValueError(f"offline layout failed: {path}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"offline layout not ready: {path}")
        time.sleep(min(30, remaining))


def run(args):
    layouts = {ds: (Path(receipt).resolve(), Path(inputs).resolve()) for ds, receipt, inputs in args.layout}
    if ((args.algorithm, args.dataset) != ("cc", "AU") or set(layouts) != set(DATASETS)
            or len(args.layout) != len(DATASETS) or args.cc_wall_packet is None
            or args.cc_warm_au_receipt is not None or args.cc_warm_layout is not None
            or args.cc_warm_r_controls is None or not 1 <= args.stage_wait_seconds <= 111600
            or not 0 <= args.layout_wait_seconds <= 21600 or not 0 <= args.wait_seconds <= 21600
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,75}", args.child_prefix)):
        raise ValueError("provide the exact warm CC AU parent, all seven layouts and bounded waits")
    unit, invocation, receipt = args.au_parent
    if not (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit)
            and re.fullmatch(r"[0-9a-f]{32}", invocation)):
        raise ValueError("expected the exact warm CC AU parent service and invocation")
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "matrix.json"
    parent = dict(unit=unit, invocation=invocation, report_path=str(Path(receipt).absolute()), observed=False)
    rows = {ds: {"status": "NOT_REQUESTED"} for ds in ("AU", *DATASETS)}
    report = dict(status="WAITING_FOR_WARM_CC_AU", cases=rows, parent=parent, warmups=0, repetitions_per_arm=1)
    save(journal, report)
    try:
        state = service_state(unit)
        if state["LoadState"] != "loaded" or state["InvocationID"] != invocation:
            raise ValueError("cannot observe the pinned warm CC AU parent")
        pins = [*runner_pins(), *(identity(module.__file__) for module in (matrix, resident, follow, wall)),
                identity(__file__), identity(args.cc_wall_packet), identity(args.balanced_host)]
        report["runner_pins"] = pins
        deadline = time.monotonic() + args.stage_wait_seconds
        while not follow.ready(parent, state, matrix.MEASURED, "cc"):
            save(journal, report)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("warm CC AU did not complete before the stage deadline")
            time.sleep(min(30, remaining))
            state = service_state(unit)
        admission = resident.active_min_admission
        gate = admission.admit("cc", args.route, args.host, args.r_report, args.r_inputs,
                               args.g_report, args.g_reference)
        odd, odd_inputs, topology, topology_inputs = args.cc_warm_r_controls
        pins.extend(admission.pin_odd_queue(odd, odd_inputs))
        controls = {name: admission.replay_r(path, "cc", inputs, gate["host"], gate["image"], geometry=geometry)
                    for name, path, inputs, geometry in (("amazon_odd", odd, odd_inputs, admission.AMAZON_GEOMETRY),
                        ("au_slice", topology, topology_inputs, admission.AU_SLICE_GEOMETRY))}
        au, rows["AU"], jobs = retained_au(parent, gate, controls)
        pins += [parent["receipt"], rows["AU"]["result"], gate["image"], gate["host"], gate["g"]["reference"],
                 *(job["receipt"] for job in jobs.values())]
        template = load(args.cc_wall_packet)
        if any(template[name] != au["case"][name] for name in ("spine_binary", "gr_host", "spine_host")):
            raise ValueError("warm matrix must reuse the exact admitted AU Spine image and G+R wall host")
        template["spine_host"] = str(args.balanced_host)
        report.update(status="RUNNING_SINGLE_PASS", baseline=gate, stages=jobs,
                      odd_r=controls["amazon_odd"], au_slice_r=controls["au_slice"])
        save(journal, report)
        layout_deadline = time.monotonic() + args.layout_wait_seconds
        for ds in DATASETS:
            row = rows[ds]
            layout, inputs = layouts[ds]
            try:
                wait_for_layout(layout, layout_deadline)
                packet = args.output / f"{ds.lower()}.packet.json"
                save(packet, dict(template, inputs=str(inputs)))
                case, frozen = resident.frozen_case(args.previous, "cc", ds)
                configured, added = wall.configure(argparse.Namespace(
                    algorithm="cc", cc_wall_packet=packet, cc_warm_layout=layout), case, frozen)
            except (OSError, ValueError) as error:
                row.update(status="LAYOUT_NOT_ADMITTED", error=str(error))
                save(journal, report)
                continue
            unchanged([*pins, *frozen, *added])
            output = args.output / ds.lower()
            command = matrix.child_command(args, ds, configured["memory_gib"], output, packet=packet)
            command += ["--cc-warm-layout", str(layout), "--cc-warm-r-controls",
                        *map(str, args.cc_warm_r_controls)]
            row.update(status="REQUESTED", command=command, pins=[*frozen, *added])
            save(journal, report)
            row.update(matrix.run_child(command, args.output / f"{ds.lower()}.service.log", output,
                                        ds, gate, wall.BOUNDARY))
            save(journal, report)
        report["status"] = ("MEASURED_CC_SINGLE_PASS" if all(row["status"] == matrix.MEASURED for row in rows.values())
                            else "CC_MATRIX_WITH_FAILURES")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(journal, report)
    return report


def arguments(parser):
    parser.add_argument("--au-parent", nargs=3, required=True, metavar=("UNIT", "INVOCATION", "QUEUE"))
    parser.add_argument("--layout", nargs=3, required=True, action="append", metavar=("DATASET", "RECEIPT", "INPUTS"))
    parser.add_argument("--balanced-host", required=True, type=lambda value: Path(value).resolve())
    parser.add_argument("--stage-wait-seconds", type=int, default=111600)
    parser.add_argument("--layout-wait-seconds", type=int, default=21600)
    parser.add_argument("--child-prefix", required=True)


if __name__ == "__main__":
    status = run(resident.parse_arguments(extend=arguments))["status"]
    print(status, flush=True)
    raise SystemExit(0 if status == "MEASURED_CC_SINGLE_PASS" else 1)
