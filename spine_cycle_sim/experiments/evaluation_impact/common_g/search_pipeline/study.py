"""Execute every declared finite-channel HLS source control with fixed bounds."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from .analysis import analyze, parse
from .preparation import CASES, MODES, command, prepare
from .rtl_analysis import parse_bench


def run(output, basis, include):
    compiler = shutil.which("g++")
    if not compiler or not (include / "ap_int.h").is_file():
        raise ValueError("compiler and HLS headers required")
    previous_path = basis / "results.json"
    previous = json.loads(previous_path.read_text())
    pins = prepare(output, basis)
    result = {"status": "RUNNING", "source": pins, "rows": [], "errors": [],
              "previous": {"path": str(previous_path), "sha256": sha256_file(previous_path)},
              "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
              "matrix": [(name, count, mode) for name, count, _ in CASES for mode in MODES],
              "hardware_timing_admitted": False, "production_baseline_admitted": False,
              "publication_match_admitted": False,
              "resources": {"memory_max_gib": 2, "reserve_gib": 8, "cpu_affinity": [126, 127],
                            "host_thread_stack_bytes": 1048576, "malloc_arena_max": 2,
                            "compile_timeout_seconds": 180, "case_timeout_seconds": 600}}
    report = output / "results.json"
    atomic_write_json(report, result)

    def execute(argv, prefix, timeout):
        record = run_bounded(["systemd-run", "--user", "--scope", "--quiet",
            "--property=MemoryMax=2G", "--property=MemorySwapMax=0", "taskset", "-c", "126,127", *argv],
            output, prefix, timeout=timeout, memory_gib=2, reserve_gib=8)
        if record["exit_code"] or record["timed_out"]:
            raise ValueError("finite source control failed; retain raw logs: " + str(prefix))
        return record

    try:
        binary = output / "probe"
        result["compile"] = execute(command(output / "source", include, compiler, binary), output / "compile", 180)
        result["binary_sha256"] = sha256_file(binary)
        result["dependencies"] = dependency_identities(binary.with_suffix(".d"), output)
        for name, count, mode in result["matrix"]:
            entry = {"case": name, "updates": count, "mode": mode}
            result["rows"].append(entry)
            try:
                entry["execution"] = execute(["env", "MALLOC_ARENA_MAX=2", "prlimit",
                                               "--stack=1048576:1048576", str(binary), str(output / "inputs" / name),
                                               str(int(mode == "stalled"))], output / f"{name}-{mode}", 600)
                entry["control"] = parse(Path(entry["execution"]["stdout"]).read_text(), count, mode)
            except Exception as error:
                entry["error"] = repr(error)
                result["errors"].append({"case": name, "mode": mode, "error": repr(error)})
            atomic_write_json(report, result)
        bench = output / "rtl-bench-source"
        result["rtl_bench_compile"] = execute(command(output / "source", include, compiler, bench, rtl=True),
                                              output / "rtl-bench-compile", 180)
        result["dependencies"] += dependency_identities(bench.with_suffix(".d"), output)
        result["rtl_bench_execution"] = execute(["env", "MALLOC_ARENA_MAX=2", str(bench)],
                                               output / "rtl-bench", 180)
        result["rtl_bench_source"] = parse_bench(Path(result["rtl_bench_execution"]["stdout"]).read_text())
        result["rtl_bench_binary_sha256"] = sha256_file(bench)
        if any(sha256_file(Path(pin["path"])) != pin["sha256"]
               for pin in pins + result["dependencies"]):
            raise ValueError("frozen source changed")
        result["analysis"] = analyze(result, previous)
        result["status"] = "FINITE_HLS_SOURCE_PASS_NOT_RTL_TIMING"
    except Exception as error:
        result["errors"].append({"error": repr(error)})
        result["status"] = "FAILED_RETAINED"
        atomic_write_json(report, result)
        raise
    atomic_write_json(report, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--basis", type=Path, required=True)
    parser.add_argument("--hls-include", type=Path, required=True)
    args = parser.parse_args()
    run(*(path.resolve() for path in (args.output, args.basis, args.hls_include)))
