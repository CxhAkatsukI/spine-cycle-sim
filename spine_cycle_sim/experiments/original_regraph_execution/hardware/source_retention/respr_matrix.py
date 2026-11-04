"""Queue the remaining frozen ResPR large-graph pairs behind hardware admission."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, runner_pins, service_state,
)
from ..board_execution import pair_resources
from . import active_min_resident, clocks, resident_board as board, resident_matrix
from .follow import unchanged
from .resident_admission import NotAdmitted, replay_gate
from .respr_au_follow import prior_case
from .respr_resident_replay import replay_case
from .runtime import check_memory, identity, save


DATASETS = tuple(dataset for dataset in active_min_resident.DATASETS if dataset != "R19")
BOUNDARY = active_min_resident.BOUNDARY
MODULE = "spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.respr_matrix"
SPINE_PINS = {"spine_host": board.SPINE_HOST_SHA256, "spine_image": board.SPINE_IMAGE_SHA256,
              "comparator": board.resident_results.COMPARATOR_SHA256}


def declaration(previous, dataset):
    case, evidence = active_min_resident.frozen_case(previous, "respr", dataset)
    by_path = {pin["path"]: pin for pin in evidence}
    for frozen, canonical in (("spine_host", "spine_host"), ("spine_binary", "spine_image")):
        if by_path[case[frozen]]["sha256"] != SPINE_PINS[canonical]:
            raise ValueError(f"{dataset} does not use the frozen Spine {canonical}")
    return {"case": {key: case[key] for key in ("dataset", "graph", "source", "vertices", "edges", "updates")}
                    | {"algorithm": "residual_pagerank", "requires_propagation": False},
            "memory_gib": case["memory_gib"], "inputs": evidence, "status": "PREDECLARED"}


def admit_parent(path, expected_sha=None):
    parent = identity(path)
    if expected_sha is not None and parent["sha256"] != expected_sha:
        raise NotAdmitted("parent changed after the matrix was admitted")
    report = json.loads(path.read_text())
    candidate = prior_case(report)
    pins = {name: report["pins"][name] for name in (*SPINE_PINS, "frozen_r_board")}
    if any(pins[name]["sha256"] != sha for name, sha in SPINE_PINS.items()):
        raise NotAdmitted("parent Spine image, host or comparator changed")
    image, gate = replay_gate(candidate, pins["frozen_r_board"])
    if gate != report["stage_gates"]:
        raise NotAdmitted("independent G and R gates do not replay")
    pins.update(gr_host=candidate.host_pin, parent=parent)
    unchanged([*pins.values(), *gate["pins"]])
    return pins, identity(image), gate


def child(args):
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREDECLARED", "dataset": args.dataset, "boundary": BOUNDARY,
              "bdf": board.BDF, "device": board.DEVICE, "warmups": 0, "repetitions_per_arm": 1,
              "attempts": [], "board_launch_attempted": False}
    result = args.output / "results.json"
    group = None

    def write():
        if "row" in report:
            report["attempts"] = [attempt["arm"] for attempt in report["row"]["attempts"]]
        save(result, report)

    write()
    try:
        declared = declaration(args.previous, args.dataset)
        case, budget = declared["case"], declared["memory_gib"]
        group = check_memory(budget, require_live_reserve=False)
        pins, image, gate = admit_parent(args.parent, args.parent_sha256)
        graph = next(pin for pin in declared["inputs"] if pin["path"] == case["graph"])
        pins[args.dataset.lower()] = graph
        for name in (*SPINE_PINS, "gr_host"):
            setattr(args, name, Path(pins[name]["path"]))
        source_pins = [*runner_pins(), identity(__file__)]
        evidence = [*pins.values(), *gate["pins"], image, *declared["inputs"], *source_pins]
        row = dict(case=case, status="PREDECLARED", rows={}, attempts=[])
        report.update(case=case, pins=pins, stage_gates=gate, image=image, inputs=evidence, row=row)
        expected = {arm: clocks.image(path, args.output, arm) for arm, path in (
            ("gr", image["path"]), ("spine", args.spine_image))}

        def record(status, memory):
            report.update(status=status, board_memory=memory)
            write()

        with pair_resources.admit(board.DEVICE, board.BDF, group, args.board_wait_seconds, record,
                                  legacy_lock=board.LEGACY_LOCK, memory_gib=budget) as (node, fd):
            report.update(status="RUNNING", board_launch_attempted=True)
            write()
            board.measure(args, case, Path(image["path"]), expected, gate, evidence, row, write, fd, node,
                          memory_gib=budget, timeout=1800)
        unchanged(evidence)
        report["replay"] = replay_case(row, report, {"image": image}, case=case)
        report["status"] = resident_matrix.MEASURED
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        if group is not None:
            report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
            report["memory_events"] = (group / "memory.events").read_text()
        write()
    return report


def wait_parent(args, report, write):
    if route_finished(service_state(args.unit), args.invocation):
        raise ValueError("enqueue the matrix while the pinned parent is live")
    deadline = time.monotonic() + args.wait_seconds
    while True:
        state = service_state(args.unit)
        report["parent_state"] = state
        write()
        collected = state["LoadState"] == "not-found" and not state["InvocationID"]
        if collected or route_finished(state, args.invocation):
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("parent screen did not finish before the matrix wait deadline")
        time.sleep(min(30, remaining))


def queue(args):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", args.unit)
            or not re.fullmatch(r"[0-9a-f]{32}", args.invocation)
            or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", args.child_prefix)
            or not 1 <= args.wait_seconds <= 64800):
        raise ValueError("pinned parent, unique child prefix and bounded wait required")
    group = check_memory(1, require_live_reserve=False)
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "boundary": BOUNDARY, "cases": [], "warmups": 0,
              "repetitions_per_arm": 1, "parent_unit": args.unit, "parent_invocation": args.invocation,
              "board_children_started": 0}

    def write():
        save(args.output / "results.json", report)

    write()
    try:
        sources = [*runner_pins(), identity(__file__)]
        report["runner_pins"] = sources
        for dataset in DATASETS:
            report["cases"].append(declaration(args.previous, dataset))
            write()
        report["status"] = "WAITING_FOR_RESPR_SCREEN"
        write()
        wait_parent(args, report, write)
        pins, image, gate = admit_parent(args.parent)
        report.update(status="RUNNING_MATRIX", parent=pins["parent"], image=image, stage_gates=gate)
        for row in report["cases"]:
            unchanged([*sources, *row["inputs"], pins["parent"], image])
            dataset = row["case"]["dataset"]
            output = args.output / dataset
            argv = resident_matrix.child_service(args.child_prefix, dataset, row["memory_gib"], MODULE) + [
                "--dataset", dataset, "--previous", str(args.previous), "--parent", str(args.parent),
                "--parent-sha256", pins["parent"]["sha256"], "--output", str(output),
                "--board-wait-seconds", str(args.board_wait_seconds),
            ]
            report["board_children_started"] += 1
            row.update(status="STARTED", command=argv)
            write()
            log = args.output / f"{dataset}.service.txt"
            try:
                row.update(resident_matrix.run_child(argv, log, output, dataset, gate, BOUNDARY))
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                row.update(status="FAILED_RETAINED", error=repr(error))
                if (output / "results.json").is_file():
                    row["result"] = identity(output / "results.json")
            if log.is_file():
                row["service_log"] = identity(log)
            write()
        report["status"] = ("MATRIX_MEASURED" if all(row["status"] == resident_matrix.MEASURED
                                                    for row in report["cases"]) else "MATRIX_NEEDS_REVIEW")
    except NotAdmitted as error:
        report.update(status="NOT_ADMITTED", error=str(error))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events"] = (group / "memory.events").read_text()
        write()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("previous", "parent", "output"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    for name in ("unit", "invocation", "child-prefix", "parent-sha256"):
        parser.add_argument("--" + name)
    parser.add_argument("--dataset", choices=DATASETS)
    parser.add_argument("--wait-seconds", type=int, default=64800)
    parser.add_argument("--board-wait-seconds", type=int, default=21600)
    args = parser.parse_args()
    if not 1 <= args.board_wait_seconds <= 21600:
        parser.error("board wait must be within six hours")
    if args.dataset and not re.fullmatch(r"[0-9a-f]{64}", args.parent_sha256 or ""):
        parser.error("the child requires a pinned parent digest")
    if not args.dataset and not all((args.unit, args.invocation, args.child_prefix)):
        parser.error("the queue requires a parent service, invocation and unique child prefix")
    status = (child(args) if args.dataset else queue(args))["status"]
    print(status, flush=True)
    return 0 if status in ("MATRIX_MEASURED", resident_matrix.MEASURED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
