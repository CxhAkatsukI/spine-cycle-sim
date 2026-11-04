"""Measure AU/512 once on the same card and clocks as the repaired image's G gate."""

import argparse
import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import containment
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.active_min_candidate import (
    BOARDS, poll_until,
)
from ..board_execution.active_min_pair import paired_loader
from . import active_min_resident_follow as follow, clocks, figure8_au_pair as au, figure8_matrix as matrix
from .active_min_admission import checked, replay_g
from .runtime import identity, save


def qualified_g(stage, reference):
    receipt = stage["receipt"]
    measured = json.loads(checked(receipt).read_text())
    gate_host, = (pin for pin in measured["pins"] if pin["path"] == measured["row"]["command"][-5])
    image = clocks.replay(measured["row"]["clock_evidence"])["binary"]
    gate = replay_g(Path(receipt["path"]), reference, au.ALGORITHM, gate_host, image)
    if gate["report"] != receipt:
        raise ValueError("independent G receipt changed during replay")
    return gate, gate_host


def run(args):
    if not (1 <= args.g_wait_seconds <= 111600 and 1 <= args.board_wait_seconds <= 21600):
        raise ValueError("G gate wait and board wait must be bounded")
    matrix.exact_service(args.g_unit, args.g_invocation)
    manifest = identity(args.manifest)
    case = matrix.load_cases(manifest, args.manifest_sha256)[matrix.ANCHOR]
    hosts = {arm: identity(getattr(args, f"{arm}_host")) for arm in ("spine", "gr")}
    image = identity(args.spine_image)
    if any(pin["sha256"] != getattr(args, f"{key}_sha256") for key, pin in
           {**{f"{arm}_host": pin for arm, pin in hosts.items()}, "spine_image": image}.items()):
        raise ValueError("a setup host or the Spine image differs from its pinned SHA-256")
    graph = case["native_g_input"]
    checked(graph)
    memory = au.MEMORY
    group = au.memory_group()
    containment.verify(group, memory_gib=memory["tree_memory_gib"])
    reservation = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    args.output.mkdir(parents=True, exist_ok=False)
    stage = dict(unit=args.g_unit, invocation=args.g_invocation, observed=False, report_path=str(args.g_report))
    row = dict(dataset=matrix.ANCHOR[0], updates=matrix.ANCHOR[1], input=graph, attempts=[], arms={})
    report = dict(status="WAITING_FOR_G_GATE", stage=stage, row=row, hosts=hosts, spine_image=image,
                  boundary=au.BOUNDARY, requested_runs_per_arm=1, warmups=0,
                  runner=identity(__file__), manifest=manifest, memory=memory)

    def checkpoint():
        save(args.output / "results.json", report)

    try:
        checkpoint()
        deadline = time.monotonic() + args.g_wait_seconds
        while not follow.ready(stage, matrix.service_state(args.g_unit), follow.STAGE_PASS["g"], au.ALGORITHM):
            checkpoint()
            poll_until(deadline)
        gate, gate_host = qualified_g(stage, args.g_reference)
        gr_clock = gate["candidate_clock"]
        bdf = gr_clock["bdf"]
        spine = clocks.image(checked(image), args.output, "spine_expected")
        reference = dict(gr=gr_clock, spine={**spine, "bdf": bdf,
                                            "driver_reported_mhz": gr_clock["driver_reported_mhz"]})
        libraries = paired_loader(checked(hosts["spine"]), checked(hosts["gr"]))
        if libraries != paired_loader(checked(gate_host), checked(hosts["gr"])):
            raise ValueError("setup hosts use different XRT libraries from the G gate")
        report.update(status="MEASURING_SAME_CARD", baseline_g=gate, bdf=bdf, xrt_libraries=libraries)
        checkpoint()
        matrix.measure(case, row, args.output, time.monotonic() + args.board_wait_seconds,
                       reservation, memory, hosts, reference, libraries, checkpoint, board=(BOARDS[bdf], bdf))
        for pin in (manifest, *hosts.values(), image, gate["report"], gate["reference"], gate_host,
                    gr_clock["binary"]):
            checked(pin)
        report["status"] = "MEASURED_QUALIFIED_AU512_SETUP_ONLY"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        row["status"] = "FAILED_RETAINED"
        row.pop("speedup_gr_over_spine", None)
        raise
    finally:
        reservation.release()
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events_final"] = (group / "memory.events").read_text()
        checkpoint()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("manifest", "spine-host", "spine-image", "gr-host", "g-report", "g-reference", "output"):
        parser.add_argument("--" + key, required=True, type=lambda path: Path(path).resolve())
    for key in ("manifest", "spine-host", "spine-image", "gr-host"):
        parser.add_argument(f"--{key}-sha256", required=True)
    for key in ("g-unit", "g-invocation"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--g-wait-seconds", type=int, default=111600)
    parser.add_argument("--board-wait-seconds", type=int, default=21600)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
