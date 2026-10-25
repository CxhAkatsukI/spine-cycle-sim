"""Probe the current routed G stage on a declared, non-publication AU batch."""

import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess

from .regraph import identity, lease, save
from ..shared_workloads import load_slice


def prepare(graph_path, updates_path, output):
    graph, updates = load_slice(graph_path), load_slice(updates_path)
    pairs = {(edge.src, edge.dst) for edge in graph.records}
    inserted = {(edge.src, edge.dst) for edge in updates.records}
    if (graph.vertices != updates.vertices or len(pairs) != len(graph.records)
            or len(inserted) != len(updates.records) or pairs & inserted
            or any(edge.diff != 1 for edge in (*graph.records, *updates.records))):
        raise ValueError("unique initial edges and unique, absent, positive insertions required")
    with output.open("x") as stream:
        stream.write(f"{graph.vertices} {len(graph.records)} {len(updates.records)}\n")
        for edge in graph.records:
            stream.write(f"{edge.src} {edge.dst} {edge.weight}\n")
        for edge in updates.records:
            stream.write(f"{edge.src} {edge.dst} {edge.weight} 1\n")
    return {"vertices": graph.vertices, "base_edges": len(graph.records),
            "successful_insertions_expected": len(updates.records),
            "original_ids_preserved": True, "reciprocal_expansion": False,
            "initial": identity(graph_path), "updates": identity(updates_path),
            "input": identity(output)}


def fields(line):
    return dict(item.split("=", 1) for item in line.split()[1:] if "=" in item)


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "publication_match": False,
              "scope": "current weighted sharded G update-only; AU original-ID insertion batch, not GraSU's converted temporal trace",
              "host": identity(args.host), "xclbin": identity(args.xclbin),
              "runner": identity(__file__), "rows": [], "errors": [],
              "clock_mhz": 150, "device_index": args.device, "expected_bdf": args.bdf,
              "boundary": "nine update-CU event envelope over all destination shards, including inter-shard gaps; excludes initial preparation/DMA and final validation readback",
              "affinity": "124,125", "repeats": 3, "same_process_repeats": 1}
    try:
        report["workload"] = prepare(args.graph, args.updates, output / "input.graph")
        with lease(args.device, args.bdf) as (render, fd):
            for repeat in range(3):
                if subprocess.run(["fuser", str(render)], capture_output=True).returncode != 1:
                    raise RuntimeError("board is in use or its idle state cannot be established")
                available = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines()
                                     if line.startswith("MemAvailable:"))) * 1024
                if available < 24 * 2**30:
                    raise MemoryError("less than 24 GiB available; no launch")
                command = ["/usr/bin/taskset", "-c", "124,125", str(args.host), "--update-only",
                           str(args.xclbin), str(output / "input.graph"), str(output / f"r{repeat}.result.txt"), "0", "256"]
                report.update(status=f"RUNNING_r{repeat}", current_command=command)
                save(output / "results.json", report)
                environment = dict(os.environ, XILINX_XRT="/opt/xilinx/xrt", XCL_DEVICE_INDEX=str(args.device),
                                   GRASU_REGRAPH_EXPECT_BDF=args.bdf, GRASU_UPDATE_REPEATS="1", MALLOC_ARENA_MAX="2")
                with (output / f"r{repeat}.stdout.txt").open("w") as stdout, \
                     (output / f"r{repeat}.stderr.txt").open("w") as stderr:
                    subprocess.run(command, cwd=output, env=environment, pass_fds=(fd,),
                                   stdout=stdout, stderr=stderr, check=True, timeout=240)
                lines = (output / f"r{repeat}.stdout.txt").read_text().splitlines()
                result = [fields(line) for line in lines if line.startswith("GRASU_SHARDED_UPDATE_ONLY_RESULT ")]
                if (len(result) != 1 or result[0].get("status") != "PASS"
                        or result[0].get("pma_mismatches") != "0"
                        or int(result[0].get("checked_words", "0")) <= 0
                        or f"GRASU_REGRAPH_DEVICE bdf={args.bdf}" not in lines):
                    raise ValueError("PMA update correctness or selected board check failed")
                duration = float(result[0]["update_ms"])
                if not duration > 0:
                    raise ValueError("positive event timing required")
                report["rows"].append({"repeat": repeat, "result": result[0], "update_ms": duration,
                    "mupdates_per_second": report["workload"]["successful_insertions_expected"] / duration / 1000})
                save(output / "results.json", report)
                print(f"G r{repeat}: correctness PASS; update_ms={duration}", flush=True)
        report["summary"] = {"median_update_ms": statistics.median(row["update_ms"] for row in report["rows"]),
            "median_mupdates_per_second": statistics.median(row["mupdates_per_second"] for row in report["rows"]),
            "minimum_update_ms": min(row["update_ms"] for row in report["rows"]),
            "maximum_update_ms": max(row["update_ms"] for row in report["rows"])}
        report["status"] = "CORRECTNESS_PASS_DIAGNOSTIC_NOT_PUBLICATION_MATCH"
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
    print(json.dumps(run(parser.parse_args())["summary"], indent=2))
