"""Wait for exact G and R jobs, then request one admitted resident FPGA pair."""

import argparse
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, runner_pins, service_state,
)
from . import active_min_resident as resident
from .follow import unchanged
from .runtime import identity, save


STAGE_PASS = {"r": "PAIRED_ACTIVE_MIN_R_GATE_PASS", "g": "G_GATE_PASS_FOR_ACTIVE_MIN_IMAGE"}
PENDING = {"g": {"PREPARING", "WAITING_FOR_ROUTE", "WAITING_FOR_MEMORY", "WAITING_FOR_BOARD", "RUNNING_CANDIDATE"},
           "r": set()}
ADDITIONAL_R = {"amazon_odd": resident.active_min_admission.AMAZON_GEOMETRY,
                "au_slice": resident.active_min_admission.AU_SLICE_GEOMETRY}
WARM_PASS = "RESIDENT_CC_STATE_WORK_AND_CLOCK_PASS_NOT_PERFORMANCE_ADMISSION"
WARM_PENDING = {"PREPARING", "MEMORY_ADMITTED", "WAITING_FOR_MEMORY_ADMISSION"}


def ready(row, state, expected, algorithm):
    row["state"] = state
    observed = state["LoadState"] == "loaded" and state["InvocationID"] == row["invocation"]
    row["observed"] |= observed
    if state["LoadState"] == "loaded":
        try:
            if not route_finished(state, row["invocation"]):
                return False
        except ValueError as error:
            if observed:
                path = Path(row["report_path"])
                if path.is_file():
                    row["failed_receipt"] = identity(path)
                    row["receipt_status"] = json.loads(path.read_text()).get("status")
            raise ValueError(f"{row['unit']} did not complete successfully") from error
    elif not (row["observed"] and state["LoadState"] == "not-found" and not state["InvocationID"]):
        raise ValueError(f"{row['unit']} lost its pinned invocation")
    # Transient services may be collected on exit; require the pinned job's terminal evidence.
    path = Path(row["report_path"])
    if not path.is_file():
        raise ValueError(f"{row['unit']} finished without a stage receipt")
    pin = identity(path)
    receipt = json.loads(path.read_text())
    unchanged([pin])
    row.update(receipt=pin, receipt_status=receipt.get("status"))
    if (receipt.get("status"), receipt.get("algorithm")) != (expected, algorithm):
        raise ValueError(f"{row['unit']} did not pass: {row['receipt_status']}")
    return True


