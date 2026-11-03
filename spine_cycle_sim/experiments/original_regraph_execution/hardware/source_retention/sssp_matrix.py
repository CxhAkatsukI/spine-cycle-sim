"""Queue seven single-pass resident SSSP FPGA pairs after the exact AU screen."""

import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, runner_pins, service_state,
)
from . import active_min_admission, active_min_resident as resident, resident_matrix
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


def run(args):
    if (args.algorithm, args.dataset, args.cc_wall_packet) != (ALGORITHM, "AU", None):
        raise ValueError("the matrix follows the AU weighted-SSSP screen only")
    prerequisites = {
        "au": {"unit": args.au_unit, "invocation": args.au_invocation},
        "odd_r": {"unit": args.odd_unit, "invocation": args.odd_invocation},
    }
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,75}", args.child_prefix)
            or not 1 <= args.au_wait_seconds <= 144000 or not 0 <= args.wait_seconds <= 21600
            or any(not (re.fullmatch(r"[0-9a-f]{32}", row["invocation"]) and
                        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", row["unit"]))
                   for row in prerequisites.values())):
        raise ValueError("exact AU and odd-frontier R invocations and bounded waits required")
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "matrix.json"
    rows = {ds: {"status": "NOT_REQUESTED"} for ds in resident.DATASETS if ds != "AU"}
    report = dict(status="WAITING_FOR_AU_AND_ODD_R", cases=rows, prerequisites=prerequisites,
                  repetitions_per_arm=1, warmups=0)
    save(journal, report)
    try:
        for row in prerequisites.values():
            if route_finished(service_state(row["unit"]), row["invocation"]):
                raise ValueError("enqueue while both pinned screens are active")
        pins = [*runner_pins(), identity(__file__), identity(resident_matrix.__file__)]
        report["runner_pins"] = pins
        for ds, row in rows.items():
            case, case_pins = resident.frozen_case(args.previous, ALGORITHM, ds)
            row.update(case=case, pins=case_pins)
        save(journal, report)
        deadline = time.monotonic() + args.au_wait_seconds
        while True:
            for row in prerequisites.values():
                if not row.get("ready"):
                    state = service_state(row["unit"])
                    collected = state["LoadState"] == "not-found" and not state["InvocationID"]
                    row.update(state=state, ready=collected or route_finished(state, row["invocation"]))
            save(journal, report)
            if all(row["ready"] for row in prerequisites.values()):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("AU and odd-frontier R did not both finish before deadline")
            time.sleep(min(30, remaining))
        unchanged(pins)
        gate = active_min_admission.admit(ALGORITHM, args.route, args.host, args.r_report,
                                          args.r_inputs, args.g_report, args.g_reference)
        au_pins = admitted_au(args, gate)
        odd, odd_pins = admitted_odd(args, gate)
        pins += au_pins + odd_pins
        pins += [gate["r"]["report"], gate["g"]["report"], gate["g"]["reference"], gate["host"], gate["image"]]
        report.update(status="RUNNING_SINGLE_PASS", baseline=gate, au_result=au_pins[1], odd_r=odd)
        for ds, row in rows.items():
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
    parser.add_argument("--au-unit", required=True)
    parser.add_argument("--au-invocation", required=True)
    parser.add_argument("--au-output", type=lambda value: Path(value).resolve(), required=True)
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
