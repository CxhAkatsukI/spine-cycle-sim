"""Complete the native AU/512 update-only pair after the independent G gate."""

import argparse
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import service_state
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.board_memory import require_unthrottled
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import containment
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.active_min_candidate import (
    BDF, DEVICE, MEMORY, poll_until,
)
from ..board_execution.active_min_pair import paired_loader
from . import active_min_resident_follow as follow, clocks
from .active_min_admission import checked, replay_g
from .runtime import check_memory, execute, identity, lease, save


ALGORITHM = "weighted_sssp"
AU_SHA = "092a84ab17b564cab854875e544f420635fe63cca5056e10c3842be912501e70"
COMMON = dict(status="PASS", vertices="515281", initial_edges="390847", logical_updates="512", repeats="1")
BOUNDARY = ("native layout/packing, initial and batch upload, update through completion; "
            "excludes input parsing, programming and validation readback")


def record(text, prefix):
    lines = [line.split()[1:] for line in text.splitlines() if line.startswith(prefix + " ")]
    tokens, = lines
    row = dict(item.split("=", 1) for item in tokens)
    if len(row) != len(tokens):
        raise ValueError(f"duplicate fields in {prefix}")
    return row


def timer(text, arm, case=None):
    common = COMMON if case is None else dict(
        status="PASS", vertices=str(case["vertices"]), initial_edges=str(case["initial_edges"]),
        logical_updates=str(case["updates"]), repeats="1",
    )
    if arm == "spine":
        edges = int(common["initial_edges"]) + int(common["logical_updates"])
        prefix, extra = "SPINE_UPDATE_SETUP_ONCE", dict(checked_edges=str(edges))
        fields = ("layout_ns", "bootstrap_ns", "batch_ns", "update_wall_ns")
    elif arm == "gr":
        prefix, extra = "GRASU_SHARDED_UPDATE_SETUP_ONCE", dict(trace_aware_pma="1", pma_mismatches="0")
        fields = ("layout_ns", "upload_ns", "update_wall_ns")
    else:
        raise ValueError(f"unknown timer arm: {arm}")
    row = record(text, prefix)
    expected = {**common, **extra}
    if any(row.get(k) != v for k, v in expected.items()):
        raise ValueError(f"{arm} did not validate the exact one-shot batch")
    times = {key: int(row[key]) for key in (*fields, "setup_inclusive_ns")}
    if any(value <= 0 for value in times.values()) or times["setup_inclusive_ns"] != sum(times[key] for key in fields):
        raise ValueError(f"inconsistent {arm} setup timer")
    return times


def gr_command(host, image, graph, oracle, *, replicas=4):
    if replicas not in (1, 4):
        raise ValueError("expected one or four metadata copies")
    return ["/usr/bin/env", "-u", "XCL_EMULATION_MODE", "-u", "GRASU_RESIDENT_BATCH_WALL",
            f"XCL_DEVICE_INDEX={DEVICE}", f"GRASU_REGRAPH_EXPECT_BDF={BDF}", "GRASU_UPDATE_REPEATS=1",
            "GRASU_SHARDED_PREMIGRATE_INPUTS=1", f"GRASU_SHARDED_METADATA_REPLICAS={replicas}",
            "GRASU_SHARDED_EVENT_TRACE=0", host, "--update-setup-once", image, graph, oracle]


def pma_oracle(pin):
    check = record("PMA " + checked(pin).read_text(), "PMA")
    if (check.get("status") != "PASS" or check.get("mismatches") != "0"
            or any(int(check[key]) <= 0 for key in ("touched_segments", "checked_words"))):
        raise ValueError("G PMA readback did not validate")


def memory_group():
    group = check_memory(require_live_reserve=False)
    high = (group / "memory.high").read_text().strip()
    if high == "max" or not 0 < int(high) <= 7 * 2**30:
        raise MemoryError("native Figure 8 requires memory.high at most 7 GiB")
    return group


