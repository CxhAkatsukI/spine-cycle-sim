"""Queue single-pass resident SSSP FPGA pairs after exact hardware gates."""

import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, runner_pins, service_state,
)
from .. import artifact
from ..board_execution import active_min, active_min_follow
from . import active_min_admission, active_min_resident as resident, resident_matrix, sssp_continuation
from . import active_min_resident_follow as follow
from .follow import unchanged
from .resident_matrix import INPUTS as GATE_INPUTS, MEASURED, admitted_odd, child_command, run_child
from .runtime import identity, save


ALGORITHM = "weighted_sssp"
INPUTS = (*GATE_INPUTS, "comparator")


def admitted_au(args, gate):
    journal = args.au_output / "queue.json"
    result = args.au_output / "pair/results.json"
    pins = [identity(journal), identity(result)]
    queue, pair = (json.loads(Path(pin["path"]).read_text()) for pin in pins)
    unchanged(pins)
    if (queue.get("status"), queue.get("result"), queue.get("requested_pair")) != (MEASURED, pins[1], True):
        raise ValueError("AU queue did not admit the pinned board result")
    if (pair.get("status"), pair.get("algorithm"), pair.get("dataset"), pair.get("boundary"),
            pair.get("attempts"), pair.get("repetitions_per_arm"), pair.get("warmups")) != (
                MEASURED, ALGORITHM, "AU", resident.BOUNDARY, ["spine", "gr"], 1, 0):
        raise ValueError("AU was not a measured single-pass resident SSSP pair")
    for key in ("host", "image", "g", "r", "resident_mhz"):
        if pair["stage_gates"][key] != gate[key]:
            raise ValueError(f"AU used a different baseline admission: {key}")
    return pins


def admitted_au_topology(args, au_pins, gate):
    queue, pair = (json.loads(Path(pin["path"]).read_text()) for pin in au_pins)
    unchanged(au_pins)
    stages, decisions = queue["stages"], pair["additional_r_gates"]
    if set(stages) != {"g", "r", *follow.ADDITIONAL_R} or set(decisions) != set(follow.ADDITIONAL_R):
        raise ValueError("AU resident screen must bind both additional R controls")
    odd_job = stages["amazon_odd"]
    if (odd_job["unit"], odd_job["invocation"], Path(odd_job["report_path"]), Path(odd_job["inputs"])) != (
            args.odd_unit, args.odd_invocation, args.odd_output / "pair/results.json", args.odd_inputs):
        raise ValueError("AU resident screen did not use the declared odd-frontier R producer")
    input_pins = [artifact.identity(args.odd_inputs / f"{name}.u32le")
                  for name in active_min.INPUTS + active_min.STATE[ALGORITHM]]
    fixture = active_min_follow.fixture_pin(args, input_pins)
    if any(not stages[key]["ready"] or stages[key]["receipt"] != decision["report"]
           for key, decision in (("g", gate["g"]), ("r", gate["r"]))):
        raise ValueError("AU resident screen used different G or Amazon R receipts")
    pins = [fixture, *input_pins]
    for label, geometry in follow.ADDITIONAL_R.items():
        job = stages[label]
        decision = active_min_admission.replay_r(
            Path(job["report_path"]), ALGORITHM, Path(job["inputs"]), gate["host"], gate["image"],
            geometry=geometry)
        if (not job["ready"] or decisions[label] != decision or decision["report"] != job["receipt"]
                or decision["candidate_clock"]["driver_reported_mhz"] != gate["resident_mhz"]):
            raise ValueError(f"{label} replay differs from the exact resident screen")
        pins.append(decision["report"])
    unchanged([*au_pins, *pins])
    return decisions["amazon_odd"], decisions["au_slice"], pins


