"""Bounded XRT-host preflight: native hot/cold plus exact old-matrix state regression."""

import argparse
import json
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
from ..continuous_board import analysis as old_analysis, preparation as old_preparation
from ..continuous_board.delivery import validate as validate_old
from ..search_pipeline.synthesis import unchanged
from . import analysis, preparation

POLICY = {"tree_memory_gib": 4, "reserve_gib": 32, "allow_bounded_builds": True}


def run(output, upstream, integration, xrt, reference, *, wait_seconds=1800):
    if output.exists():
        raise FileExistsError(output)
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= 86400:
        raise ValueError("finite memory wait between one second and one day required")
    group = current()
    containment = verify(group, memory_gib=4)
    if int(containment["limits"]["memory.max"]) != 4 * 1024**3 or \
            int(containment["limits"]["memory.high"]) > 3 * 1024**3:
        raise ValueError("exact 4-GiB hard/at most 3-GiB high cgroup required")
    compiler = Path(shutil.which("g++") or "/missing/compiler").resolve()
    if not compiler.is_file() or not (xrt / "include/CL/cl_ext_xilinx.h").is_file():
        raise ValueError("G++ and installed XRT required")
    old = json.loads((reference / "results.json").read_text())
    validate_old(reference, old)
    if old["status"] != old_analysis.PASS:
        raise ValueError("passing frozen reference matrix required")
    pins, contract = preparation.prepare(output, upstream, integration)
    frozen_reference = output / "reference"
    frozen_reference.mkdir()
    for path in (reference / "results.json", *sorted(reference.glob("*.stdout.txt")), *sorted(reference.glob("*.stderr.txt"))):
        target = frozen_reference / path.name
        shutil.copy2(path, target)
        pins.append({"original": str(path), "path": str(target), "sha256": sha256_file(target)})
    runners = {Path(module.__file__) for name, module in sys.modules.copy().items()
               if name.startswith("spine_cycle_sim.experiments") and getattr(module, "__file__", None)}
    pins += [{"path": str(path), "sha256": sha256_file(path)}
             for path in (compiler, Path(sys.executable), *sorted(runners))]
    report = {"status": "PREPARED", "errors": [], "steps": [], "cases": [], "regression": [],
              "pins": pins, "contract": contract, "policy": POLICY, "containment": containment,
              "compiler_version": subprocess.check_output([str(compiler), "--version"], text=True),
              "python_version": sys.version, "binary_sha256": {}, **dict.fromkeys(analysis.CLAIMS, False),
              "scope": "XRT host compilation and CPU oracle only; no FPGA API invoked"}
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
                raise TimeoutError("complete finite budgets and reserve did not fit; no child launched")
            time.sleep(min(10, remaining))
        commands = [("compile-regression", old_preparation.command(output / "source", xrt, str(compiler), output / "regression-probe")),
                    ("compile-native", preparation.command(output / "source", xrt, str(compiler), output / "probe"))]
        commands += [(case["case"], [str(output / "regression-probe"), "--model-check", case["input"]])
                     for case in contract["regression_cases"]]
        commands += [(preparation.CASE["case"], [str(output / "probe"), "--model-check", preparation.CASE["input"]])]
        environment = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "LANG": "C", "LC_ALL": "C", "MALLOC_ARENA_MAX": "2"}
        report["environment"] = environment
        for label, argv in commands:
            unchanged(pins)
            report["status"] = "RUNNING_" + label
            save()
            step = run_link(argv, output, output / "raw" / label, timeout=300, tree_memory_gib=4,
                            reserve_gib=32, environment=environment)
            report["steps"].append({"label": label, **step})
            save()
            if step["exit_code"] or step["stop_reason"] != "process_exit" or step["cleanup_snapshot_error"]:
                raise RuntimeError("native preflight child failed or safely stopped: " + label)
            stdout, stderr = ((output / "raw" / (label + suffix)).read_text() for suffix in (".stdout.txt", ".stderr.txt"))
            if label.startswith("compile-"):
                if stdout.strip() or stderr.strip():
                    raise ValueError("unexpected compile diagnostic")
                binary = Path(argv[-1])
                report["binary_sha256"][binary.name] = sha256_file(binary)
                pins += dependency_identities(binary.with_suffix(".d"), output)
            elif label == preparation.CASE["case"]:
                report["cases"].append({"case": label, **analysis.analyze(preparation.CASE, stdout, stderr)})
            else:
                case = next(case for case in contract["regression_cases"] if case["case"] == label)
                actual = old_analysis.analyze(case, stdout, stderr)
                previous = next(case for case in old["cases"] if case["case"] == label)
                if analysis.deterministic(actual) != analysis.deterministic(previous):
                    raise ValueError("old resident-state deterministic output changed: " + label)
                report["regression"].append({"case": label, "equivalent": True, **actual})
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
    for name in ("output", "upstream", "integration", "xrt", "reference"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--wait-seconds", type=int, default=1800)
    args = parser.parse_args()
    print(run(*(path.resolve() for path in (args.output, args.upstream, args.integration, args.xrt, args.reference)),
              wait_seconds=args.wait_seconds)["status"], flush=True)
