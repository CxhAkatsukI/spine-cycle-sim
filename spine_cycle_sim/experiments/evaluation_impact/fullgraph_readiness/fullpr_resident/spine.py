"""Admit the isolated FullPR host; keep the live three-algorithm freeze untouched."""

import json
import math
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities
from .. import board_preparation, board_protocol, preparation
from ..board_analysis import BOUNDARY, single
from ..spine_resident import preparation as shared_freeze
from . import inputs

FROZEN = "SPINE_FULLPR_HOST_AND_FIXED_ARTIFACT_PINNED_NOT_BOARD"
PASS = "SPINE_FULLPR_RESIDENT_CONVERGENCE_PASS_NOT_PAIRED_OR_STAGE_CALIBRATION"


def freeze(source, build, artifacts, output):
    output.mkdir(parents=True, exist_ok=False)
    # The retained three-algorithm driver tests are a host regression gate,
    # not a claim that their FPGA matrix validates the new FullPR path.
    base = shared_freeze.freeze(source, build, artifacts, output / "host-regression-freeze")
    name = "full_pagerank"
    test = build / (name + ".test.log")
    if "FULLPR_RESIDENT_HOST_TEST_PASS scope=offboard_driver_only" not in test.read_text().splitlines():
        raise ValueError("isolated FullPR injected-runtime test required")
    required = {"host_full_pagerank_resident.hpp", "host_full_pagerank_resident_test.cpp"}
    if not required <= {Path(pin["path"]).name for pin in base["pins"]}:
        raise ValueError("FullPR driver and injected test source pins required")
    binary = build / (name + ".host")
    compile_log = build / (name + ".compile.log")
    command = next((line for line in compile_log.read_text().splitlines()
                    if line.startswith("g++ ") and "host_partitioned_algorithms_smoke.cpp" in line), "")
    if not all(flag in command.split() for flag in (
            "-O3", "-DMAX_N=16777216", "-DVS_PARTITION_SIZE=1048576", "-DMAX_SORT_N=131072",
            "-DEDGE_BUF_CHUNK_SIZE=33554432", "-DSPINE_ALGORITHM_KIND=3",
            "-DSPINE_ENFORCE_PAPER_ALIGNMENT_CONTRACT=1", "-lxilinxopencl",
            "-Wl,-rpath,/opt/xilinx/xrt/lib")) or " -o " + str(binary) + " " not in command:
        raise ValueError("full-capacity Release FullPR compile command required")
    deps = build / (name + ".d")
    dep_pins = dependency_identities(deps, source / "tests/test_integration")
    candidate = artifacts / "fullpr/xclbin/spine_partitioned_split_e2e.fullpr.hw.xclbin"
    timing_path = artifacts / "fullpr/reports/link/imp/impl_1_hw_bb_locked_timing_summary_routed.rpt"
    timing = bitstream.parse_routed_timing(timing_path)
    topology = bitstream.normalized_topology(bitstream._dump(candidate, output / "topology"))
    kernels = {name.split(":")[0] for name, _ in topology["kernels"]}
    if ("DATA", "DATA_CLK", 150) not in topology["clock"] or not {
            "spine_partconv_compute_kernel", "spine_partconv_rdmaint_kernel"} <= kernels:
        raise ValueError("fixed 150-MHz FullPR reader/compute artifact required")
    candidate_pin = preparation.identity(candidate)
    pins = board_preparation.stamp_pins([*base["pins"], *dep_pins, candidate_pin,
            *[preparation.identity(path) for path in (test, binary, compile_log, deps, timing_path)],
            *[preparation.identity(path) for path in (output / "topology").iterdir()]])
    report = {"status": FROZEN, "host_revision": base["host_revision"], "pins": pins,
              "binary": str(binary), "candidate": candidate_pin, "timing": timing, "topology": topology,
              "board_programmed": False, "stage_calibration": False}
    atomic_write_json(output / "results.json", report)
    return report


