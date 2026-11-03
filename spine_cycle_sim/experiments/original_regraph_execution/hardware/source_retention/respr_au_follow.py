"""Run one resident ResPR AU propagation pair on the already admitted image."""

import argparse
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, runner_pins, service_state,
)
from ..board_execution import pair_resources
from . import clocks, resident_board as board
from .follow import unchanged
from .resident_admission import Candidate, NotAdmitted, replay_gate
from .runtime import check_memory, identity, save


def prior_case(prior):
    if (prior["status"], prior["bdf"], prior["device"], prior["repetitions_per_arm"],
            prior["warmups"], prior["board_launch_attempted"]) != (
                "PAIRED_SCREEN_MEASURED", board.BDF, board.DEVICE, 1, 0, True):
        raise NotAdmitted("the pinned R19/Flickr screen did not complete successfully")
    if [row["case"]["dataset"] for row in prior["cases"]] != list(board.CASES):
        raise NotAdmitted("the parent must retain both original screen cases")
    for row in prior["cases"]:
        if (row["status"] != "MEASURED" or [attempt["arm"] for attempt in row["attempts"]] != ["spine", "gr"]
                or (row["case"]["dataset"] == "Flickr" and not row["pair"]["positive_propagation_on_both"])):
            raise NotAdmitted("the parent needs a single measured pair per case and positive Flickr propagation")
    route = prior["selected_route"]
    receipts = prior["candidates"][route]
    if receipts["host"] != prior["pins"]["gr_host"]:
        raise NotAdmitted("the selected route must use the parent screen host")
    return Candidate(Path(route), Path(receipts["r_report"]), Path(receipts["g_report"]), receipts["host"])


def run(args):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", args.unit)
            or not re.fullmatch(r"[0-9a-f]{32}", args.invocation) or not 1 <= args.wait_seconds <= 64800):
        raise ValueError("a pinned parent service and bounded wait are required")
    group = check_memory()
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(status="WAITING_FOR_RESPR_SCREEN", scope=board.AU_CASE, bdf=board.BDF, device=board.DEVICE,
                  affinity="124,125", repetitions_per_arm=1, warmups=0, board_launch_attempted=False,
                  full_evaluation_started=False, parent_unit=args.unit, parent_invocation=args.invocation)

    def write():
        save(args.output / "results.json", report)

    write()
    try:
        graph = identity(args.graph)
        case = board.frozen_case(board.AU_CASE, args.graph, graph)
        row = dict(case=case, status="PREDECLARED", rows={}, attempts=[])
        sources = runner_pins()
        report.update(cases=[row], runner_pins=sources)
        if route_finished(service_state(args.unit), args.invocation):
            raise ValueError("enqueue while the pinned parent screen is live")
        deadline = time.monotonic() + args.wait_seconds
        while True:
            check_memory()
            state = service_state(args.unit)
            report["parent_state"] = state
            write()
            collected = state["LoadState"] == "not-found" and not state["InvocationID"]
            if collected or route_finished(state, args.invocation):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("the pinned parent did not finish before the wait deadline")
            time.sleep(min(30, remaining))

        parent = identity(args.parent)
        prior = json.loads(args.parent.read_text())
        candidate = prior_case(prior)
        pins = {name: prior["pins"][name] for name in ("spine_host", "spine_image", "comparator", "frozen_r_board")}
        if (pins["spine_host"]["sha256"], pins["spine_image"]["sha256"], pins["comparator"]["sha256"]) != (
                board.SPINE_HOST_SHA256, board.SPINE_IMAGE_SHA256, board.resident_results.COMPARATOR_SHA256):
            raise NotAdmitted("the prior Spine host, image or comparator differs from the frozen pins")
        pins.update(gr_host=candidate.host_pin, parent=parent, **{board.AU_CASE.lower(): graph})
        image, gate = replay_gate(candidate, pins["frozen_r_board"])
        if prior["stage_gates"] != gate:
            raise NotAdmitted("the original independent G/R admission does not replay")
        pinned = [*sources, *pins.values(), *gate["pins"], identity(image)]
        unchanged(pinned)
        for name in ("spine_host", "spine_image", "comparator", "gr_host"):
            setattr(args, name, Path(pins[name]["path"]))
        report.update(pins=pins, stage_gates=gate, selected_route=str(candidate.route))
        expected = {arm: clocks.image(path, args.output, arm)
                    for arm, path in (("gr", image), ("spine", args.spine_image))}

        def record(status, memory):
            report.update(status=status, board_memory=memory)
            write()

        with pair_resources.admit(board.DEVICE, board.BDF, group, args.board_wait_seconds, record,
                                  legacy_lock=board.LEGACY_LOCK) as (node, fd):
            report.update(status="RUNNING_PAIRED_SCREEN", board_launch_attempted=True)
            write()
            board.measure(args, case, image, expected, gate, pinned, row, write, fd, node)
        unchanged(pinned)
        report["status"] = ("PAIRED_SCREEN_MEASURED" if row["status"] == "MEASURED"
                            else "PAIRED_SCREEN_NEEDS_REVIEW")
    except NotAdmitted as error:
        report.update(status="NOT_ADMITTED", error=str(error))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events_final"] = (group / "memory.events").read_text()
        write()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent", "graph", "output"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    for name in ("unit", "invocation"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--wait-seconds", type=int, default=64800)
    parser.add_argument("--board-wait-seconds", type=int, default=21600)
    status = run(parser.parse_args())["status"]
    print(status, flush=True)
    raise SystemExit(0 if status == "PAIRED_SCREEN_MEASURED" else 1)
