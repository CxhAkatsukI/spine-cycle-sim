"""Memory-admitted native hot/cold G source check, not RTL or board timing."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes, dependency_identities
from ...search_pipeline.synthesis import unchanged
from . import analysis, preparation

POLICY = {"tree_memory_gib": 4, "reserve_gib": 32, "allow_bounded_builds": True}


def run(output, upstream, integration, include, *, wait_seconds=1800):
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= 86400:
        raise ValueError("memory wait must be between one second and one day")
    if output.exists():
        raise FileExistsError(output)
    compiler = Path(shutil.which("g++") or "/missing/compiler").resolve()
    if not compiler.is_file() or not (include / "ap_int.h").is_file():
        raise ValueError("G++ and vendor headers required")
    group = current()
    containment = verify(group, memory_gib=4)
    if int(containment["limits"]["memory.max"]) != 4 * 1024**3:
        raise ValueError("exact 4-GiB complete source-check cgroup required")
    pins = preparation.prepare(output, upstream, integration)
    runners = {Path(module.__file__) for name, module in sys.modules.copy().items()
               if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)}
    pins += [{"path": str(path), "sha256": sha256_file(path)}
             for path in (compiler, Path(sys.executable), *sorted(runners))]
    report = {"status": "PREPARED", "errors": [], "steps": [], "rows": [], "pins": pins,
              "contract": analysis.CONTRACT, "policy": POLICY, "containment": containment,
              "compiler_version": subprocess.check_output([str(compiler), "--version"], text=True),
              "python_version": sys.version, **dict.fromkeys(analysis.CLAIMS, False),
              "scope": "native_65536_multi_shard_full_cache_hot_cold_source_functionality",
              "excludes": ["integrated RTL progress", "XRT binding", "FPGA performance", "ReGraph compute",
                           "real-trace performance", "full reservation trace execution"]}
    save = lambda: atomic_write_json(output / "results.json", report)
    lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    save()
    try:
        deadline = time.monotonic() + wait_seconds
        report["status"] = "WAITING_FOR_MEMORY_NOT_FOR_OTHER_TOOLS_TO_EXIT"
        while True:
            unchanged(pins)
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), POLICY, commit=True)
            save()
            if report["admission"]["admitted"]:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("full budgets and reserve did not fit before deadline; no child launched")
            time.sleep(min(10, remaining))
        binary = output / "probe"
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()),
                       "LANG": "C", "LC_ALL": "C", "MALLOC_ARENA_MAX": "2"}
        report["environment"] = environment
        for label, argv, timeout in (
                ("compile", preparation.command(output / "source", include, str(compiler), binary), 300),
                ("native", [str(binary)], 1800)):
            unchanged(pins)
            report["status"] = "RUNNING_" + label
            save()
            result = run_link(argv, output, output / "raw" / label, timeout=timeout,
                              tree_memory_gib=4, reserve_gib=32, environment=environment)
            report["steps"].append({"label": label, **result})
            save()
            if result["exit_code"] or result["stop_reason"] != "process_exit" or result["cleanup_snapshot_error"]:
                raise RuntimeError("source child failed or safely stopped: " + label)
            stdout, stderr = ((output / "raw" / (label + suffix)).read_text()
                              for suffix in (".stdout.txt", ".stderr.txt"))
            if label == "compile":
                if stdout.strip() or stderr.strip():
                    raise ValueError("unexpected compile diagnostic")
                report["binary_sha256"] = sha256_file(binary)
                pins += dependency_identities(binary.with_suffix(".d"), output)
            else:
                report.update(analysis.analyze(stdout, stderr))
            unchanged(pins)
            save()
        report["status"] = analysis.PASS
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        lease.release()
        report["memory_events_after"] = (group / "memory.events").read_text()
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "upstream", "integration", "hls-include"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=1800)
    args = parser.parse_args()
    print(run(*(path.resolve() for path in (args.output, args.upstream, args.integration, args.hls_include)),
              wait_seconds=args.wait_seconds)["status"], flush=True)
