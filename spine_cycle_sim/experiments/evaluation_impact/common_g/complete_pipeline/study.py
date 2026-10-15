"""Execute full-capacity G source checks under bounded parallel admission."""

import argparse
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from ..search_pipeline.synthesis import unchanged
from .analysis import analyze, diagnostics
from .preparation import command, prepare


def run(output: Path, upstream: Path, integration: Path, include: Path, reserve_gib: int = 120):
    if type(reserve_gib) is not int or not 104 <= reserve_gib <= 120:
        raise ValueError("source verification requires a 104--120 GiB reserve")
    compiler = shutil.which("g++")
    if not compiler or not (include / "ap_int.h").is_file():
        raise ValueError("G++ and vendor HLS headers required")
    pins = prepare(output, upstream, integration)
    result = {"status": "PREPARED", "source": pins, "errors": [],
              "scope": "full_hot_halves_cold_DDR_four_search_CUs_dispatch_direct_adapter_source_only",
              "fixture": "synthetic_reserved_PMA_stress_not_real_trace_or_host_reservation_validation",
              "internal_cache_ddr_fifos": "unbounded_C_simulation_not_RTL_progress",
              "hardware_timing_admitted": False, "production_baseline_admitted": False,
              "publication_match_admitted": False, "integrated_rtl_admitted": False,
              "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
              "resources": {"memory_max_gib": 4, "reserve_gib": reserve_gib, "swap_max_bytes": 0,
                            "cpu_affinity": [124, 125], "compile_timeout_seconds": 300,
                            "execute_timeout_seconds": 900}}
    report = output / "results.json"
    save = lambda: atomic_write_json(report, result)
    save()
    binary = output / "probe"
    try:
        for label, argv, timeout in (
                ("compile", command(output / "source", include, compiler, binary), 300),
                ("execute", [str(binary)], 900)):
            unchanged(pins)
            result["status"] = "RUNNING_" + label.upper()
            save()
            result[label] = run_bounded(["systemd-run", "--user", "--scope", "--quiet",
                "--property=MemoryHigh=3G", "--property=MemoryMax=4G", "--property=MemorySwapMax=0",
                "env", "MALLOC_ARENA_MAX=2", "taskset", "-c", "124,125", *argv],
                output, output / label, timeout=timeout, memory_gib=4, reserve_gib=reserve_gib)
            if result[label]["exit_code"] or result[label]["timed_out"]:
                raise ValueError(f"{label} failed; raw attempt retained")
        result["dependencies"] = dependency_identities(binary.with_suffix(".d"), output)
        result["binary_sha256"] = sha256_file(binary)
        result["rows"] = analyze(Path(result["execute"]["stdout"]).read_text(),
                                 Path(result["execute"]["stderr"]).read_text())
        result["diagnostics"] = diagnostics(Path(result["execute"]["stderr"]).read_text())
        unchanged(pins + result["dependencies"])
        result["status"] = "COMPLETE_G_SOURCE_COMPOSITION_PASS_NOT_INTEGRATED_RTL"
    except Exception as error:
        result["errors"].append(repr(error))
        result["status"] = "FAILED_RETAINED"
        save()
        raise
    save()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "upstream", "integration", "hls-include"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--reserve-gib", type=int, default=120)
    args = parser.parse_args()
    run(*(path.resolve() for path in (args.output, args.upstream, args.integration, args.hls_include)), args.reserve_gib)