def run(args):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", args.g_unit)
            or not re.fullmatch(r"[0-9a-f]{32}", args.g_invocation)
            or not 1 <= args.wait_seconds <= 111600):
        raise ValueError("exact G producer and bounded wait required")
    group = memory_group()
    reservation = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    args.output.mkdir(parents=True, exist_ok=False)
    result = args.output / "results.json"
    stage = dict(unit=args.g_unit, invocation=args.g_invocation, observed=False, report_path=str(args.g_report))
    report = dict(status="WAITING_FOR_G_GATE", stage=stage, board_launch_attempted=False,
                  bdf=BDF, requested_runs_per_arm=1, warmups=0, dataset="AU", updates=512,
                  boundary=BOUNDARY)
    save(result, report)
    try:
        spine_pin, host = identity(args.spine), identity(args.g_host)
        spine = json.loads(checked(spine_pin).read_text())
        gr_input = checked(spine["input"])
        spine_clock = clocks.replay(spine["clock_evidence"])
        spine_text = checked(spine["run"]["stdout"]).read_text()
        if (spine.get("status") != "PASS" or spine["input"]["sha256"] != AU_SHA
                or host["sha256"] != args.g_host_sha256
                or spine_clock != spine["clock"] or spine_clock["bdf"] != BDF
                or record(spine_text, "SPINE_DEVICE") != {"bdf": BDF}):
            raise ValueError("invalid AU/512 Spine receipt or G host identity")
        pins = [spine_pin, host, spine["input"], spine["host"], spine["run"]["stdout"],
                spine["run"]["stderr"], spine_clock["binary"], identity(__file__)]
        spine_ns = timer(spine_text, "spine")
        deadline = time.monotonic() + args.wait_seconds
        while not follow.ready(stage, service_state(args.g_unit), follow.STAGE_PASS["g"], ALGORITHM):
            save(result, report)
            poll_until(deadline)
        g = json.loads(checked(stage["receipt"]).read_text())
        g_host = next(pin for pin in g["pins"] if pin["path"] == g["row"]["command"][-5])
        image = clocks.replay(g["row"]["clock_evidence"])["binary"]
        gate = replay_g(args.g_report, args.g_reference, ALGORITHM, g_host, image)
        if gate["report"] != stage["receipt"]:
            raise ValueError("independent G report changed during replay")
        if gate["candidate_clock"]["driver_reported_mhz"][0] != spine_clock["driver_reported_mhz"][0]:
            raise ValueError("native setup comparison requires the same primary reported clock")
        libraries = paired_loader(checked(g_host), checked(host))
        pins += [image, stage["receipt"], gate["reference"], g_host]
        report.update(pins=pins, baseline_g=gate, xrt_libraries=libraries, spine_ns=spine_ns)
        expected = clocks.image(checked(image), args.output, "gr")
        oracle = args.output / "gr-oracle.txt"
        command = gr_command(args.g_host, image["path"], gr_input, oracle)
        while True:
            report["status"] = "WAITING_FOR_BOARD"
            try:
                with lease(DEVICE, BDF) as (node, fd):
                    require_unthrottled((group / "memory.events").read_text())
                    admission = reservation.sample(available_memory_bytes(), containment.other_builds(), MEMORY, commit=True)
                    report.update(status="WAITING_FOR_MEMORY", admission=admission)
                    if admission["admitted"]:
                        for pin in pins:
                            checked(pin)
                        if paired_loader(g_host["path"], host["path"]) != libraries:
                            raise ValueError("G XRT library set changed")
                        report.update(status="RUNNING_G", board_launch_attempted=True)
                        save(result, report)
                        report["gr"] = execute(command, args.output, "gr", fd, node, BDF)
                        report["gr_clock_evidence"] = clocks.capture(BDF, expected, args.output, "gr")
                        break
            except BlockingIOError:
                if report["board_launch_attempted"]:
                    raise
            save(result, report)
            poll_until(deadline)
        clock = clocks.replay(report["gr_clock_evidence"])
        if (clock["bdf"], clock["binary"], clock["driver_reported_mhz"]) != (
                BDF, image, gate["candidate_clock"]["driver_reported_mhz"]):
            raise ValueError("G loaded image or clock differs from independent G gate")
        report["gr_oracle"] = identity(oracle)
        pma_oracle(report["gr_oracle"])
        gr_ns = timer(checked(report["gr"]["stdout"]).read_text(), "gr")
        require_unthrottled((group / "memory.events").read_text())
        for pin in pins:
            checked(pin)
        report.update(status="MEASURED_AU512_SETUP_ONLY", gr_ns=gr_ns, gr_clock=clock, spine_clock=spine_clock,
                      speedup_gr_over_spine=gr_ns["setup_inclusive_ns"] / spine_ns["setup_inclusive_ns"])
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        reservation.release()
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events_final"] = (group / "memory.events").read_text()
        save(result, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("spine", "g-host", "g-report", "g-reference", "output"):
        parser.add_argument("--" + name, required=True, type=lambda value: Path(value).resolve())
    for name in ("g-host-sha256", "g-unit", "g-invocation"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--wait-seconds", type=int, default=108000)
    run(parser.parse_args())
