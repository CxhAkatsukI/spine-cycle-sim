"""Run one resident SSSP/CC FPGA pair using the independently admitted G+R image."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import concurrent, containment
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from . import active_min_admission, cc_resident_wall, clocks, spine_cc_warm_receipt
from .follow import unchanged
from .resident_board import LEGACY_LOCK
from .runtime import identity, lease, save


DEVICE, BDF = 1, "0000:c1:00.1"
DATASETS = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")
ALGORITHMS = {"cc": "connected_components", "weighted_sssp": "weighted_sssp"}
FROZEN_ALGORITHMS = {
    "cc": ("cc", ALGORITHMS["cc"]),
    "weighted_sssp": ("sssp", ALGORITHMS["weighted_sssp"]),
    "respr": ("respr", "residual_pagerank"),
}
COMPARATOR_SHA256 = "0fcd0d63aab314b90e957ede40cad53fa9f257199ad9f9bb4e8ce8eca9709b3f"
BOUNDARY = "resident_update_to_final_readback_wall_including_host_relaunch"


def frozen_case(previous, algorithm, dataset):
    prefix, logical = FROZEN_ALGORITHMS[algorithm]
    key = prefix + "-" + dataset.lower()
    config_path, manifest_path = previous / f"{key}.json", previous / key / "manifest.json"
    pins = [identity(config_path), identity(manifest_path)]
    config, manifest = (json.loads(Path(pin["path"]).read_text()) for pin in pins)
    fields = ("dataset", "logical", "source", "graph", "spine_host", "spine_binary", "memory_gib")
    if (manifest["boundary"] != BOUNDARY or any(config[k] != manifest["config"][k] for k in fields)
            or (config["logical"], config["dataset"]) != (logical, dataset)):
        raise ValueError("frozen case and prior execution disagree")
    case = {k: config[k] for k in fields}
    for name in ("graph", "spine_host", "spine_binary"):
        pin = identity(case[name])
        for records in (config["expected_pins"], manifest["pins"]):
            hashes = {row["sha256"] for row in records if row["path"] == pin["path"]}
            if hashes != {pin["sha256"]}:
                raise ValueError("frozen artifact missing or changed: " + name)
        case[name] = pin["path"]
        pins.append(pin)
    with Path(case["graph"]).open() as stream:
        vertices, edges, updates = map(int, stream.readline().split())
    if min(vertices, edges, updates) <= 0 or type(case["source"]) is not int or not 0 <= case["source"] < vertices:
        raise ValueError("invalid graph dimensions or source")
    if case["memory_gib"] not in (16, 24, 32):
        raise ValueError("expected frozen per-case memory budget")
    return dict(case, vertices=vertices, edges=edges, updates=updates), pins


def commands(case, gate, output):
    source = str(case["source"])
    return {
        "spine": [case["spine_host"], case["spine_binary"], "--dynamic-graph", case["graph"],
                  "--source", source, "--resident-benchmark"],
        "gr": [gate["host"]["path"], gate["image"]["path"], case["graph"],
               str(output / "gr-state.txt"), source, "256"],
    }


def environment(*, bdf=BDF, device=DEVICE):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("GRASU_", "SPINE_", "XCL_", "LD_"))}
    return dict(env, XILINX_XRT="/opt/xilinx/xrt", XCL_DEVICE_INDEX=str(device),
                LD_LIBRARY_PATH="/opt/xilinx/xrt/lib:/usr/lib/x86_64-linux-gnu", MALLOC_ARENA_MAX="2",
                SPINE_EXPECT_BDF=bdf, GRASU_REGRAPH_EXPECT_BDF=bdf,
                GRASU_UPDATE_REPEATS="1", GRASU_SHARDED_PREMIGRATE_INPUTS="1",
                GRASU_SHARDED_METADATA_REPLICAS="4", GRASU_SHARDED_EVENT_TRACE="0")


def idle(node):
    users = subprocess.run(["fuser", str(node)], capture_output=True, timeout=20)
    return users.returncode == 1 and not (users.stdout.strip() or users.stderr.strip())


def arm(name, command, expected, output, *, cc_wall=False, bdf=BDF, device=DEVICE):
    stdout, stderr = (output / f"{name}.{stream}.txt" for stream in ("stdout", "stderr"))
    env = environment(bdf=bdf, device=device)
    if cc_wall and name == "gr":
        env["GRASU_SHARDED_RESIDENT_BATCH_WALL"] = "1"
    with stdout.open("x") as out, stderr.open("x") as err:
        completed = subprocess.run(command, env=env, cwd=output, stdout=out, stderr=err, timeout=1800)
    if completed.returncode != 0:
        raise RuntimeError(f"{name} exit {completed.returncode}; see {stderr}")
    evidence = clocks.capture(bdf, expected, output, name)
    observed = clocks.replay(evidence)
    if observed["bdf"] != bdf or observed["binary"] != expected["binary"]:
        raise ValueError("measured board or image differs from the preflight")
    return dict(command=command, stdout=identity(stdout), stderr=identity(stderr),
                clock_evidence=evidence, clock=observed)


def compare(case, arms, comparator, output):
    result = output / "pair.json"
    log_pins = [row["stdout"] for row in arms.values()]
    unchanged(log_pins)
    subprocess.run(["/usr/bin/python3", str(comparator), "--algorithm", case["logical"],
                    "--source", str(case["source"]), "--spine-log", arms["spine"]["stdout"]["path"],
                    "--gr-log", arms["gr"]["stdout"]["path"], "--output", str(result)],
                   cwd=output, check=True, timeout=30)
    pair = json.loads(result.read_text())
    unchanged(log_pins)
    if (pair["boundary"], pair["vertices"], pair["logical_updates"]) != (
            BOUNDARY, case["vertices"], case["updates"]):
        raise ValueError("published state dimensions or timing boundary disagree with the frozen graph")
    return pair, identity(result)


def replay_controls(args, gate, *, warm_cc=False, stage_receipts=None):
    decisions, pins = {}, []
    controls = getattr(args, "additional_r", ())
    warm_controls = getattr(args, "cc_warm_r_controls", None)
    sssp_controls = getattr(args, "sssp_r_controls", None)
    diagnostic = getattr(args, "au_r_diagnostic_sha256", None)
    if warm_controls is not None or sssp_controls is not None:
        if (controls or (warm_controls is not None and not warm_cc)
                or (sssp_controls is not None and (args.algorithm != "weighted_sssp" or warm_controls is not None))):
            raise ValueError("additional R controls must match the declared SSSP or warm CC protocol")
        odd_receipt, odd_inputs, au_receipt, au_inputs = warm_controls or sssp_controls
        fixture, queue, odd_pin = active_min_admission.pin_odd_queue(odd_receipt, odd_inputs, args.algorithm)
        pins += [fixture, queue]
        controls = (
            ("amazon_odd", odd_pin, odd_inputs, active_min_admission.AMAZON_GEOMETRY),
            ("au_slice", identity(au_receipt), au_inputs, active_min_admission.AU_SLICE_GEOMETRY),
        )
    if diagnostic is not None and not (warm_controls or sssp_controls):
        raise ValueError("AU R exception requires both pinned cross-topology controls")
    for label, receipt, inputs, geometry in controls:
        if stage_receipts is not None and stage_receipts.get(label) != receipt:
            raise ValueError(f"{label} R receipt differs from the exact producer")
        options = {"au_diagnostic_sha256": diagnostic} if label == "au_slice" and diagnostic else {}
        decision = active_min_admission.replay_r(Path(receipt["path"]), args.algorithm, inputs,
                                                 gate["host"], gate["image"], geometry=geometry, **options)
        if (decision["report"] != receipt or
                decision["candidate_clock"]["driver_reported_mhz"] != gate["resident_mhz"]):
            raise ValueError(f"additional {label} R gate used different evidence or clocks")
        decisions[label] = decision
        pins.append(receipt)
    if warm_cc:
        if warm_controls is None or set(decisions) != {"amazon_odd", "au_slice"}:
            raise ValueError("the warm CC pair needs both the odd Amazon and AU topology R gates")
        if len({row["report"]["sha256"] for row in (gate["r"], *decisions.values())}) != 3:
            raise ValueError("the warm CC pair needs three distinct R stage receipts")
    return decisions, pins


def run(args):
    if not 0 <= args.wait_seconds <= 21600:
        raise ValueError("board and memory admission wait is limited to six hours")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREDECLARED", "dataset": args.dataset, "algorithm": args.algorithm,
              "boundary": BOUNDARY, "bdf": BDF, "warmups": 0, "repetitions_per_arm": 1,
              "attempts": [], "arms": {}}
    write = lambda: save(args.output / "results.json", report)
    write()
    memory = None
    try:
        cc_wall = getattr(args, "cc_wall_packet", None) is not None
        gate = active_min_admission.admit(args.algorithm, args.route, args.host, args.r_report,
                                           args.r_inputs, args.g_report, args.g_reference)
        bdf = gate["g"]["candidate_clock"]["bdf"]
        device = active_min_admission.g_control.BOARDS[bdf]
        report["bdf"] = bdf
        stage_receipts = getattr(args, "stage_receipts", None)
        if stage_receipts is not None and any(
                stage_receipts.get(stage) != gate[stage]["report"] for stage in ("g", "r")):
            raise ValueError("admission replay used a different producer receipt")
        case, pins = frozen_case(args.previous, args.algorithm, args.dataset)
        retained = getattr(args, "cc_warm_au_receipt", None)
        warm_layout = getattr(args, "cc_warm_layout", None)
        warm_cc = retained is not None or warm_layout is not None
        if warm_cc and (not cc_wall or args.algorithm != "cc" or bdf != spine_cc_warm_receipt.BDF):
            raise ValueError("the warm CC hosts require the matched wall scope and the qualified card")
        retained_spine = None
        if retained is not None:
            if not cc_wall or (args.algorithm, args.dataset) != ("cc", "AU"):
                raise ValueError("the warm CC arm is reusable only for the AU wall comparison")
            retained_pin = identity(retained)
            if stage_receipts is not None and stage_receipts.get("spine") != retained_pin:
                raise ValueError("warm CC receipt differs from the exact producer")
            frozen = next(pin for pin in pins if pin["path"] == case["graph"])
            retained_spine, retained_pins = spine_cc_warm_receipt.replay(
                retained_pin, frozen, bdf=bdf, affinity=spine_cc_warm_receipt.AFFINITY)
            pins += [*retained_pins, identity(spine_cc_warm_receipt.__file__)]
            report.update(retained_spine=retained_pin)
            report["arms"]["spine"] = retained_spine
        if cc_wall:
            case, added_pins = cc_resident_wall.configure(args, case, pins, retained_spine=retained_spine)
            pins += added_pins
            if warm_layout is not None:
                report["warm_layout"] = identity(warm_layout)
                report["wall_packet"] = identity(args.cc_wall_packet)
                if any(report[key] not in added_pins for key in ("warm_layout", "wall_packet")):
                    raise ValueError("warm layout or wall packet changed after admission")
            report.update(boundary=cc_resident_wall.BOUNDARY,
                          gr_host_overlay="15717a5928929cafd39dbf5a3f7fc1aaf18d167a",
                          gr_host_overlay_environment={"GRASU_SHARDED_RESIDENT_BATCH_WALL": "1"})
            command_pair = cc_resident_wall.commands(case, gate, args.output)
            if retained_spine is not None:
                command_pair["spine"] = retained_spine["command"]
        else:
            comparator = identity(args.comparator)
            if comparator["sha256"] != COMPARATOR_SHA256:
                raise ValueError("unexpected resident log comparator")
            pins.append(comparator)
            command_pair = commands(case, gate, args.output)
        pins += [gate["host"], gate["image"], gate["g"]["report"], gate["g"]["reference"], gate["r"]["report"],
                 identity(__file__), identity(active_min_admission.__file__)]
        additional_r, control_pins = replay_controls(args, gate, warm_cc=warm_cc, stage_receipts=stage_receipts)
        pins += control_pins
        if stage_receipts is not None:
            expected_stages = {"g", "r", *additional_r}
            if retained is not None:
                expected_stages.add("spine")
            if set(stage_receipts) != expected_stages:
                raise ValueError("queued producer receipts do not match the replayed stages")
        if additional_r:
            report["additional_r_gates"] = additional_r
        report.update(stage_gates=gate, case=case, pins=pins)
        budget = case["memory_gib"]
        group = containment.current()
        limits = containment.verify(group, memory_gib=budget)["limits"]
        if int(limits["memory.max"]) != budget * 2**30 or int(limits["memory.high"]) > (budget - 2) * 2**30:
            raise ValueError("reserve the frozen board host budget with a 2-GiB high-watermark margin")
        memory = concurrent.Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        policy = {"tree_memory_gib": budget, "reserve_gib": 32, "allow_bounded_builds": True}
        images = {"gr": gate["image"]["path"]}
        if retained_spine is None:
            images["spine"] = case["spine_binary"]
        expected = {name: clocks.image(path, args.output, name) for name, path in images.items()}
        affinity = (list(spine_cc_warm_receipt.AFFINITY) if warm_cc
                    else sorted(os.sched_getaffinity(0))[:4])
        if not set(affinity).issubset(os.sched_getaffinity(0)):
            raise ValueError("resident host cannot use the retained CPU affinity")
        os.sched_setaffinity(0, affinity)
        report.update(status="WAITING_FOR_MEMORY", cpu_affinity=affinity, commands=command_pair)
        write()
        deadline = time.monotonic() + args.wait_seconds
        while True:
            report["memory_admission"] = memory.sample(available_memory_bytes(), containment.other_builds(),
                                                        policy, commit=True)
            write()
            if memory.held:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("resident host memory not admitted")
            time.sleep(10)
        report["status"] = "WAITING_FOR_BOARD"
        write()
        while True:
            try:
                with LEGACY_LOCK.open("rb") as legacy:
                    fcntl.flock(legacy, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with lease(device, bdf) as (node, _):
                        if not idle(node):
                            raise BlockingIOError("card has other users")
                        report["status"] = "RUNNING"
                        for name in ("spine", "gr"):
                            if name == "spine" and retained_spine is not None:
                                continue
                            unchanged(pins)
                            if not idle(node):
                                raise RuntimeError("card acquired by another user between arms")
                            if available_memory_bytes() < policy["reserve_gib"] * 2**30:
                                raise MemoryError("resident host memory reserve fell below policy")
                            report["attempts"].append(name)
                            write()
                            report["arms"][name] = arm(name, report["commands"][name], expected[name], args.output,
                                                       cc_wall=cc_wall, bdf=bdf, device=device)
                            write()
                        break
            except BlockingIOError:
                if report["attempts"] or time.monotonic() >= deadline:
                    raise
                time.sleep(10)
        unchanged(pins)
        if report["arms"]["gr"]["clock"]["driver_reported_mhz"] != gate["resident_mhz"]:
            raise ValueError("resident G+R clock differs from the exact-image G and R screens")
        report["arms"]["gr"]["state"] = identity(args.output / "gr-state.txt")
        report["pair"], report["comparison_log"] = (
            cc_resident_wall.compare(case, report["arms"], args.output, bdf) if cc_wall
            else compare(case, report["arms"], args.comparator, args.output))
        report["status"] = "MEASURED_RESIDENT_PAIR"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        if memory is not None:
            memory.release()
            report["memory_events"] = (group / "memory.events").read_text()
            report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        write()
    return report


def parse_arguments(argv=None, *, extend=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--algorithm", required=True, choices=ALGORITHMS)
    parser.add_argument("--dataset", required=True, choices=DATASETS)
    for name in ("previous", "route", "host", "r-report", "r-inputs", "g-report", "g-reference",
                 "output"):
        parser.add_argument("--" + name, required=True, type=lambda value: Path(value).resolve())
    comparison = parser.add_mutually_exclusive_group(required=True)
    comparison.add_argument("--comparator", type=lambda value: Path(value).resolve())
    comparison.add_argument("--cc-wall-packet", type=lambda value: Path(value).resolve())
    warm = parser.add_mutually_exclusive_group()
    warm.add_argument("--cc-warm-au-receipt", type=lambda value: Path(value).resolve())
    warm.add_argument("--cc-warm-layout", type=lambda value: Path(value).resolve())
    parser.add_argument("--cc-warm-r-controls", nargs=4, type=lambda value: Path(value).resolve(),
                        metavar=("ODD_RECEIPT", "ODD_INPUTS", "AU_RECEIPT", "AU_INPUTS"))
    parser.add_argument("--sssp-r-controls", nargs=4, type=lambda value: Path(value).resolve(),
                        metavar=("ODD_RECEIPT", "ODD_INPUTS", "AU_RECEIPT", "AU_INPUTS"))
    parser.add_argument("--au-r-diagnostic-sha256",
                        help="allow a pinned AU R miss up to 22%% for the resident run only")
    parser.add_argument("--wait-seconds", type=int, default=0)
    if extend is not None:
        extend(parser)
    return parser.parse_args(argv)


def main():
    print(run(parse_arguments())["status"], flush=True)


if __name__ == "__main__":
    main()
