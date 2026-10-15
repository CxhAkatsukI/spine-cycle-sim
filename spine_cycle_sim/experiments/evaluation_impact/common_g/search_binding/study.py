"""Run a bounded C++14 production-shaped search binding control."""

import argparse
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from .analysis import analyze
from .preparation import MATRIX, command, prepare


def run(output: Path, integration: Path, include: Path):
    compiler = shutil.which("g++")
    if not compiler or not (include / "ap_int.h").is_file():
        raise ValueError("compiler and vendor HLS headers required")
    pins = prepare(output, integration)
    result = {"status": "RUNNING", "source": pins, "matrix": MATRIX, "errors": [],
              "hardware_timing_admitted": False, "production_baseline_admitted": False,
              "publication_match_admitted": False,
              "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
              "resources": {"memory_max_gib": 2, "reserve_gib": 88, "cpu_affinity": [125],
                            "compile_timeout_seconds": 180, "run_timeout_seconds": 600}}
    report = output / "results.json"
    atomic_write_json(report, result)
    try:
        binary = output / "probe"
        for label, argv, timeout in (
                ("compile", command(output / "source", include, compiler, binary), 180),
                ("execute", ["env", "MALLOC_ARENA_MAX=2", "prlimit", "--stack=1048576:1048576",
                             str(binary)], 600)):
            result[label] = run_bounded(["systemd-run", "--user", "--scope", "--quiet",
                "--property=MemoryMax=2G", "--property=MemorySwapMax=0", "taskset", "-c", "125", *argv],
                output, output / label, timeout=timeout, memory_gib=2, reserve_gib=88)
            atomic_write_json(report, result)
            if result[label]["exit_code"] or result[label]["timed_out"]:
                raise ValueError(label + " failed; raw logs retained")
        result["binary_sha256"] = sha256_file(binary)
        result["dependencies"] = dependency_identities(binary.with_suffix(".d"), output)
        result["analysis"] = analyze(Path(result["execute"]["stdout"]).read_text())
        if any(sha256_file(Path(pin["path"])) != pin["sha256"]
               for pin in pins + result["dependencies"]):
            raise ValueError("frozen source or dependency changed")
        result["status"] = "SEARCH_BINDING_SOURCE_PASS_NOT_RTL"
    except Exception as error:
        result["errors"].append(repr(error))
        result["status"] = "FAILED_RETAINED"
        atomic_write_json(report, result)
        raise
    atomic_write_json(report, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--hls-include", type=Path, required=True)
    args = parser.parse_args()
    run(*(path.resolve() for path in (args.output, args.integration, args.hls_include)))
