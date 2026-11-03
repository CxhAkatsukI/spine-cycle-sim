"""Run one guarded public A4 active-min resident reference superstep."""

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import runtime
from spine_cycle_sim.experiments.sharded_k4_stages.board import require_idle_board
from .. import artifact, oracle
from ..source_build.snapshot import unchanged
from ..source_retention import clocks
from ..source_retention.runtime import check_memory, execute, lease, save
from . import admission
from .analysis import event_window

ALGORITHMS = ("cc", "weighted_sssp")
INPUTS = ("execution", "tasks", "initial", "degrees", "csr_offsets", "csr_destinations")
STATE = {"cc": ("cc_initial",), "weighted_sssp": ("sssp_initial", "sssp_tasks", "sssp_weights")}
BOUNDARY = "resident first-CU-start to last-CU-end; internal host gaps included; DMA/restore/readback excluded"


def read_offline(host, algorithm, inputs, output):
    command = ["/usr/bin/taskset", "-c", "124,125", str(host), "offline", algorithm,
               str(inputs), str(output / "offline")]
    with (output / "offline.stdout.txt").open("x") as stdout, (output / "offline.stderr.txt").open("x") as stderr:
        subprocess.run(command, cwd=output, stdout=stdout, stderr=stderr, timeout=240, check=True)
    directory = output / "offline"
    result = json.loads((directory / "result.json").read_text())
    if (result.get("status") != "A4_ACTIVE_MIN_OFFLINE_PASS_NOT_FPGA" or
            result.get("algorithm") != algorithm or result.get("topology") != "a4" or
            type(result.get("iterations")) is not int or result["iterations"] != 1 or
            result.get("hardware_timing_measured") is not False or result.get("events") != []):
        raise ValueError("explicit offline active-min oracle success required")
    expected = artifact.identity(directory / "expected.u32le")
    return result, expected, artifact.identity(directory / "result.json")


def inspect(directory, offline, expected, inputs, bdf):
    result_path = directory / "result.json"
    result = json.loads(result_path.read_text())
    fields = ("algorithm", "topology", "iterations", "vertices", "logical_edges", "physical_edges", "tasks")
    if (result.get("status") != "A4_ACTIVE_MIN_BOARD_PASS" or
            result.get("hardware_timing_measured") is not True or result.get("bdf") != bdf or
            any(key not in result or type(result[key]) is not type(offline[key]) or result[key] != offline[key]
                for key in fields)):
        raise ValueError("board and offline algorithm, geometry or leased BDF differs")
    output_pins = [artifact.identity(result_path)]
    for name in ("expected", "apply_property", *(f"replica{lane}" for lane in range(4))):
        pin = artifact.identity(directory / f"{name}.u32le")
        if pin["sha256"] != expected["sha256"]:
            raise ValueError("board output differs from the offline CSR oracle")
        output_pins.append(pin)
    tasks = offline["tasks"]
    descriptor = oracle.read_words(inputs / "execution.u32le", 8 + 8 * tasks)
    if (list(descriptor[:2]) != [0x3447524F, 1] or list(descriptor[2:4]) !=
            [offline["vertices"], offline["logical_edges"]] or descriptor[6] != tasks):
        raise ValueError("A4 descriptor geometry differs from the executed oracle")
    identities = [("hbm_wrapper", 0, 0), ("apply", 0, 0)]
    identities += [("little", index, descriptor[8 + 8 * index + 2]) for index in range(tasks)]
    events = result["events"]
    busy, span = event_window(events)
    wall = result["enqueue_to_completion_ms"]
    if (any(type(event.get(key)) is not int for event in events for key in ("ordinal", "lane")) or
            [(event.get("role"), event["ordinal"], event["lane"]) for event in events] != identities or
            any(not 0 <= lane < 4 for _, _, lane in identities) or
            type(result["event_union_ns"]) is not int or type(result["event_span_ns"]) is not int or
            (busy, span) != (result["event_union_ns"], result["event_span_ns"]) or
            type(wall) not in (int, float) or not math.isfinite(wall) or wall <= 0 or
            span > math.ceil(wall * 1e6)):
        raise ValueError("raw active-min kernel identities or timestamp envelope differ")
    return {"event_span_ns": span, "event_union_ns": busy, "enqueue_to_completion_ms": wall,
            "output_pins": output_pins, "oracle_sha256": expected["sha256"]}


