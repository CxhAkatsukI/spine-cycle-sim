"""Memory-admitted compile and CPU preflight; never invokes FPGA programming."""

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
from ..search_pipeline.synthesis import unchanged
from . import analysis, preparation

POLICY = {"tree_memory_gib": 2, "reserve_gib": 24, "allow_bounded_builds": True}


def run(output, integration, xrt, *, wait_seconds=1800):
    if output.exists():
        raise FileExistsError(output)
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= 86400:
        raise ValueError("finite one-second to one-day memory wait required")
    group = current()
    containment = verify(group, memory_gib=2)
    if int(containment["limits"]["memory.max"]) != 2 * 1024**3 or \
            int(containment["limits"]["memory.high"]) > 1536 * 1024**2:
        raise ValueError("2-GiB hard/at most 1536-MiB high containment required")
    compiler = Path(shutil.which("g++") or "/missing/compiler").resolve()
    if not compiler.is_file() or not (xrt / "include/CL/cl_ext_xilinx.h").is_file():
        raise ValueError("G++ and installed XRT required")
    pins, contract = preparation.prepare(output, integration)
    runners = {Path(module.__file__) for name, module in sys.modules.copy().items()
               if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)}
    pins += [{"path": str(path), "sha256": sha256_file(path)}
             for path in (compiler, Path(sys.executable), *sorted(runners))]
    report = {"status": "PREPARED", "errors": [], "steps": [], "pins": pins,
              "contract": contract, "policy": POLICY, "containment": containment,
              "compiler_version": subprocess.check_output([str(compiler), "--version"], text=True),
              "python_version": sys.version, **dict.fromkeys(preparation.CLAIMS, False),
              "scope": "host compile/model only; no FPGA API, real device refresh or hardware timing"}
    save = lambda: atomic_write_json(output / "results.json", report)
    lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    save()
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            unchanged(pins)
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), POLICY, commit=True)
            report["status"] = "WAITING_FOR_MEMORY_NOT_OTHER_TOOLS"
            save()
            if report["admission"]["admitted"]:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("full finite memory budgets plus reserve do not fit; no child launched")
            time.sleep(min(10, remaining))
        binary = output / "probe"
        commands = [("compile", preparation.command(output / "source", xrt, str(compiler), binary)),
                    ("model", [str(binary), "--model-check", preparation.CASE["input"]]),
                    ("stale", [str(binary), "--model-check", preparation.CASE["input"], "--stale-metadata"])]
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LANG": "C", "LC_ALL": "C",
                       "MALLOC_ARENA_MAX": "2"}
        report["environment"] = environment
        for label, argv in commands:
            unchanged(pins)
            report["status"] = "RUNNING_" + label
            save()
            step = run_link(argv, output, output / "raw" / label, timeout=300, tree_memory_gib=2,
                            reserve_gib=24, environment=environment)
            report["steps"].append({"label": label, **step})
            save()
            if step["exit_code"] != (1 if label == "stale" else 0) or \
                    step["stop_reason"] != "process_exit" or step["cleanup_snapshot_error"]:
                raise RuntimeError("metadata preflight child failed/safely stopped: " + label)
            stdout, stderr = ((output / "raw" / (label + suffix)).read_text()
                              for suffix in (".stdout.txt", ".stderr.txt"))
            if label == "compile":
                if stdout.strip() or stderr.strip():
                    raise ValueError("unexpected metadata preflight compile diagnostic")
                report["binary_sha256"] = sha256_file(binary)
                pins += dependency_identities(binary.with_suffix(".d"), output)
            elif label == "model":
                report["model"] = analysis.analyze(stdout, stderr)
            else:
                report["negative"] = analysis.stale_rejection(stdout, stderr)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "integration", "xrt"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=1800)
    args = parser.parse_args()
    print(run(*(path.resolve() for path in (args.output, args.integration, args.xrt)),
              wait_seconds=args.wait_seconds)["status"], flush=True)


if __name__ == "__main__":
    main()
