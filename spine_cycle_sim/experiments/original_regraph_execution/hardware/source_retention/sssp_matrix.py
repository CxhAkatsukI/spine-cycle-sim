"""Queue seven single-pass resident SSSP FPGA pairs after the exact AU screen."""

import json
from pathlib import Path
import re
import subprocess
import sys
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, runner_pins, service_state,
)
from .. import artifact
from ..board_execution import active_min_follow
from . import active_min_admission, active_min_resident as resident
from .follow import unchanged
from .runtime import identity, save


ALGORITHM = "weighted_sssp"
MODULE = resident.__spec__.name
MEASURED = "MEASURED_RESIDENT_PAIR"
INPUTS = ("previous", "route", "host", "r_report", "r_inputs", "g_report", "g_reference", "comparator")


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


def admitted_odd(args, gate):
    journal = args.odd_output / "queue.json"
    result = args.odd_output / "pair/results.json"
    fixture = active_min_follow.fixture_pin(args, [])
    pins = [identity(journal), identity(result), fixture]
    queue = json.loads(journal.read_text())
    unchanged(pins)
    if (queue.get("status"), queue.get("result"), queue.get("retention_gate_pass")) != (
            "PAIRED_ACTIVE_MIN_R_GATE_PASS", artifact.identity(result), True) or fixture not in queue["pins"]:
        raise ValueError("odd-frontier R queue did not admit the frozen hardware result")
    odd = active_min_admission.replay_r(result, ALGORITHM, args.odd_inputs, gate["host"], gate["image"])
    if (odd["report"] != pins[1] or
            odd["candidate_clock"]["driver_reported_mhz"] != gate["resident_mhz"]):
        raise ValueError("odd-frontier R screen did not use the admitted image and clock")
    return odd, pins


def child_command(args, dataset, budget, output):
    return [
        "systemd-run", "--user", "--wait", "--collect",
        f"--unit={args.child_prefix}-{dataset.lower()}", f"--working-directory={Path.cwd()}",
        f"--property=MemoryMax={budget}G", f"--property=MemoryHigh={budget - 2}G",
        "--property=MemorySwapMax=0", "--property=OOMPolicy=kill", "--property=KillMode=control-group",
        "--property=RuntimeMaxSec=8h", sys.executable, "-m", MODULE, "--algorithm", ALGORITHM,
        "--dataset", dataset, "--output", str(output), "--wait-seconds", str(args.wait_seconds),
        *(part for key in INPUTS for part in ("--" + key.replace("_", "-"), str(getattr(args, key)))),
    ]


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
        pins = [*runner_pins(), identity(__file__)]
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
            with (args.output / f"{ds.lower()}.service.log").open("x") as log:
                job = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=8 * 3600 + 60)
            row["service_exit"] = job.returncode
            result = output / "results.json"
            if result.is_file():
                pin = identity(result)
                child = json.loads(result.read_text())
                unchanged([pin])
                row.update(result=pin, child_status=child.get("status"), attempts=child.get("attempts"))
                if child.get("status") == MEASURED and (
                        child.get("stage_gates") != gate or child.get("dataset") != ds
                        or child.get("boundary") != resident.BOUNDARY
                        or child.get("repetitions_per_arm") != 1 or child.get("warmups") != 0):
                    raise ValueError(f"{ds} result differs from the admitted single-pass protocol")
            row["status"] = MEASURED if (
                job.returncode == 0 and row.get("child_status") == MEASURED
                and row.get("attempts") == ["spine", "gr"]) else "FAILED_RETAINED"
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