def prepare(preflight, admission, algorithm):
    if algorithm != inputs.ALGORITHM:
        raise ValueError("FullPR-only protocol")
    cohort, pins = inputs.load(preflight)
    frozen = json.loads(admission.read_text())
    if frozen.get("status") != FROZEN or frozen.get("board_programmed") is not False or \
            frozen.get("stage_calibration") is not False:
        raise ValueError("isolated FullPR host/artifact freeze required")
    pins = board_preparation.stamp_pins([*pins, *frozen["pins"], preparation.identity(admission)])
    return {**frozen, "algorithm": algorithm, "pins": pins,
            "rows": cohort["rows"], "smoke": cohort["smoke"]}


def analyze(row, stdout, stderr, *, bdf):
    notices = stderr.splitlines()
    if notices not in ([], ["Using XCL_DEVICE_INDEX=0"], ["Using XCL_DEVICE_INDEX=1"]):
        raise ValueError("unexpected FullPR runtime diagnostic")
    lines = stdout.splitlines()
    if single(lines, "SPINE_DEVICE") != {"bdf": bdf}:
        raise ValueError("FullPR leased board mismatch")
    result = single(lines, "SPINE_RESIDENT_BENCHMARK_PASS")
    integers = {"algorithm": 3, "vertices": row["vertices"], "source": row["source"],
                "logical_updates": row["updates"], "physical_updates": row["updates"],
                "host_correction_included": 0, "warm_sweeps": 128, "warm_residual_checked": 1}
    if any(int(result[key]) != value for key, value in integers.items()):
        raise ValueError("FullPR workload or old-converged initialization differs")
    expected = {"boundary": BOUNDARY, "final_validation": "outside_wall",
                "full_state_readback": "each_round", "convergence": "global_l1",
                "degree_preparation": "host_inside_wall", "case": row["graph"] + ":final"}
    if any(result.get(key) != value for key, value in expected.items()) or float(result["epsilon"]) != 1e-6:
        raise ValueError("FullPR convergence, degree handoff or continuous boundary differs")
    wall, delta = float(result["wall_ms"]), float(result["final_l1_error"])
    rounds = int(result["iterations"])
    if not math.isfinite(wall) or wall <= 0 or not math.isfinite(delta) or not 0 <= delta <= 1e-6 or \
            not 1 <= rounds <= 256 or (row["dataset"] == "SMOKE" and rounds <= 3):
        raise ValueError("finite converged FullPR required; smoke must exceed the old three-round limit")
    ledgers = [line for line in lines if line.startswith("KERNEL_PAIR_RESULT ")]
    if len(ledgers) != rounds:
        raise ValueError("one clean FullPR ledger per completed sweep required")
    for index, line in enumerate(ledgers):
        ledger = single([line], "KERNEL_PAIR_RESULT")
        if ledger["algorithm"] != "fullpr_resident" or int(ledger["iteration"]) != index or \
                any(int(ledger[key]) for key in ("overflow", "task_error", "source_status", "owner_status")):
            raise ValueError("FullPR per-sweep device ledger failed")
    return {"status": "PASS", "dataset": row["dataset"], "algorithm": inputs.ALGORITHM,
            "boundary": BOUNDARY, "resident_wall_ms": wall, "iterations": rounds,
            "last_iteration_l1_delta": delta, "result": result, "ledgers": ledgers,
            "runtime_notices": notices,
            "limits": ["fixed FullPR bitstream, not ten-stage calibration",
                       "degree handoff and full-state readback each round are inside wall",
                       "three complete inputs, not the eight-graph differential matrix",
                       "not a paired speedup or original-publication match"]}


def environment(device, bdf):
    return {"XCL_DEVICE_INDEX": str(device), "SPINE_EXPECT_BDF": bdf}


def experiment():
    return board_protocol.Experiment("fixed_spine_fullpr_resident", BOUNDARY, PASS,
        prepare, shared_freeze.command, analyze, environment, False)
