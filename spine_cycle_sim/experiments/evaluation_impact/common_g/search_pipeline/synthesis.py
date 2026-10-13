"""Run isolated search HLS/RTL after source controls and safe serial admission."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .admission import wait
from .analysis import analyze
from .preparation import tcl
from .rtl_analysis import analyze_rtl


def unchanged(pins):
    if any(sha256_file(Path(pin["path"])) != pin["sha256"] for pin in pins):
        raise ValueError("frozen control source changed")


def run(output, basis, previous_unit, route_unit, maximum_wait):
    basis_path = basis / "results.json"
    controls = json.loads(basis_path.read_text())
    if controls.get("status") != "FINITE_HLS_SOURCE_PASS_NOT_RTL_TIMING":
        raise ValueError("complete finite source controls required before HLS")
    unchanged(controls["source"])
    unchanged(controls["dependencies"])
    previous = Path(controls["previous"]["path"])
    if sha256_file(previous) != controls["previous"]["sha256"]:
        raise ValueError("metadata-buffer reference changed")
    analyze(controls, json.loads(previous.read_text()))
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(basis / "source", output / "source")
    pins = [{"path": str(path), "sha256": sha256_file(path)}
            for path in sorted((output / "source").rglob("*")) if path.is_file()]
    attempt = output / "attempt"
    attempt.mkdir()
    script = attempt / "run.tcl"
    script.write_text(tcl(), encoding="ascii")
    command = ["systemd-run", "--user", "--scope", "--quiet", "--property=MemoryHigh=7G",
        "--property=MemoryMax=8G", "--property=MemorySwapMax=0", "env", "MALLOC_ARENA_MAX=2",
        "taskset", "-c", "127", "/data/yxx/tools/xilinx/Vitis_HLS/2024.1/bin/vitis_hls", "-f", str(script)]
    result = {"status": "PREPARED", "source": pins,
        "basis": {"path": str(basis_path), "sha256": sha256_file(basis_path)},
        "script": {"path": str(script), "sha256": sha256_file(script)}, "command": command,
        "resources": {"memory_max_gib": 8, "memory_high_gib": 7, "reserve_gib": 24,
                      "cpu_affinity": [127], "timeout_seconds": 1800, "swap_max_bytes": 0},
        "hardware_timing_admitted": False, "production_baseline_admitted": False,
        "publication_match_admitted": False,
        "claim": "isolated_search_HLS_RTL_not_whole_G_or_routed_performance"}
    report = output / "results.json"
    save = lambda: atomic_write_json(report, result)
    save()
    try:
        reserve = wait(result, save, previous_unit, route_unit, maximum_wait)
        unchanged(pins)
        result["status"] = "RUNNING_ISOLATED_HLS_RTL"
        save()
        result["execution"] = run_bounded(command, attempt, attempt / "execution", timeout=1800,
                                           memory_gib=8, reserve_gib=reserve)
        unchanged(pins)
        if result["execution"]["exit_code"] or result["execution"]["timed_out"]:
            raise ValueError("isolated search HLS/RTL failed; raw attempt retained")
        result["analysis"] = analyze_rtl(attempt)
        result["status"] = ("ISOLATED_RTL_PASS_TARGET_MET_REQUIRES_INTEGRATION" if
            result["analysis"]["target_5ns_met"] else "ISOLATED_RTL_PASS_CLOCK_GATE_FAILED")
    except Exception as error:
        result.update(status="FAILED_RETAINED", error=repr(error))
        save()
        raise
    save()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--basis", type=Path, required=True)
    parser.add_argument("--previous-unit", required=True)
    parser.add_argument("--route-unit", required=True)
    parser.add_argument("--maximum-wait", type=float, default=43200)
    args = parser.parse_args()
    run(args.output.resolve(), args.basis.resolve(), args.previous_unit, args.route_unit, args.maximum_wait)
