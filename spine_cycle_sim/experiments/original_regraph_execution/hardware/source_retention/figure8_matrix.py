"""Measure the six remaining native setup pairs after the admitted AU/512 pair."""

import argparse
import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import (
    route_finished, service_state,
)
from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import board_memory
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import containment
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.active_min_candidate import (
    BDF, DEVICE, poll_until,
)
from ..board_execution.active_min_pair import paired_loader
from ..board_execution.active_min_follow import exact_service
from . import clocks, figure8_au_pair as au
from .active_min_admission import checked, replay_g
from .figure8_manifest import CASES
from .runtime import check_memory, execute, identity, lease, save


ANCHOR = ("AU", 512)
CAPACITY_CASE = ("SO", 512)
AFFINITY = ["/usr/bin/taskset", "-c", "124,125"]


def load_cases(pin, sha256):
    report = json.loads(checked(pin).read_text())
    if pin["sha256"] != sha256 or report["schema"] != "figure8-native-input-identity-v1":
        raise ValueError("wrong Figure 8 input manifest")
    cases = {(row["dataset"], row["updates"]): row for row in report["cases"]}
    if tuple(cases) != CASES or len(report["cases"]) != len(CASES):
        raise ValueError("expected the exact seven Figure 8 cases")
    if cases[ANCHOR]["native_g_input"]["sha256"] != au.AU_SHA:
        raise ValueError("AU/512 does not match the measured anchor")
    return cases


def ratio(timers):
    return timers["gr"]["setup_inclusive_ns"] / timers["spine"]["setup_inclusive_ns"]


def same_clock(clock, expected):
    fields = ("bdf", "uuid", "binary", "driver_reported_mhz")
    if any(clock[field] != expected[field] for field in fields) or clock["bdf"] != BDF:
        raise ValueError("loaded image or clock differs from the admitted anchor")


def spine_args(host, image, graph):
    return [host, image, "--update-setup-once", "--dynamic-graph", graph]


def spine_command(host, image, graph):
    return ["/usr/bin/env", "-u", "XCL_EMULATION_MODE", f"XCL_DEVICE_INDEX={DEVICE}",
            f"SPINE_EXPECT_BDF={BDF}", *spine_args(host, image, graph)]


def reuse_capacity_spine(pin, manifest, anchor, case, host, reference):
    prior = json.loads(checked(pin).read_text())
    if (prior["status"] != "PARTIAL_OR_FAILED_RETAINED" or prior["manifest"] != manifest
            or prior["anchor"] != anchor or prior["boundary"] != au.BOUNDARY
            or prior["requested_runs_per_arm"] != 1 or prior["warmups"] != 0):
        raise ValueError("capacity retry requires the exact terminal one-shot predecessor")
    previous, = [row for row in prior["cases"] if (row["dataset"], row["updates"]) == CAPACITY_CASE]
    if (previous["input"] != case["native_g_input"] or previous["status"] != "FAILED_RETAINED"
            or previous["attempts"] != ["spine", "gr"] or previous["arms"]["gr"] != {}):
        raise ValueError("capacity retry requires an untimed G failure and one measured Spine arm")
    failed_log = identity(Path(pin["path"]).parent / "SO_u512/gr.stderr.txt")
    if checked(failed_log).read_text().strip() != "ERROR: replicated metadata exceeds lane-aware HBM capacity":
        raise ValueError("the four-copy failure is not the expected HBM capacity error")
    spine = previous["arms"]["spine"]
    command = AFFINITY + spine_command(host["path"], reference["binary"]["path"], case["native_g_input"]["path"])
    checked(spine["run"]["stderr"])
    same_clock(clocks.replay(spine["clock_evidence"]), reference)
    if spine["run"]["command"] != command or inspect(spine["run"], "spine", case) != spine["timer"]:
        raise ValueError("predecessor Spine command or timer differs from the raw evidence")
    return spine, failed_log


def wait_anchor(path, unit, invocation, wait_seconds, checkpoint):
    exact_service(unit, invocation)
    if not 1 <= wait_seconds <= 111600:
        raise ValueError("anchor wait must be bounded to 31 hours")
    observed = False
    deadline = time.monotonic() + wait_seconds
    while True:
        state = service_state(unit)
        checkpoint(state)
        if state["LoadState"] == "not-found" and not state["InvocationID"] and observed:
            break  # A successful transient unit can disappear before the next poll.
        if route_finished(state, invocation):
            break
        observed = True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("AU/512 admission wait expired before any board run")
        time.sleep(min(30, remaining))
    return identity(path)


