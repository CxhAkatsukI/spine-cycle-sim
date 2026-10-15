"""Run a bounded, memory-admitted production cache wrapper RTL/export check."""

import argparse
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from ..search_pipeline.admission import wait
from ..search_pipeline.synthesis import unchanged
from .binding_analysis import analyze, status
from .binding_preparation import prepare, tcl


def run(output, basis, production, reference, previous_unit, route_unit, maximum_wait, background_memory_gib):
    result = {"source": prepare(output, basis, production, reference), "status": "PREPARED", "errors": [],
        "hardware_timing_admitted": False, "production_baseline_admitted": False,
        "publication_match_admitted": False,
        "claim": "complete_hot_half_production_cache_wrapper_RTL_ABI_not_complete_G_or_board_timing",
        "resources": {"memory_max_gib": 8, "memory_high_gib": 7, "reserve_gib": 24,
                      "swap_max_bytes": 0, "cpu_affinity": [125], "timeout_seconds": 1800}}
    attempt = output / "attempt"
    attempt.mkdir()
    script = attempt / "run.tcl"
    script.write_text(tcl(), encoding="ascii")
    result["script"] = {"path": str(script), "sha256": sha256_file(script)}
    command = ["systemd-run", "--user", "--scope", "--quiet", "--property=MemoryHigh=7G",
        "--property=MemoryMax=8G", "--property=MemorySwapMax=0", "env", "MALLOC_ARENA_MAX=2",
        "taskset", "-c", "125", "/data/yxx/tools/xilinx/Vitis_HLS/2024.1/bin/vitis_hls", "-f", str(script)]
    result["command"] = command
    report = output / "results.json"
    save = lambda: atomic_write_json(report, result)
    save()
    try:
        reserve = wait(result, save, previous_unit, route_unit, maximum_wait, background_memory_gib)
        unchanged(result["source"] + [result["script"]])
        result["status"] = "RUNNING_CACHE_WRAPPER_HLS_RTL_ABI"
        save()
        result["execution"] = run_bounded(command, attempt, attempt / "execution", timeout=1800,
                                           memory_gib=8, reserve_gib=reserve)
        result["analysis"] = analyze(attempt, output / "reference")
        unchanged(result["source"] + [result["script"]])
        if result["execution"]["exit_code"] or result["execution"]["timed_out"]:
            raise ValueError("cache wrapper HLS/RTL/export failed; partial reports retained")
        result["status"] = status(result["analysis"])
        if result["status"] == "FAILED_RETAINED":
            raise ValueError("cache wrapper RTL, ABI or synthesis gate failed")
    except Exception as error:
        result["errors"].append(repr(error))
        result["status"] = "FAILED_RETAINED"
        save()
        raise
    save()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "basis", "production", "reference"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--previous-unit", required=True)
    parser.add_argument("--route-unit", required=True)
    parser.add_argument("--maximum-wait", type=float, default=3600)
    parser.add_argument("--background-memory-gib", type=int, default=0)
    args = parser.parse_args()
    run(*(getattr(args, name).resolve() for name in ("output", "basis", "production", "reference")),
        args.previous_unit, args.route_unit, args.maximum_wait, args.background_memory_gib)
