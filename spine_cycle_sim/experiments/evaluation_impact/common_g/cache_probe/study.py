"""Run declared full-depth cache controls sequentially with bounded resources."""

import argparse
from pathlib import Path
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes, run_bounded
from .analysis import analyze
from .preparation import ARMS, FULL_ARM, FULL_ARMS, prepare, tcl


def wait_for_memory(record, save, *, maximum_wait=600):
    started = time.monotonic()
    record["memory_admission"] = {"required_bytes": 30 * 1024**3,
                                  "maximum_wait_seconds": maximum_wait, "samples": []}
    admission = record["memory_admission"]
    while True:
        available, elapsed = available_memory_bytes(), time.monotonic() - started
        admission["samples"].append({"elapsed_seconds": elapsed, "available_bytes": available})
        admission["admitted"] = available >= admission["required_bytes"]
        save()
        if admission["admitted"]:
            return
        if elapsed >= maximum_wait:
            raise RuntimeError("memory admission wait expired; no tool launched")
        time.sleep(min(5, maximum_wait - elapsed))


def run(output: Path, upstream: Path, full_original=False, full_comparison=False):
    full = full_original or full_comparison
    arms = FULL_ARMS if full_comparison else (FULL_ARM,) if full_original else ARMS
    pins = prepare(output, upstream)
    result = {"source": pins, "arms": [], "errors": [],
        "status": "RUNNING", "hardware_timing_admitted": False,
        "production_baseline_admitted": False, "publication_match_admitted": False,
        "scope": "sixteen_bank" if full else "isolated_bank",
        "full_stimuli_version": 2 if full else None,
        "declared_arms": list(arms),
        "resources": {"timeout_seconds_per_arm": 900, "memory_max_gib": 6,
                      "memory_high_gib": 5, "reserve_gib": 24, "swap_max_bytes": 0,
                      "cpu_affinity": [127], "part": "xcu55c-fsvh2892-2L-e",
                      "target_clock_ns": 5}}
    atomic_write_json(output / "results.json", result)
    for arm in arms:
        folder = output / arm
        folder.mkdir()
        script = folder / "run.tcl"
        script.write_text(tcl(arm), encoding="ascii")
        entry = {"arm": arm, "script_sha256": sha256_file(script)}
        result["arms"].append(entry)
        try:
            wait_for_memory(entry, lambda: atomic_write_json(output / "results.json", result))
            entry["execution"] = run_bounded([
                "systemd-run", "--user", "--scope", "--quiet",
                "--property=MemoryHigh=5G", "--property=MemoryMax=6G",
                "--property=MemorySwapMax=0", "taskset", "-c", "127",
                "/data/yxx/tools/xilinx/Vitis_HLS/2024.1/bin/vitis_hls", "-f", str(script)],
                folder, folder / "execution", timeout=900, memory_gib=6, reserve_gib=24)
            if entry["execution"]["exit_code"] or entry["execution"]["timed_out"]:
                raise ValueError("cache-bank HLS attempt failed; retain raw logs")
            entry["analysis"] = analyze(folder, full=full, full_extended=full)
        except Exception as error:
            entry["error"] = repr(error)
            result["errors"].append({"arm": arm, "error": repr(error)})
        atomic_write_json(output / "results.json", result)
    if any(sha256_file(Path(pin["path"])) != pin["sha256"] for pin in pins):
        result["errors"].append({"error": "frozen source changed"})
    if result["errors"]:
        result["status"] = "FAILED_RETAINED"
    elif full:
        result["status"] = "FULL_CACHE_RTL_PASS_WITH_SEPARATE_CLOCK_GATES"
    else:
        result["status"] = "ISOLATED_BANK_RTL_PASS_WITH_SEPARATE_CLOCK_GATES"
    atomic_write_json(output / "results.json", result)
    if result["errors"]:
        raise ValueError("one or more declared cache-bank arms failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full-original", action="store_true",
                        help="audit the unchanged sixteen-bank kernel, not an isolated bank")
    mode.add_argument("--full-comparison", action="store_true",
                      help="compare full original and registered-candidate caches")
    args = parser.parse_args()
    run(args.output.resolve(), args.upstream.resolve(), args.full_original, args.full_comparison)