def load_anchor(pin, case):
    anchor = json.loads(checked(pin).read_text())
    if (anchor.get("status") != "MEASURED_AU512_SETUP_ONLY"
            or (anchor["dataset"], anchor["updates"]) != ANCHOR or anchor["boundary"] != au.BOUNDARY
            or anchor["requested_runs_per_arm"] != 1 or anchor["warmups"] != 0):
        raise ValueError("the AU/512 one-shot pair has not been admitted")
    for item in anchor["pins"]:
        checked(item)
    spine_pin, gr_host = anchor["pins"][:2]
    spine = json.loads(checked(spine_pin).read_text())
    gr_clock = clocks.replay(anchor["gr_clock_evidence"])
    spine_clock = clocks.replay(spine["clock_evidence"])
    same_clock(gr_clock, anchor["gr_clock"])
    same_clock(spine_clock, anchor["spine_clock"])
    baseline = anchor["baseline_g"]
    gate_report = json.loads(checked(baseline["report"]).read_text())
    gate_host_path = gate_report["row"]["command"][-5]
    gate_host = next(item for item in gate_report["pins"] if item["path"] == gate_host_path)
    if replay_g(Path(baseline["report"]["path"]), Path(baseline["reference"]["path"]), au.ALGORITHM,
                gate_host, gr_clock["binary"]) != baseline:
        raise ValueError("independent G gate no longer replays")
    same_clock(gr_clock, baseline["candidate_clock"])
    if gr_clock["driver_reported_mhz"][0] != spine_clock["driver_reported_mhz"][0]:
        raise ValueError("different primary clocks in AU/512 anchor")

    graph = checked(case["native_g_input"])
    gr_bin, spine_bin = gr_clock["binary"]["path"], spine_clock["binary"]["path"]
    hosts = {"spine": spine["host"], "gr": gr_host}
    if (spine["status"] != "PASS" or spine["input"] != case["native_g_input"]
            or spine["run"]["command"] != AFFINITY + spine_args(hosts["spine"]["path"], spine_bin, str(graph))
            or anchor["gr"]["command"] != AFFINITY + au.gr_command(
                gr_host["path"], gr_bin, str(graph), anchor["gr_oracle"]["path"])):
        raise ValueError("AU/512 command or input mismatch")
    for item in (*hosts.values(), spine["run"]["stderr"], anchor["gr"]["stderr"]):
        checked(item)
    au.pma_oracle(anchor["gr_oracle"])
    runs = {"spine": spine["run"], "gr": anchor["gr"]}
    timers = {arm: inspect(run, arm, case) for arm, run in runs.items()}
    if (any(timers[arm] != anchor[f"{arm}_ns"] for arm in timers)
            or ratio(timers) != anchor["speedup_gr_over_spine"]):
        raise ValueError("AU/512 timers or speedup differ from raw logs")
    return hosts, {"spine": spine_clock, "gr": gr_clock}, anchor["xrt_libraries"], timers


def inspect(run, arm, case):
    raw = checked(run["stdout"]).read_text()
    if arm == "spine" and au.record(raw, "SPINE_DEVICE") != {"bdf": BDF}:
        raise ValueError("wrong Spine card")
    return au.timer(raw, arm, case)


def unthrottled(group):
    try:
        board_memory.require_unthrottled((group / "memory.events").read_text())
    except ValueError as error:
        raise MemoryError(str(error)) from error


def measure(case, row, output, deadline, reservation, memory, hosts, reference, libraries, checkpoint,
            *, replicas=4, arms=("spine", "gr")):
    graph = checked(case["native_g_input"])
    paths = {arm: checked(pin) for arm, pin in hosts.items()}
    images = {arm: clocks.image(checked(reference[arm]["binary"]), output, arm) for arm in arms}
    if paired_loader(paths["spine"], paths["gr"]) != libraries:
        raise ValueError("XRT library identity differs from the AU/512 pair")
    oracle = output / "gr-oracle.txt"
    commands = {
        "spine": spine_command(paths["spine"], reference["spine"]["binary"]["path"], graph),
        "gr": au.gr_command(paths["gr"], reference["gr"]["binary"]["path"], graph, oracle, replicas=replicas),
    }
    while True:
        try:
            with lease(DEVICE, BDF) as (node, fd):
                unthrottled(reservation.own)
                admission = reservation.sample(available_memory_bytes(), containment.other_builds(), memory, commit=True)
                row.update(status="WAITING_FOR_MEMORY", admission=admission)
                if admission["admitted"]:
                    for arm in arms:
                        row.update(status=f"RUNNING_{arm.upper()}")
                        row["attempts"].append(arm)
                        checkpoint()
                        arm_row = row["arms"].setdefault(arm, {})
                        arm_row["run"] = execute(commands[arm], output, arm, fd, node, BDF,
                                                 memory_gib=memory["tree_memory_gib"])
                        arm_row["clock_evidence"] = clocks.capture(BDF, images[arm], output, arm)
                        same_clock(clocks.replay(arm_row["clock_evidence"]), reference[arm])
                        arm_row["timer"] = inspect(arm_row["run"], arm, case)
                        if arm == "gr":
                            arm_row["pma_oracle"] = identity(oracle)
                            au.pma_oracle(arm_row["pma_oracle"])
                        unthrottled(reservation.own)
                        checkpoint()
                    checked(case["native_g_input"])
                    row.update(status="MEASURED_SETUP_ONLY",
                               speedup_gr_over_spine=ratio({arm: item["timer"] for arm, item in row["arms"].items()}))
                    return
        except BlockingIOError:
            if row["attempts"]:
                raise
            row["status"] = "WAITING_FOR_BOARD"
        checkpoint()
        poll_until(deadline)


