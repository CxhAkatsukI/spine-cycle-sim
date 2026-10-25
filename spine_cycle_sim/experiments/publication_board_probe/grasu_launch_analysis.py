"""Package G startup evidence separately from synthesis-derived fixed costs."""

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from .analysis import compare_rates, update_timeline
from .grasu import fields
from .grasu_launch import inspect
from .regraph import identity, save


def synthesis_loop(path, loop):
    root = ET.parse(path).getroot()
    prefix = "PerformanceEstimates/"
    cycles = int(root.findtext(prefix + "SummaryOfOverallLatency/Best-caseLatency"))
    ii = int(root.findtext(prefix + f"SummaryOfLoopLatency/{loop}/PipelineII"))
    trips = int(root.findtext(prefix + f"SummaryOfLoopLatency/{loop}/TripCount"))
    if min(cycles, ii, trips) <= 0:
        raise ValueError("positive synthesis cycle counts required")
    return {"report": identity(path), "loop": loop, "best_case_cycles": cycles,
            "achieved_ii": ii, "trip_count": trips}


def package(raw, synthesis, output, hls_root, author_cache, paper):
    report = json.loads((raw / "results.json").read_text())
    if (report["status"] != "G_STARTUP_DIAGNOSTIC_PASS_NOT_PUBLICATION_MATCH"
            or report["publication_match"]
            or [row["mode"] for row in report["rows"]] != ["baseline", "premigrate"]):
        raise ValueError("complete two-mode startup diagnostic required")
    rows = []
    for mode in ("baseline", "premigrate"):
        lines = (raw / f"{mode}.stdout.txt").read_text().splitlines()
        result = inspect(lines, report["expected_bdf"])
        result["mode"] = mode
        result["final_timeline"] = update_timeline(lines, result["repeat_ms"][-1])
        rate = report["workload"]["successful_insertions_expected"] / result["warm_median_ms"] / 1000
        result["warm_mupdates_per_second"] = rate
        result["unmatched_paper_rate_ratio"] = compare_rates(rate, 190.77)
        residency = [fields(line) for line in lines if line.startswith("SHARDED_INPUT_RESIDENCY ")]
        if mode == "premigrate":
            if len(residency) != 1 or residency[0].get("policy") != "premigrate":
                raise ValueError("explicit premigration evidence required")
            result["premigration_outside_update_window"] = residency[0]
        rows.append(result)
    loops = [synthesis_loop(synthesis / f"cached_process_Pipeline_{loop}_csynth.xml", loop)
             for loop in ("preload_all", "writeback_all")]
    shards = rows[0]["final_timeline"]["shard_count"]
    if shards != rows[1]["final_timeline"]["shard_count"] or shards != 8:
        raise ValueError("this fixed-layout analysis requires eight shards")
    result = {"schema_version": 1, "publication_match": False,
              "status": "G_STARTUP_AND_FIXED_CACHE_DIAGNOSED_NOT_PUBLICATION_MATCH",
              "raw_report": identity(raw / "results.json"),
              "raw_index": [identity(path) for path in sorted(raw.iterdir())
                            if path.name != "input.graph"],
              "host": report["host"], "xclbin": report["xclbin"],
              "analysis_source": identity(__file__),
              "source_witnesses": [identity(path) for path in (
                  hls_root / "kernels/grasu_complete/cache_bank.hpp",
                  hls_root / "kernels/grasu_complete/cache_pipeline.hpp",
                  hls_root / "kernels/grasu_complete/process_cache.cpp",
                  hls_root / "tools/sharded_k4_native_host.cpp", author_cache, paper)],
              "workload": report["workload"], "clock_mhz": report["clock_mhz"],
              "rows": rows,
              "boundary_correction": "explicit initial DMA excluded; baseline first use may contain implicit migration",
              "fixed_cache": {"evidence_kind": "source footprint and synthesis schedule, not isolated board measurement",
                  "cache_halves": 2, "banks_per_half": 16, "words_per_bank": 8192,
                  "bytes_per_word": 64, "bytes_per_shard_load_and_store": 32 * 2**20,
                  "batch_bytes_eight_shards": shards * 32 * 2**20, "synthesis_loops": loops,
                  "nominal_no_stall_floor_ms": sum(row["best_case_cycles"] for row in loops)
                      * shards / (report["clock_mhz"] * 1000),
                  "overlap": "two cache CUs overlap; sum sequential preload and writeback, not both CUs"},
              "limitations": ["one process per mode; only final repeat has a PMA correctness check",
                  "premigration moves setup cost outside timer; it does not remove setup-inclusive cost",
                  "remaining update work, AXI stalls and backpressure not independently attributed",
                  "not the paper's identical temporal workload, RTL implementation, or platform"]}
    save(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("raw", "synthesis", "output", "hls-root", "author-cache", "paper"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    print(package(args.raw, args.synthesis, args.output, args.hls_root,
                  args.author_cache, args.paper)["status"])