def run(route, host, inputs, output, *, algorithm, device, bdf):
    if (algorithm not in ALGORITHMS or type(device) is not int or device not in (0, 1) or
            not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", bdf)):
        raise ValueError("explicit active-min algorithm, U55C index and PCI address required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "algorithm": algorithm, "device_index": device, "bdf": bdf,
              "boundary": BOUNDARY, "requested_runs": 1, "board_launch_attempted": False,
              "hardware_timing_measured": False, "convergence_measured": False,
              "performance_retention_measured": False, "errors": []}
    path = output / "results.json"
    save(path, report)
    try:
        group = check_memory()
        if int((group / "memory.high").read_text()) > 7 * 2**30:
            raise MemoryError("active-min board run requires memory.high at most 7 GiB")
        runtime.require_clean_environment(host, output)
        if any(key in os.environ for key in ("ORIGINAL_R_LEASE_FD", "ORIGINAL_R_EXPECT_BDF")):
            raise ValueError("inherited original-R device/lease override is forbidden")
        pins = [artifact.identity(host), *(artifact.identity(inputs / f"{name}.u32le")
                                          for name in INPUTS + STATE[algorithm])]
        report["pins"] = pins
        checked = admission.review(route, output / "routed_admission", topology="a4", algorithm=algorithm)
        report["routed_admission"] = checked
        pins.extend(checked["pins"])
        offline, expected, result_pin = read_offline(host, algorithm, inputs, output)
        report["offline"] = {"result": result_pin, "expected": expected, "geometry": offline}
        pins.extend((result_pin, expected))
        unchanged(pins)
        binary = checked["xclbin"]["path"]
        destination = output / "board"
        with lease(device, bdf) as (render, fd):
            require_idle_board(render)
            captured = runtime.capture(host, render, output / "runtime")
            if captured["device"]["bdf"] != bdf:
                raise ValueError("leased runtime BDF differs")
            report["runtime"] = captured
            image = clocks.image(binary, output, "reference")
            unchanged(pins)
            report.update(status="RUNNING_REFERENCE_ONCE", board_launch_attempted=True)
            save(path, report)
            report["execution"] = execute([host, "board", algorithm, inputs, destination, binary, device],
                                          output, "reference", fd, render, bdf)
            report["clock_evidence"] = clocks.capture(bdf, image, output, "reference")
            if clocks.replay(report["clock_evidence"])["bdf"] != bdf:
                raise ValueError("clock observation belongs to another device")
            report["analysis"] = inspect(destination, offline, expected, inputs, bdf)
            runtime.unchanged(captured, render)
            unchanged(pins + report["analysis"]["output_pins"])
        report.update(status="A4_ACTIVE_MIN_REFERENCE_MEASURED_NOT_PAIRED", hardware_timing_measured=True)
    except BaseException as error:
        report.update(status="FAILED_RETAINED")
        report["errors"].append(repr(error))
        raise
    finally:
        save(path, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("route", "host", "inputs", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--algorithm", choices=ALGORITHMS, required=True)
    parser.add_argument("--device", type=int, choices=(0, 1), required=True)
    parser.add_argument("--bdf", required=True)
    args = parser.parse_args()
    print(run(args.route.resolve(), args.host.absolute(), args.inputs.resolve(), args.output.resolve(),
              algorithm=args.algorithm, device=args.device, bdf=args.bdf)["status"], flush=True)
