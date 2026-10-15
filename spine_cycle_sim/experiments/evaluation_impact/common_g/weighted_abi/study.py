"""Run lightweight source controls; this is not HLS synthesis or RTL timing."""

import argparse
from pathlib import Path
import shutil
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import dependency_identities, run_bounded
from .analysis import analyze, diagnostics
from .preparation import ADAPTERS, SEARCH_MODES, command, prepare


def run(output: Path, upstream: Path, integration: Path, include: Path, *, search_mode="pristine"):
    compiler = shutil.which("g++")
    if not compiler or not (include / "ap_int.h").is_file():
        raise ValueError("G++ and vendor HLS headers are required")
    pins = prepare(output, upstream, integration, search_mode=search_mode)
    finite = search_mode == "finite_pipeline"
    memory_gib, reserve_gib = (2, 88) if finite else (1, 8)
    cpu = 126 if finite else 127
    result = {"status": "RUNNING", "source": pins, "declared_adapters": list(ADAPTERS),
              "adapters": [], "errors": [], "hardware_timing_admitted": False,
              "production_baseline_admitted": False, "publication_match_admitted": False,
              "search_mode": search_mode,
              "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
              "resources": {"memory_max_gib": memory_gib, "reserve_gib": reserve_gib,
                            "cpu_affinity": [cpu],
                            "compile_timeout_seconds": 180, "run_timeout_seconds": 180},
              "scope": ("host_layout_finite_search_current_dispatch_cache_edit_adapter_source_only"
                        if finite else
                        "host_layout_original_search_current_dispatch_cache_edit_adapter_source_only")}
    report = output / "results.json"
    atomic_write_json(report, result)
    for adapter in ADAPTERS:
        folder = output / adapter
        folder.mkdir()
        binary = folder / "probe"
        entry = {"adapter": adapter}
        result["adapters"].append(entry)
        try:
            for label, argv in (("compile", command(output / "source", include, adapter, compiler,
                                                    binary, search_mode=search_mode)),
                                ("execute", [str(binary)])):
                if finite:
                    argv = ["env", "MALLOC_ARENA_MAX=2", *argv]
                entry[label] = run_bounded(["systemd-run", "--user", "--scope", "--quiet",
                    f"--property=MemoryMax={memory_gib}G", "--property=MemorySwapMax=0",
                    "taskset", "-c", str(cpu), *argv], folder, folder / label,
                    timeout=180, memory_gib=memory_gib, reserve_gib=reserve_gib)
                if entry[label]["exit_code"] or entry[label]["timed_out"]:
                    raise ValueError(f"{label} failed; retained raw logs")
            entry["dependencies"] = dependency_identities(binary.with_suffix(".d"), folder)
            entry["binary_sha256"] = sha256_file(binary)
            entry["rows"] = analyze(Path(entry["execute"]["stdout"]).read_text(),
                                    Path(entry["execute"]["stderr"]).read_text(),
                                    search_mode=search_mode)
            entry["diagnostics"] = diagnostics(Path(entry["execute"]["stderr"]).read_text(),
                                               search_mode=search_mode)
        except Exception as error:
            entry["error"] = repr(error)
            result["errors"].append({"adapter": adapter, "error": repr(error)})
        atomic_write_json(report, result)
    if any(sha256_file(Path(pin["path"])) != pin["sha256"] for pin in pins):
        result["errors"].append({"error": "frozen source changed"})
    result["status"] = "FAILED_RETAINED" if result["errors"] else "WEIGHTED_SOURCE_ABI_PASS_NOT_TIMING"
    atomic_write_json(report, result)
    if result["errors"]:
        raise ValueError("one or more declared weighted source controls failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--hls-include", type=Path, required=True)
    parser.add_argument("--search-mode", choices=SEARCH_MODES, default="pristine")
    args = parser.parse_args()
    run(*(path.resolve() for path in (args.output, args.upstream, args.integration, args.hls_include)),
        search_mode=args.search_mode)
