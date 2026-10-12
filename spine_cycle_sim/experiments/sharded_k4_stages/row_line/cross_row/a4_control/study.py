"""Run explicitly versioned A4/whole-line/cross-row one-round controls."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ....link_runtime import run_link
from ...a4_control.preparation import identity
from .analysis import admit, matrix
from .contract import BOUNDARY, LIMITS, VERSION, label, run_specs
from .execution import binary_paths, case_command, commands, execute, require_executors
from .preparation import freeze, pins
from .recheck import recheck


def run(root, output, pre_edit):
    frozen = freeze(root, output, pre_edit)
    plugin = root / "build/sst/libspine_cycle.so"
    manifest = {"schema": 1, "version": VERSION, "root": str(root), "output": str(output), **frozen,
                "boundary": BOUNDARY, "limits": LIMITS, "python_executable": sys.executable,
                "default_plugin_sha256_before": sha256_file(plugin),
                "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "dirty_diff": subprocess.check_output(["git", "diff", "HEAD", "--", "cpp"], cwd=root, text=True),
                "parent_affinity": sorted(os.sched_getaffinity(0)),
                "tools": [identity(Path(shutil.which(tool)).resolve()) for tool in ("g++", "cmake", "taskset")],
                "hardware_timing_admitted": False, "strict_resource_match_admitted": False}
    atomic_write_json(output / "manifest.json", manifest)
    basis = json.loads((output / "bases/results.json").read_text())
    report = {"schema": 1, "status": "running", "manifest_sha256": sha256_file(output / "manifest.json"),
              "runs": [], "cases": []}
    try:
        for name, command, budget, timeout in commands(root, output):
            execute(root, output, report, name, command, budget, timeout)
            if name == "compiler" and (output / "raw/compiler.stdout.txt").read_bytes() != (output / "bases/compiler.txt").read_bytes():
                raise ValueError("compiler differs from historical basis")
        report["executors"] = {name: identity(path) for name, path in binary_paths(output).items()}
        files = set(binary_paths(output).values()) | {output / "build" / name for name in
                                                     ("CMakeCache.txt", "compile_commands.json")}
        report["build_files"] = [{"relative": str(p.relative_to(output)), "sha256": sha256_file(p)} for p in sorted(files)]
        for spec in run_specs():
            mode, latency, reverse, arm = spec
            name = label(*spec)
            state = output / "states" / name
            state.mkdir(parents=True)
            raw = execute(root, output, report, name, case_command(output, *spec),
                          LIMITS["run_tree_gib"], LIMITS["run_timeout_seconds"])
            if (output / "raw" / (name + ".stderr.txt")).read_bytes():
                raise ValueError("control emitted stderr")
            geometry = next(item for item in frozen["inputs"] if item["mode"] == mode)
            result = admit(raw.read_text(), state, geometry, basis, spec)
            report["cases"].append({"mode": mode, "latency": latency, "reverse": reverse, "arm": arm, **result})
            atomic_write_json(output / "results.json", report)
            print(name, "FULL_STATE_AND_TRAFFIC_PASS", flush=True)
        require_executors(report["executors"])
        if (pins(root) != frozen["sources"] or sha256_file(plugin) != manifest["default_plugin_sha256_before"]
                or any(identity(Path(item["path"])) != item for item in manifest["tools"])):
            raise ValueError("executed sources, tools or production plugin changed")
        report["default_plugin_sha256_after"] = sha256_file(plugin)
        report["admission"] = matrix(report["cases"])
        report["status"] = report["admission"]["status"]
        atomic_write_json(output / "results.json", report)
        recheck(output)
    except BaseException as error:
        report["status"], report["error"] = "failed_attempt_retained", repr(error)
        raise
    finally:
        atomic_write_json(output / "results.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pre-edit", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[6]
    output, before = args.output.resolve(), args.pre_edit.resolve()
    if args.worker:
        print(json.dumps(run(root, output, before)["admission"], sort_keys=True), flush=True)
        return
    prefix = output.with_name(output.name + "_watchdog")
    if output.exists() or list(prefix.parent.glob(prefix.name + ".*")):
        raise FileExistsError("fresh control and watchdog paths required")
    command = [sys.executable, "-m", __package__ + ".study", "--worker", "--output", str(output), "--pre-edit", str(before)]
    record = run_link(command, root, prefix, timeout=LIMITS["outer_timeout_seconds"],
                      tree_memory_gib=LIMITS["outer_tree_gib"], reserve_gib=LIMITS["reserve_gib"], poll_seconds=1)
    print(json.dumps(record, sort_keys=True))
    if record["exit_code"] or record["stop_reason"] != "process_exit" or record["cleanup_snapshot_error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
