"""Host-only, oracle-checked launch controls using unchanged original-R hardware.

Run this file with PYTHONPATH set to the frozen original-R worktree. No FPGA
source, input state, kernel arithmetic, task mapping or timer is subtracted.
"""

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess

if __package__:
    from .regraph import identity, lease, save
else:
    from regraph import identity, lease, save


def summarize(rows):
    summaries = []
    for mode in ("baseline", "prebound", "author_order"):
        selected = [row for row in rows if row["mode"] == mode and row["repeat"] > 0]
        if len(selected) != 3 or {row["repeat"] for row in selected} != {1, 2, 3}:
            raise ValueError("three warm repeats required for every launch mode")
        summary = {"mode": mode, "repeats": 3, **{
            metric: statistics.median(row[metric] for row in selected)
            for metric in ("event_span_ms", "resident_wall_ms", "first_wave_start_spread_ms", "gteps")}}
        if mode == "author_order":
            summary["post_enqueue_wait_ms"] = statistics.median(row["post_enqueue_wait_ms"] for row in selected)
        summaries.append(summary)
    return summaries


def run(args):
    from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import runtime
    from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution.analysis import event_window
    from spine_cycle_sim.experiments.sharded_k4_stages.board import require_idle_board

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    job = json.loads(args.manifest.read_text())
    case = next(case for case in job["cases"] if case["graph"] == "amazon" and case["binding"] == args.binding)
    report = {"status": "PREPARING", "publication_match": False, "rows": [], "errors": [],
              "runner": identity(__file__), "manifest": identity(args.manifest), "case": case,
              "scope": "same resident static PR superstep; three interleaved warm repeats per launch mode",
              "host_wall_includes": "argument binding, task-handle creation, enqueue and completion",
              "device_window": "earliest CU start to latest CU end, with no time subtraction"}
    save(output / "results.json", report)
    try:
        available = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                             if line.startswith("MemAvailable:"))) * 1024
        if available < 24 * 2**30:
            raise MemoryError("24 GiB available-memory reserve required")
        frozen = args.frozen.resolve()
        report["frozen_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=frozen, text=True).strip()
        headers = frozen / "cpp/tests/original_regraph/hardware"
        report["headers"] = [identity(path) for path in sorted(headers.glob("*.hpp"))]
        source = Path(__file__).with_name("launch_control.cpp")
        host = output / "launch_control"
        command = ["/usr/bin/x86_64-linux-gnu-g++-15", "-std=c++20", "-O2", "-DNDEBUG", "-Wall",
                   "-Wextra", "-Wpedantic", "-Werror", "-I/opt/xilinx/xrt/include", "-I" + str(headers),
                   str(source), "-o", str(host), "/opt/xilinx/xrt/lib/libxilinxopencl.so", "-Wl,-rpath,/opt/xilinx/xrt/lib"]
        report["compile"] = command
        report["source"] = identity(source)
        with (output / "compile.stdout.txt").open("w") as stdout, (output / "compile.stderr.txt").open("w") as stderr:
            subprocess.run(command, stdout=stdout, stderr=stderr, timeout=90, check=True)
        report["host"] = identity(host)
        if identity(job["xclbin"]["path"])["sha256"] != job["xclbin"]["sha256"]:
            raise ValueError("frozen bitstream changed")
        report["xclbin"] = identity(job["xclbin"]["path"])
        with lease(args.device, args.bdf) as (render, fd):
            require_idle_board(render)
            runtime.require_clean_environment(host, output)
            captured = runtime.capture(host, render, output / "runtime")
            if captured["device"]["bdf"] != args.bdf:
                raise ValueError("runtime BDF differs")
            report["runtime"] = captured
            report["status"] = "RUNNING"
            save(output / "results.json", report)
            command = ["/usr/bin/taskset", "-c", "124,125", str(host), case["input"], job["configuration"],
                       args.binding, str(output / "board"), job["xclbin"]["path"], str(args.device)]
            report["command"] = command
            with (output / "board.stdout.txt").open("w") as stdout, (output / "board.stderr.txt").open("w") as stderr:
                subprocess.run(command, env=dict(os.environ, ORIGINAL_R_LEASE_FD=str(fd),
                    ORIGINAL_R_EXPECT_BDF=args.bdf, MALLOC_ARENA_MAX="2"), pass_fds=(fd,),
                    stdout=stdout, stderr=stderr, timeout=180, check=True)
            runtime.unchanged(captured, render)
        for directory in sorted((output / "board").iterdir()):
            mode, repeat = directory.name.rsplit("_r", 1)
            timing = json.loads((directory / "timing.json").read_text())
            pins = [identity(directory / "expected.u32le")]
            pins += [identity(directory / f"replica{lane}.u32le")
                     for lane in range(case["offline"]["little"] + case["offline"]["big"])]
            if any(pin["sha256"] != case["expected"]["expected_sha256"] for pin in pins):
                raise ValueError("independent oracle mismatch, including output padding and guards")
            busy, span = event_window(timing["events"])
            if (busy, span) != (timing["event_union_ns"], timing["event_span_ns"]):
                raise ValueError("event windows do not conserve")
            if span > timing["resident_wall_ms"] * 1e6:
                raise ValueError("device window exceeds host window")
            first = {}
            for event in timing["events"]:
                if event["role"] in ("little", "big"):
                    first.setdefault(event["lane"], event["start_ns"])
            report["rows"].append({"mode": mode, "repeat": int(repeat), **timing,
                "event_span_ms": span / 1e6, "gteps": case["offline"]["logical_edges"] / span,
                "first_wave_start_spread_ms": (max(first.values()) - min(first.values())) / 1e6,
                "independent_oracle_pass": True, "pins": pins})
        if len(report["rows"]) != 10:
            raise ValueError("cold baseline plus nine warm controls required")
        report["summaries"] = summarize(report["rows"])
        report["status"] = "HOST_LAUNCH_DIAGNOSTIC_PASS_NOT_PUBLICATION_MATCH"
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save(output / "results.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--frozen", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--binding", choices=("author_initial", "csr_degree"), default="author_initial")
    parser.add_argument("--device", required=True, type=int, choices=(0, 1))
    parser.add_argument("--bdf", required=True)
    print(json.dumps(run(parser.parse_args())["summaries"], indent=2))