def run(args):
    if not 1 <= args.wait_seconds <= 3600:
        raise ValueError("wait_seconds must be between 1 and 3600 per case")
    manifest = identity(args.manifest)
    cases = load_cases(manifest, args.manifest_sha256)
    retry = args.retry_so_single_directory
    if retry and args.wait_for_anchor:
        raise ValueError("a capacity retry requires an existing anchor")
    memory = board_memory.policy(args.memory_gib)
    group = check_memory(args.memory_gib, require_live_reserve=False)
    board_memory.validate(containment.verify(group, memory_gib=args.memory_gib)["limits"], memory)
    reservation = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    report = dict(status="PREPARING", manifest=manifest, runner=identity(__file__),
                  boundary=au.BOUNDARY, requested_runs_per_arm=1, warmups=0, memory=memory, cases=rows)

    def checkpoint():
        save(args.output / "results.json", report)

    def checkpoint_anchor(state):
        report.update(status="WAITING_FOR_AU512", anchor_service_state=state)
        checkpoint()

    try:
        if args.wait_for_anchor:
            unit, invocation = args.wait_for_anchor
            report["anchor_dependency"] = dict(unit=unit, invocation=invocation, path=str(args.anchor))
            anchor = wait_anchor(args.anchor, unit, invocation, args.anchor_wait_seconds, checkpoint_anchor)
        else:
            anchor = identity(args.anchor)
        hosts, reference, libraries, anchor_timers = load_anchor(anchor, cases[ANCHOR])
        checked(manifest)
        report.update(status="RUNNING", anchor=anchor)
        checkpoint()
        for key, case in ([(CAPACITY_CASE, cases[CAPACITY_CASE])] if retry else cases.items()):
            row = dict(dataset=key[0], updates=key[1], input=case["native_g_input"], attempts=[], arms={})
            rows.append(row)
            if key == ANCHOR:
                row.update(status="REUSED_MEASURED_ANCHOR", timers=anchor_timers,
                           speedup_gr_over_spine=ratio(anchor_timers))
                checkpoint()
                continue
            output = args.output / f"{key[0]}_u{key[1]}"
            output.mkdir()
            try:
                if retry:
                    path, digest = retry
                    predecessor = identity(path)
                    if predecessor["sha256"] != digest:
                        raise ValueError("capacity retry predecessor digest mismatch")
                    spine, failed_log = reuse_capacity_spine(
                        predecessor, manifest, anchor, case, hosts["spine"], reference["spine"])
                    report["capacity_retry"] = dict(predecessor=predecessor, failure=failed_log,
                                                    gr_directory_copies=1, gr_source_gate_same_policy=False)
                    row["arms"]["spine"] = spine
                    checkpoint()
                measure(case, row, output, time.monotonic() + args.wait_seconds, reservation,
                        memory, hosts, reference, libraries, checkpoint, replicas=1 if retry else 4,
                        arms=("gr",) if retry else ("spine", "gr"))
                if retry:
                    row["status"] = "MEASURED_CAPACITY_DIAGNOSTIC_ONLY"
            except (MemoryError, TimeoutError) as error:
                row.update(status="STOPPED_RETAINED", error=repr(error))
                raise
            except Exception as error:
                row.update(status="FAILED_RETAINED", error=repr(error))
            finally:
                reservation.release()
                checkpoint()
        if retry:
            report["status"] = rows[0]["status"]
        else:
            report["status"] = ("MEASURED_ALL_SEVEN_SETUP_PAIRS"
                                if all("speedup_gr_over_spine" in row for row in rows)
                                else "PARTIAL_OR_FAILED_RETAINED")
    except BaseException as error:
        report.update(status="STOPPED_RETAINED", error=repr(error))
        raise
    finally:
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events_final"] = (group / "memory.events").read_text()
        checkpoint()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "anchor", "output"):
        parser.add_argument("--" + name, required=True, type=lambda value: Path(value).resolve())
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--wait-for-anchor", nargs=2, metavar=("UNIT", "INVOCATION"))
    parser.add_argument("--retry-so-single-directory", nargs=2, metavar=("PREDECESSOR", "SHA256"))
    parser.add_argument("--anchor-wait-seconds", type=int, default=111600)
    parser.add_argument("--wait-seconds", type=int, default=300)
    parser.add_argument("--memory-gib", type=int, choices=board_memory.HIGH_GIB, default=24)
    if run(parser.parse_args())["status"] not in (
            "MEASURED_ALL_SEVEN_SETUP_PAIRS", "MEASURED_CAPACITY_DIAGNOSTIC_ONLY"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
