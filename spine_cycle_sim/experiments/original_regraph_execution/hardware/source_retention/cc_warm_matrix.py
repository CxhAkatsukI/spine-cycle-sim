"""Continue the pinned warm CC AU screen without measuring AU again."""

import argparse
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, runner_pins, service_state,
)
from . import active_min_resident as resident, active_min_resident_follow as follow
from . import cc_au_revision as revision, cc_resident_wall as wall, cc_spine_route, resident_matrix as matrix
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


def replacement_au(comparison, candidate, gate, controls):
    prepared, replayed = revision.replay_comparison(comparison, candidate)
    _, files = cc_spine_route.matrix_route(candidate)
    anchor = load(prepared["arm"]["path"])
    if anchor["stage_gates"] != gate or anchor["additional_r_gates"] != controls:
        raise ValueError("AU replacement and matrix do not use the exact same baseline stage receipts")
    template = dict(spine_binary=files["image"]["path"], spine_host=files["host"]["path"],
                    gr_host=anchor["case"]["gr_host"])
    row = dict(status=matrix.MEASURED, result=comparison, kind="replacement_au", reused=True,
               comparison=replayed["new_pair"])
    pins = [comparison, candidate, prepared["arm"], replayed["candidate_smoke"], *files.values()]
    unchanged(pins)
    return row, template, pins


def replacement_ready(parent, state):
    parent["state"] = state
    if state["LoadState"] == "loaded":
        if not route_finished(state, parent["invocation"]):
            return False
    elif not (parent["observed"] and state["LoadState"] == "not-found" and not state["InvocationID"]):
        raise ValueError("lost the pinned AU replacement collector")
    parent["receipt"] = identity(parent["report_path"])
    receipt = load(parent["receipt"]["path"])
    if receipt.get("status") != revision.MATCHED:
        raise ValueError(f"AU replacement collector did not pass: {receipt.get('status')}")
    parent.update(comparison=receipt["comparison"], route=receipt["candidate"])
    unchanged([parent["receipt"], parent["comparison"], parent["route"]])
    return True


def run(args):
    with resident.memory_policy.scope(getattr(args, "memory_profile", resident.memory_policy.DEFAULT)):
        return _run(args)


def _run(args):
    layouts = {ds: (Path(receipt).resolve(), Path(inputs).resolve()) for ds, receipt, inputs in args.layout}
    replacement = getattr(args, "au_replacement", None)
    if ((args.algorithm, args.dataset) != ("cc", "AU") or set(layouts) != set(DATASETS)
            or len(args.layout) != len(DATASETS) or args.cc_wall_packet is None
            or args.cc_warm_au_receipt is not None or args.cc_warm_layout is not None
            or getattr(args, "cc_warm_candidate", None) is not None
            or ((args.balanced_host is None) != (replacement is not None))
            or args.cc_warm_r_controls is None or not 1 <= args.stage_wait_seconds <= 111600
            or not 0 <= args.layout_wait_seconds <= 21600 or not 0 <= args.wait_seconds <= 21600
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,75}", args.child_prefix)):
        raise ValueError("provide the exact warm CC AU parent, all seven layouts and bounded waits")
    unit, invocation, receipt = args.au_parent if replacement is None else replacement
    if not (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit)
            and re.fullmatch(r"[0-9a-f]{32}", invocation)):
        raise ValueError("expected the exact warm CC AU parent service and invocation")
    parent = dict(unit=unit, invocation=invocation, report_path=str(Path(receipt).absolute()), observed=False)
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "matrix.json"
    rows = {ds: {"status": "NOT_REQUESTED"} for ds in ("AU", *DATASETS)}
    report = dict(status="WAITING_FOR_WARM_CC_AU", cases=rows, parent=parent, warmups=0, repetitions_per_arm=1,
                  memory_profile=resident.memory_policy.selected())
    save(journal, report)
    try:
        pins = [*runner_pins(), *(identity(module.__file__) for module in (matrix, resident, follow, wall)),
                identity(__file__), identity(args.cc_wall_packet)]
        report["runner_pins"] = pins
        if replacement is None:
            pins.append(identity(args.balanced_host))
        state = service_state(unit)
        if state["LoadState"] != "loaded" or state["InvocationID"] != invocation:
            raise ValueError("cannot observe the pinned warm CC AU parent")
        parent["observed"] = True
        ready = replacement_ready if replacement is not None else (
            lambda parent, state: follow.ready(parent, state, matrix.MEASURED, "cc"))
        deadline = time.monotonic() + args.stage_wait_seconds
        while not ready(parent, state):
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
        template = load(args.cc_wall_packet)
        candidate = parent.get("route")
        if replacement is None:
            au, rows["AU"], jobs = retained_au(parent, gate, controls)
            pins.append(rows["AU"]["result"])
            if any(template[name] != au["case"][name] for name in ("spine_binary", "gr_host", "spine_host")):
                raise ValueError("warm matrix must reuse the exact admitted AU Spine image and G+R wall host")
            template["spine_host"] = str(args.balanced_host)
        else:
            rows["AU"], admitted, replacement_pins = replacement_au(parent["comparison"], candidate, gate, controls)
            if template.get("gr_host") != admitted["gr_host"]:
                raise ValueError("warm matrix template differs from the exact replacement AU G+R host")
            template = admitted
            pins.extend([identity(revision.__file__), identity(cc_spine_route.__file__), *replacement_pins])
            jobs = {key: {"receipt": row["report"], "ready": True} for key, row in
                    {"g": gate["g"], "r": gate["r"], **controls}.items()}
        pins += [parent["receipt"], gate["image"], gate["host"], gate["g"]["reference"],
                 *(job["receipt"] for job in jobs.values())]
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
                    algorithm="cc", cc_wall_packet=packet, cc_warm_layout=layout, cc_warm_candidate=candidate),
                    case, frozen)
            except (OSError, ValueError) as error:
                row.update(status="LAYOUT_NOT_ADMITTED", error=str(error))
                save(journal, report)
                continue
            unchanged([*pins, *frozen, *added])
            output = args.output / ds.lower()
            command = matrix.child_command(args, ds, configured["memory_gib"], output, packet=packet)
            command += ["--cc-warm-layout", str(layout), "--cc-warm-r-controls",
                        *map(str, args.cc_warm_r_controls)]
            if candidate is not None:
                command += ["--cc-warm-candidate", candidate["path"], candidate["sha256"]]
            row.update(status="REQUESTED", command=command, pins=[*frozen, *added])
            save(journal, report)
            row.update(matrix.run_child(command, args.output / f"{ds.lower()}.service.log", output,
                                        ds, gate, wall.BOUNDARY, controls=controls))
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
    au = parser.add_mutually_exclusive_group(required=True)
    au.add_argument("--au-parent", nargs=3, metavar=("UNIT", "INVOCATION", "QUEUE"))
    au.add_argument("--au-replacement", nargs=3, metavar=("UNIT", "INVOCATION", "COLLECTOR_JSON"))
    parser.add_argument("--layout", nargs=3, required=True, action="append", metavar=("DATASET", "RECEIPT", "INPUTS"))
    parser.add_argument("--balanced-host", type=lambda value: Path(value).resolve())
    parser.add_argument("--stage-wait-seconds", type=int, default=111600)
    parser.add_argument("--layout-wait-seconds", type=int, default=21600)
    parser.add_argument("--child-prefix", required=True)


if __name__ == "__main__":
    status = run(resident.parse_arguments(extend=arguments))["status"]
    print(status, flush=True)
    raise SystemExit(0 if status == "MEASURED_CC_SINGLE_PASS" else 1)
