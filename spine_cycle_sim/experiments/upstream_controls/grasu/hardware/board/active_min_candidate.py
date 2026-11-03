"""Measure G once on a pinned CC or weighted-SSSP adapter-repair image."""

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import re
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    runner_pins, service_state,
)
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness.board_memory import require_unthrottled
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import active_min_follow, active_min_pair
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import clocks
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.analysis import (
    profiled_runs, records, summarize,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.follow import unchanged
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import (
    check_memory, execute, identity, lease, save,
)
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import containment
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from .native_profile import update_only_profile
from .reference_board import BDF, DEVICE, IMAGE_SHA256, INPUT_SHA256


HOST_SHA256 = {
    "cc": "b4106f1f5886bbf7374ddc19e693705018f127ba4e0b1e2be3065dffa178bf55",
    "weighted_sssp": "8e5d95a07bf3166de28e9835bfd5cfddc3fcd62bbce8fd47bf8941b5eb8cafdd",
}
MEMORY = {"tree_memory_gib": 8, "reserve_gib": 32, "allow_bounded_builds": True}


def reference_arm(path):
    frozen = json.loads(path.read_text())
    config, row = frozen["config"], frozen["row"]
    graph, image = (frozen["pins"][name] for name in ("input", "image"))
    host, build = (frozen["pins"][name] for name in ("host", "host_build"))
    unchanged([graph, image, host, build, row["stdout"]])
    host_build = json.loads(Path(build["path"]).read_text())
    measured_config, = records(row["stdout"]["path"], "G_CONTROL_CONFIG ")
    clock = clocks.replay(row["clock_evidence"])
    if (frozen["status"] != "REFERENCE_MEASURED_AWAITING_CANDIDATE"
            or (frozen["device"], frozen["bdf"], frozen["partition_vertices"], frozen["repetitions"])
            != (DEVICE, BDF, 65536, 1)
            or graph["sha256"] != INPUT_SHA256 or image["sha256"] != IMAGE_SHA256
            or host_build["binary"] != host or host_build["repetitions"] != 1
            or config != measured_config
            or clock["bdf"] != BDF or clock["binary"] != image
            or tuple(config[key] for key in ("vertices", "updates", "shards", "pma_slots", "metadata_replicas"))
            != (515281, 131072, 8, 2245472, 4)):
        raise ValueError("expected the frozen one-shot public G reference on AU 131K")
    return graph, config, clock, profiled_runs(row), host, host_build["xrt_library"]


def compare(ref_runs, profile, ref_clock, clock):
    if clock["bdf"] != BDF or ref_clock["bdf"] != BDF:
        raise ValueError("both G arms must use the same PCI device")
    comparison = summarize(ref_runs, [profile], repetitions=1)
    equal = clock["driver_reported_mhz"] == ref_clock["driver_reported_mhz"]
    return {**comparison, "equal_driver_reported_clocks": equal,
            "retention_gate_pass": equal and comparison["at_most_15_percent_slower"]}


def poll_until(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("bounded route, memory or board wait expired before G execution")
    time.sleep(min(30, remaining))


def run(args):
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", args.unit)
            or not re.fullmatch(r"[0-9a-f]{32}", args.invocation) or not 1 <= args.wait_seconds <= 111600):
        raise ValueError("explicit route service, invocation and bounded wait required")
    group = check_memory()
    limits = containment.verify(group, memory_gib=8)["limits"]
    if int(limits["memory.high"]) > 7 * 2**30:
        raise MemoryError("one-shot G screen requires memory.high at most 7 GiB")
    reservation = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    args.output.mkdir(parents=True, exist_ok=False)
    result = args.output / "results.json"
    report = {"status": "PREPARING", "algorithm": args.algorithm, "repetitions": 1,
              "bdf": BDF, "device": DEVICE, "board_launch_attempted": False,
              "route_unit": args.unit, "route_invocation": args.invocation,
              "boundary": "first update CU start through last update CU end, including inter-shard gaps; "
                          "final barrier, input residency and readback outside the event span"}
    save(result, report)
    try:
        host = identity(args.host)
        if host["sha256"] != HOST_SHA256[args.algorithm]:
            raise ValueError("expected the exact preflighted algorithm host")
        reference = identity(args.reference)
        graph, config, ref_clock, ref_runs, ref_host, ref_xrt = reference_arm(args.reference)
        libraries = active_min_pair.paired_loader(ref_host["path"], args.host)
        if libraries.get(ref_xrt["path"]) != ref_xrt["sha256"]:
            raise ValueError("G hosts must resolve the recorded public control XRT library")
        report["xrt_libraries"] = libraries
        pins = [host, reference, graph, ref_host, identity(__file__),
                identity(args.route / "manifest.json"), *runner_pins()]
        deadline, observed = time.monotonic() + args.wait_seconds, False
        while True:
            state = service_state(args.unit)
            observed |= state["LoadState"] == "loaded" and state["InvocationID"] == args.invocation
            report.update(status="WAITING_FOR_ROUTE", route_state=state, pins=pins)
            save(result, report)
            if active_min_follow.ready("candidate", args.route, state, args.invocation, observed, args.algorithm):
                break
            poll_until(deadline)
        image, route_pins = active_min_pair.candidate_route(args.route, args.algorithm)
        pins.extend(route_pins)
        unchanged(pins)
        expected = clocks.image(image["path"], args.output, "candidate")
        oracle = args.output / "native-oracle.txt"
        argv = ["/usr/bin/env", "-u", "XCL_EMULATION_MODE", f"XCL_DEVICE_INDEX={DEVICE}",
                f"GRASU_REGRAPH_EXPECT_BDF={BDF}", "GRASU_UPDATE_REPEATS=1",
                "GRASU_SHARDED_PREMIGRATE_INPUTS=1", "GRASU_SHARDED_METADATA_REPLICAS=4",
                "GRASU_SHARDED_EVENT_TRACE=0", args.host, "--update-only", image["path"], graph["path"], oracle]
        while True:
            with ExitStack() as stack:
                try:
                    node, fd = stack.enter_context(lease(DEVICE, BDF))
                except BlockingIOError:
                    report["status"] = "WAITING_FOR_BOARD"
                else:
                    require_unthrottled((group / "memory.events").read_text())
                    admission = reservation.sample(available_memory_bytes(), containment.other_builds(), MEMORY, commit=True)
                    report.update(status="WAITING_FOR_MEMORY", admission=admission)
                    if admission["admitted"]:
                        unchanged(pins)
                        if active_min_pair.paired_loader(ref_host["path"], args.host) != libraries:
                            raise ValueError("G XRT library set changed before board execution")
                        report.update(status="RUNNING_CANDIDATE", board_launch_attempted=True, image=image)
                        save(result, report)
                        row = execute(argv, args.output, "candidate", fd, node, BDF)
                        report["row"] = row
                        row["clock_evidence"] = clocks.capture(BDF, expected, args.output, "candidate")
                        break
            save(result, report)
            poll_until(deadline)
        row["oracle"] = identity(oracle)
        profile = update_only_profile(Path(row["stdout"]["path"]).read_text(), oracle.read_text(),
                                      bdf=BDF, reference=config, algorithm=args.algorithm)
        if profile["config"]["static_edges"] != "390847":
            raise ValueError("unexpected initial edge count")
        clock = clocks.replay(row["clock_evidence"])
        if clock["binary"] != expected["binary"]:
            raise ValueError("clock record does not describe the exact repaired image")
        comparison = compare(ref_runs, profile, ref_clock, clock)
        require_unthrottled((group / "memory.events").read_text())
        unchanged(pins)
        report.update(status="G_GATE_PASS_FOR_ACTIVE_MIN_IMAGE" if comparison["retention_gate_pass"]
                      else "G_PERFORMANCE_GATE_FAILED_RETAINED", profile=profile, comparison=comparison,
                      reference_clock=ref_clock, candidate_clock=clock)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        reservation.release()
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events_final"] = (group / "memory.events").read_text()
        save(result, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference", "host", "route", "output"):
        parser.add_argument("--" + name, required=True, type=lambda value: Path(value).resolve())
    for name in ("unit", "invocation"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--algorithm", choices=HOST_SHA256, required=True)
    parser.add_argument("--wait-seconds", type=int, default=108000)
    result = run(parser.parse_args())
    print(result["status"], flush=True)
    raise SystemExit(0 if result["comparison"]["retention_gate_pass"] else 1)
