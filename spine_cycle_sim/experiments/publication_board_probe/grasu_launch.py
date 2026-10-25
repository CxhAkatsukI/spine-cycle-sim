"""Diagnose G startup using one bitstream and PMA-restored repetitions."""

import argparse
import json
import math
import os
from pathlib import Path
import statistics
import subprocess

from .grasu import fields, prepare
from .regraph import identity, lease, save


def inspect(lines, bdf, repetitions=4):
    if f"GRASU_REGRAPH_DEVICE bdf={bdf}" not in lines:
        raise ValueError("selected board identity differs")
    configs = [fields(line) for line in lines
               if line.startswith("GRASU_SHARDED_UPDATE_REPEAT_CONFIG ")]
    rows = [fields(line) for line in lines
            if line.startswith("GRASU_SHARDED_UPDATE_REPEAT ")]
    results = [fields(line) for line in lines
               if line.startswith("GRASU_SHARDED_UPDATE_ONLY_RESULT ")]
    if (len(configs) != 1 or configs[0].get("repeats") != str(repetitions)
            or configs[0].get("restore_pma_between_repeats") != "1"
            or len(rows) != repetitions or len(results) != 1):
        raise ValueError("complete restored-repetition matrix required")
    result = results[0]
    if (result.get("status") != "PASS" or result.get("pma_mismatches") != "0"
            or int(result.get("checked_words", "0")) <= 0
            or result.get("repeats") != str(repetitions)):
        raise ValueError("final-repeat PMA correctness gate failed")
    for index, row in enumerate(rows):
        duration = float(row["update_ms"])
        if (row.get("repeat") != str(index)
                or row.get("final") != str(int(index == repetitions - 1))
                or not math.isfinite(duration) or duration <= 0):
            raise ValueError("ordered, positive repetition timings required")
    if not math.isclose(float(rows[-1]["update_ms"]), float(result["update_ms"]), abs_tol=1e-5):
        raise ValueError("final result and repeat timer disagree")
    timings = [float(row["update_ms"]) for row in rows]
    return {"cold_ms": timings[0], "warm_median_ms": statistics.median(timings[1:]),
            "repeat_ms": timings, "final_result": result,
            "correctness_scope": "last repeat checked; earlier repeats diagnostic only"}


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "publication_match": False,
              "host": identity(args.host), "xclbin": identity(args.xclbin),
              "runner": identity(__file__), "rows": [], "errors": [],
              "expected_bdf": args.bdf, "device_index": args.device,
              "affinity": "124,125", "clock_mhz": 150,
              "processes_per_mode": 1, "repetitions_per_process": 4,
              "boundary": "nine-CU event envelope including inter-shard gaps; excludes explicit initial DMA, PMA restoration and final readback; first-use implicit migration may remain inside",
              "purpose": "startup diagnosis, not steady-state publication reproduction"}
    try:
        report["workload"] = prepare(args.graph, args.updates, output / "input.graph")
        with lease(args.device, args.bdf) as (render, fd):
            for mode in ("baseline", "premigrate"):
                if subprocess.run(["fuser", str(render)], capture_output=True).returncode != 1:
                    raise RuntimeError("board idle state cannot be established")
                available = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                                     if line.startswith("MemAvailable:"))) * 1024
                if available < 24 * 2**30:
                    raise MemoryError("less than 24 GiB available; no launch")
                command = ["/usr/bin/taskset", "-c", "124,125", str(args.host), "--update-only",
                           str(args.xclbin), str(output / "input.graph"), str(output / f"{mode}.result.txt"), "0", "256"]
                report.update(status="RUNNING_" + mode, current_command=command)
                save(output / "results.json", report)
                environment = dict(os.environ, XILINX_XRT="/opt/xilinx/xrt", XCL_DEVICE_INDEX=str(args.device),
                                   GRASU_REGRAPH_EXPECT_BDF=args.bdf, GRASU_UPDATE_REPEATS="4",
                                   GRASU_SHARDED_PREMIGRATE_INPUTS=str(int(mode == "premigrate")),
                                   MALLOC_ARENA_MAX="2")
                with (output / f"{mode}.stdout.txt").open("w") as stdout, \
                     (output / f"{mode}.stderr.txt").open("w") as stderr:
                    subprocess.run(command, cwd=output, env=environment, pass_fds=(fd,),
                                   stdout=stdout, stderr=stderr, timeout=240, check=True)
                analysis = inspect((output / f"{mode}.stdout.txt").read_text().splitlines(), args.bdf)
                analysis["warm_mupdates_per_second"] = (report["workload"]["successful_insertions_expected"]
                                                        / analysis["warm_median_ms"] / 1000)
                report["rows"].append({"mode": mode, "analysis": analysis})
                save(output / "results.json", report)
                print(mode + ": " + json.dumps(analysis), flush=True)
        report["status"] = "G_STARTUP_DIAGNOSTIC_PASS_NOT_PUBLICATION_MATCH"
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save(output / "results.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("host", "xclbin", "graph", "updates", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--device", required=True, type=int, choices=(0, 1))
    parser.add_argument("--bdf", required=True)
    run(parser.parse_args())