def run(args):
    if not 1 <= args.stage_wait_seconds <= 111600:
        raise ValueError("stage wait must be bounded to 31 hours")
    stages = {}
    extra = {label: getattr(args, label + "_r", None) for label in ADDITIONAL_R}
    warm = getattr(args, "cc_warm_unit", None)
    if (getattr(args, "cc_warm_r_controls", None) is not None or
            bool(warm) != bool(getattr(args, "cc_warm_invocation", None)) or
            bool(warm) != bool(getattr(args, "cc_warm_au_receipt", None)) or
            (warm and ((args.algorithm, args.dataset) != ("cc", "AU") or args.cc_wall_packet is None))):
        raise ValueError("warm CC AU requires its exact producer, receipt and wall packet")
    if (any(extra.values()) or warm) and (not all(extra.values()) or (args.algorithm != "weighted_sssp" and not warm)):
        raise ValueError("the cross-topology gate needs both alternate R controls")
    for stage in STAGE_PASS:
        unit, invocation = (getattr(args, f"{stage}_{key}") for key in ("unit", "invocation"))
        stages[stage] = dict(unit=unit, invocation=invocation,
                             report_path=str(getattr(args, f"{stage}_report")), observed=False)
    for label, values in extra.items():
        if values:
            unit, invocation, receipt, inputs = values
            stages[label] = dict(unit=unit, invocation=invocation, report_path=str(Path(receipt).absolute()),
                                 inputs=str(Path(inputs).resolve(strict=True)), observed=False)
    if warm:
        stages["spine"] = dict(unit=warm, invocation=args.cc_warm_invocation,
                               report_path=str(args.cc_warm_au_receipt), observed=False)
    if len({row["unit"] for row in stages.values()}) != len(stages):
        raise ValueError("each stage needs a distinct producer")
    for row in stages.values():
        unit, invocation = row["unit"], row["invocation"]
        if not (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit)
                and re.fullmatch(r"[0-9a-f]{32}", invocation)):
            raise ValueError("each stage needs an exact service and invocation ID")
    args.output.mkdir(parents=True, exist_ok=False)
    journal = args.output / "queue.json"
    report = dict(status="WAITING_FOR_STAGE_GATES", stages=stages, requested_pair=False,
                  dataset=args.dataset, algorithm=args.algorithm)
    save(journal, report)
    try:
        for stage, row in stages.items():
            state = service_state(row["unit"])
            path = Path(row["report_path"])
            if state["LoadState"] != "loaded" or state["InvocationID"] != row["invocation"]:
                raise ValueError(f"must enqueue while the pinned {stage} producer is active")
            if route_finished(state, row["invocation"]):
                if stage != "spine":
                    raise ValueError(f"must enqueue while the pinned {stage} producer is active")
                # Reuse the completed single-arm run; the resident runner replays its raw evidence.
                row["ready"] = ready(row, state, WARM_PASS, None)
                continue
            pending = WARM_PENDING if stage == "spine" else PENDING.get(stage, set())
            if path.is_file() and json.loads(path.read_text()).get("status") not in pending:
                raise ValueError(f"expected no terminal {stage} receipt at enqueue: {path}")
            row.update(state=state, observed=True)
        pins = [*runner_pins(), identity(__file__)]
        if getattr(args, "cc_wall_packet", None) is not None:
            case, case_pins = resident.frozen_case(args.previous, args.algorithm, args.dataset)
            if warm:
                packet = json.loads(args.cc_wall_packet.read_text())
                wall_pins = [identity(path) for path in
                             (args.cc_wall_packet, packet["spine_host"], packet["gr_host"], packet["inputs"])]
            else:
                _, wall_pins = resident.cc_resident_wall.configure(args, case, case_pins)
            pins += [identity(resident.__file__), *case_pins, *wall_pins]
        report["runner_pins"] = pins
        deadline = time.monotonic() + args.stage_wait_seconds
        while True:
            for stage, row in stages.items():
                if not row.get("ready"):
                    expected = WARM_PASS if stage == "spine" else STAGE_PASS.get(stage, STAGE_PASS["r"])
                    row["ready"] = ready(row, service_state(row["unit"]), expected,
                                         None if stage == "spine" else args.algorithm)
            save(journal, report)
            if all(row["ready"] for row in stages.values()):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("G and R did not pass before the stage deadline")
            time.sleep(min(30, remaining))
        unchanged([*pins, *(row["receipt"] for row in stages.values())])
        report.update(status="REQUESTING_ONE_RESIDENT_PAIR", requested_pair=True)
        save(journal, report)
        controls = [(key, stages[key]["receipt"], Path(stages[key]["inputs"]), geometry)
                    for key, geometry in ADDITIONAL_R.items() if key in stages]
        warm_controls = [path for _, receipt, inputs, _ in controls for path in (Path(receipt["path"]), inputs)]
        measured = resident.run(argparse.Namespace(**dict(
            vars(args), output=args.output / "pair", stage_receipts={k: row["receipt"] for k, row in stages.items()},
            additional_r=() if warm else controls, cc_warm_r_controls=warm_controls if warm else None)))
        report.update(status=measured["status"], result=identity(args.output / "pair/results.json"))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(journal, report)
    return report


def arguments(parser):
    for stage in STAGE_PASS:
        parser.add_argument(f"--{stage}-unit", required=True)
        parser.add_argument(f"--{stage}-invocation", required=True)
    parser.add_argument("--stage-wait-seconds", type=int, default=108000)
    parser.add_argument("--cc-warm-unit")
    parser.add_argument("--cc-warm-invocation")
    for label in ADDITIONAL_R:
        parser.add_argument("--" + label.replace("_", "-") + "-r", nargs=4,
                            metavar=("UNIT", "INVOCATION", "PAIR_RESULTS", "INPUTS"))


if __name__ == "__main__":
    print(run(resident.parse_arguments(extend=arguments))["status"], flush=True)
