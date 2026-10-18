"""Freeze host-test dependencies and fixed artifacts before exclusive board work."""

import json
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities
from .. import analysis as offline_analysis, board_preparation, preparation, recheck

HOST_NAMES = {"weighted_sssp": "weighted_sssp", "connected_components": "connected_components",
              "residual_pagerank": "thresholded_residual_pagerank"}
ARTIFACTS = {"weighted_sssp": ("sssp", ""), "connected_components": ("cc", ".cc"),
             "residual_pagerank": ("respr", ".respr")}
FROZEN = "SPINE_RESIDENT_HOST_AND_FIXED_ARTIFACTS_PINNED_NOT_BOARD"


def freeze(spine, build, artifacts, output):
    output.mkdir(parents=True, exist_ok=False)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=spine, text=True).strip()
    if subprocess.check_output(["git", "diff", "HEAD", "--name-only"], cwd=spine).strip():
        raise ValueError("tracked Spine source must be committed before admission")
    if (build / "source-commit.txt").read_text().strip() != revision or \
            (build / "source.patch").read_text().strip() or \
            (build / "decision.txt").read_text().strip() != "RESIDENT_BENCHMARK_HOST_TESTS_PASS scope=offboard_not_fpga":
        raise ValueError("successful offboard tests at the same clean committed revision required")
    pins = [preparation.identity(build / name) for name in (
        "source-commit.txt", "source.patch", "source-sha256.txt", "compiler.txt", "decision.txt")]
    source_pins = []
    for line in (build / "source-sha256.txt").read_text().splitlines():
        digest, path = line.split(maxsplit=1)
        actual = preparation.identity(Path(path))
        if actual["sha256"] != digest:
            raise ValueError("host test source changed")
        source_pins.append(actual)
    required = {"host_partitioned_algorithms_smoke.cpp", "host_resident_benchmark.hpp", "host_split.hpp"}
    if not required <= {Path(pin["path"]).name for pin in source_pins}:
        raise ValueError("complete host boundary source pins required")
    pins += source_pins
    plans = {}
    for index, algorithm in enumerate(preparation.ALGORITHMS):
        name = HOST_NAMES[algorithm]
        binary = build / (name + ".host")
        test = build / (name + ".test.log")
        if f"RESIDENT_BENCHMARK_HOST_TEST_PASS algorithm={index} scope=offboard_driver_only" not in test.read_text().splitlines():
            raise ValueError("offboard driver test marker missing")
        compile_log = build / (name + ".compile.log")
        command = next((line for line in compile_log.read_text().splitlines() if
                        line.startswith("g++ ") and "host_partitioned_algorithms_smoke.cpp" in line), "")
        if not all(flag in command.split() for flag in (
                "-O3", "-DMAX_N=16777216", "-DVS_PARTITION_SIZE=1048576",
                "-DMAX_SORT_N=131072", "-DEDGE_BUF_CHUNK_SIZE=33554432",
                f"-DSPINE_ALGORITHM_KIND={index}", "-DSPINE_ENFORCE_PAPER_ALIGNMENT_CONTRACT=1",
                "-lxilinxopencl", "-Wl,-rpath,/opt/xilinx/xrt/lib")) or \
                " -o " + str(binary) + " " not in command:
            raise ValueError("complete full-capacity Release compile command required")
        deps = build / (name + ".d")
        dependency_pins = dependency_identities(deps, spine / "tests/test_integration")
        # dependency_identities uses a lean identity; stamp all dependencies so
        # the shared executor can detect between-step changes as well as hashes.
        pins += board_preparation.stamp_pins(dependency_pins)
        directory, suffix = ARTIFACTS[algorithm]
        candidate = artifacts / directory / "xclbin" / f"spine_partitioned_split_e2e{suffix}.hw.xclbin"
        timing_path = artifacts / directory / "reports/link/imp/impl_1_hw_bb_locked_timing_summary_routed.rpt"
        timing = bitstream.parse_routed_timing(timing_path)
        topology = bitstream.normalized_topology(bitstream._dump(candidate, output / (algorithm + "-topology")))
        kernels = {name.split(":")[0] for name, _ in topology["kernels"]}
        if ("DATA", "DATA_CLK", 150) not in topology["clock"] or not {
                "spine_partconv_compute_kernel", "spine_partconv_rdmaint_kernel"} <= kernels:
            raise ValueError("fixed 150-MHz reader/compute Spine artifact required")
        candidate_pin = preparation.identity(candidate)
        pins += [candidate_pin, preparation.identity(timing_path), preparation.identity(deps),
                 preparation.identity(compile_log), preparation.identity(test), preparation.identity(binary)]
        pins += [preparation.identity(path) for path in (output / (algorithm + "-topology")).iterdir()]
        plans[algorithm] = {"binary": str(binary), "candidate": candidate_pin,
                            "timing": timing, "topology": topology}
    unique = board_preparation.stamp_pins(pins)
    report = {"status": FROZEN, "host_revision": revision, "plans": plans, "pins": unique,
              "board_programmed": False, "stage_calibration": False}
    atomic_write_json(output / "results.json", report)
    return report


def prepare(preflight, admission, algorithm):
    if algorithm not in preparation.ALGORITHMS:
        raise ValueError("fixed Spine study covers SSSP/CC/ResPR only")
    offline_path = preflight / "results.json"
    offline = json.loads(offline_path.read_text())
    if offline.get("status") != offline_analysis.PASS:
        raise ValueError("complete offline matrix required")
    recheck.recheck(offline, lambda name: (preflight / name).read_text())
    frozen = json.loads(admission.read_text())
    if frozen.get("status") != FROZEN or frozen.get("board_programmed") is not False or \
            frozen.get("stage_calibration") is not False:
        raise ValueError("Spine host and fixed-artifact freeze required")
    plan = frozen["plans"][algorithm]
    pins = board_preparation.stamp_pins([*offline["pins"], *frozen["pins"],
                 preparation.identity(offline_path), preparation.identity(admission)])
    rows = [row for row in offline["matrix"] if row["algorithm"] == algorithm]
    if [row["dataset"] for row in rows] != list(preparation.DATASETS):
        raise ValueError("exact full eight-graph matrix required")
    smoke = next(row for row in recheck.smoke_rows(preflight) if row["algorithm"] == algorithm)
    return {**plan, "pins": pins, "algorithm": algorithm, "host_revision": frozen["host_revision"],
            "rows": rows, "smoke": smoke,
            "smokes": [{**smoke, "dataset": "SMOKE_LEGACY", "legacy": True}, smoke]}


def command(plan, row, result):
    return [plan["binary"], plan["candidate"]["path"], "--dynamic-graph", row["graph"],
            "--source", str(row["source"]), *([] if row.get("legacy") else ["--resident-benchmark"])]