def legacy_jobs(args):
    prerequisites = {
        "au": {"unit": args.au_unit, "invocation": args.au_invocation},
        "odd_r": {"unit": args.odd_unit, "invocation": args.odd_invocation},
    }
    if not args.au_output or any(not (re.fullmatch(r"[0-9a-f]{32}", row["invocation"]) and
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", row["unit"]))
            for row in prerequisites.values()):
        raise ValueError("exact AU and odd-frontier R invocations and bounded waits required")
    for row in prerequisites.values():
        if route_finished(service_state(row["unit"]), row["invocation"]):
            raise ValueError("enqueue while both pinned screens are active")
    return prerequisites


def run(args):
    if (args.algorithm, args.dataset, args.cc_wall_packet) != (ALGORITHM, "AU", None):
        raise ValueError("expected the AU weighted-SSSP matrix template")
    include_au = getattr(args, "include_au", False)
    source = getattr(args, "continue_from", None)
    require_topology = getattr(args, "require_au_topology", False)
    if source and not include_au:
        raise ValueError("continuation requires the complete SSSP matrix")
    if require_topology and include_au:
        raise ValueError("cross-topology admission requires the separate AU resident screen")
    if include_au and (args.au_unit or args.au_invocation or args.au_output):
        raise ValueError("choose the complete matrix or a separate AU screen")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,75}", args.child_prefix)
            or not 1 <= args.au_wait_seconds <= 144000 or not 0 <= args.wait_seconds <= 21600):
        raise ValueError("expected a valid service prefix and bounded waits")
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "matrix.json"
    rows = {ds: {"status": "NOT_REQUESTED"} for ds in resident.DATASETS if include_au or ds != "AU"}
    waiting = "WAITING_FOR_G_AND_BOTH_R_GATES" if include_au else "WAITING_FOR_AU_AND_ODD_R"
    if require_topology:
        waiting = "WAITING_FOR_CROSS_TOPOLOGY_AU_AND_ODD_R"
    report = dict(status=waiting, cases=rows, require_au_topology=require_topology,
                  repetitions_per_arm=1, warmups=0)
    save(journal, report)
    try:
        pins = [*runner_pins(), identity(__file__), identity(resident_matrix.__file__)]
        if include_au:
            pins.append(identity(follow.__file__))
        report["runner_pins"] = pins
        for ds, row in rows.items():
            case, case_pins = resident.frozen_case(args.previous, ALGORITHM, ds)
            row.update(case=case, pins=case_pins)
        if source:
            previous, pending, old_pins, stopped = sssp_continuation.load(source, rows)
            pins += old_pins
            prerequisites = previous["prerequisites"]
            report["continuation"] = dict(journal=old_pins[0], stopped_services=stopped,
                                          pending_order=pending)
        else:
            previous, pending = None, list(rows)
            if require_topology:
                pending.sort(key=lambda ds: rows[ds]["case"]["memory_gib"])
            prerequisites = resident_matrix.stage_jobs(args) if include_au else legacy_jobs(args)
        report["prerequisites"] = prerequisites
        save(journal, report)
        deadline = time.monotonic() + args.au_wait_seconds
        while True:
            for key, row in prerequisites.items():
                if not row.get("ready"):
                    state = service_state(row["unit"])
                    if include_au:
                        row["ready"] = follow.ready(row, state, follow.STAGE_PASS["r" if key == "odd" else key],
                                                   ALGORITHM)
                    else:
                        collected = state["LoadState"] == "not-found" and not state["InvocationID"]
                        row.update(state=state, ready=collected or route_finished(state, row["invocation"]))
            save(journal, report)
            if all(row["ready"] for row in prerequisites.values()):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("SSSP matrix prerequisites did not finish before deadline")
            time.sleep(min(30, remaining))
        unchanged(pins)
        gate = active_min_admission.admit(ALGORITHM, args.route, args.host, args.r_report,
                                          args.r_inputs, args.g_report, args.g_reference)
        if not require_topology:
            odd, odd_pins = admitted_odd(args, gate)
        if include_au:
            resident_matrix.check_stage_receipts(prerequisites, gate, odd)
        else:
            au_pins = admitted_au(args, gate)
            pins += au_pins
            report["au_result"] = au_pins[1]
            if require_topology:
                odd, topology, odd_pins = admitted_au_topology(args, au_pins, gate)
                report["au_slice_r"] = topology
        pins += odd_pins
        pins += [gate["r"]["report"], gate["g"]["report"], gate["g"]["reference"], gate["host"], gate["image"]]
        if previous is not None:
            if (previous["baseline"], previous["odd_r"]) != (gate, odd):
                raise ValueError("continuation must use the same exact baseline stage admissions")
            sssp_continuation.claim(source, args.output)
        report.update(status="RUNNING_SINGLE_PASS", baseline=gate, odd_r=odd)
        for ds in pending:
            row = rows[ds]
            unchanged([*pins, *row["pins"]])
            output = args.output / ds.lower()
            command = child_command(args, ds, row["case"]["memory_gib"], output)
            row.update(status="REQUESTED", command=command)
            save(journal, report)
            row.update(run_child(command, args.output / f"{ds.lower()}.service.log", output, ds, gate,
                                 resident.BOUNDARY))
            save(journal, report)
        report["status"] = ("MEASURED_SSSP_MATRIX" if all(row["status"] == MEASURED for row in rows.values())
                            else "SSSP_MATRIX_WITH_FAILURES")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(journal, report)
    return report


def arguments(parser):
    parser.add_argument("--include-au", action="store_true", help="run all eight once after exact G and both R gates")
    parser.add_argument("--continue-from", nargs=3, metavar=("JOURNAL", "SHA256", "STOPPED_SERVICE"),
                        help="keep prior attempts and queue unattempted cases from smallest memory budget")
    parser.add_argument("--require-au-topology", action="store_true",
                        help="replay the separate AU screen's exact cross-topology admission")
    for stage in ("au", "g", "r"):
        parser.add_argument(f"--{stage}-unit", default="")
        parser.add_argument(f"--{stage}-invocation", default="")
    parser.add_argument("--au-output", type=lambda value: Path(value).resolve())
    parser.add_argument("--au-wait-seconds", type=int, default=140400)
    parser.add_argument("--odd-unit", required=True)
    parser.add_argument("--odd-invocation", required=True)
    for name in ("odd-output", "odd-inputs"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument("--odd-fixture", nargs=2, required=True, metavar=("MANIFEST", "SHA256"))
    parser.add_argument("--child-prefix", required=True)


if __name__ == "__main__":
    status = run(resident.parse_arguments(extend=arguments))["status"]
    print(status, flush=True)
    raise SystemExit(0 if status == "MEASURED_SSSP_MATRIX" else 1)
