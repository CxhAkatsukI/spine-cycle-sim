"""Run a fixed original-A4/legacy/skip-empty/whole-line model control."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...link_runtime import run_link
from .analysis import admit, matrix
from .contract import BOUNDARY, LIMITS, label, run_specs
from .execution import binary_paths, case_command, commands, execute, require_executors
from .preparation import bases, freeze, identity, pins
from .recheck import recheck


def run(root: Path, output: Path, extraction: Path) -> dict:
    reports = bases(root)
    frozen = freeze(root, output, extraction, reports)
    plugin = root / "build/sst/libspine_cycle.so"
    manifest = {"schema": 1, "root": str(root), "output": str(output), **frozen,
                "boundary": BOUNDARY, "limits": LIMITS, "memory": reports["partition"]["memory"],
                "model": reports["partition"]["model"], "default_plugin_sha256_before": sha256_file(plugin),
                "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                "dirty_diff": subprocess.check_output(["git", "diff", "HEAD", "--", "cpp/tests/routed_regraph"],
                                                       cwd=root, text=True),
                "python_executable": sys.executable, "parent_affinity": sorted(os.sched_getaffinity(0)),
                "tools": [identity(Path(shutil.which(tool)).resolve()) for tool in ("g++", "cmake", "taskset")],
                "strict_resource_match_admitted": False, "hardware_timing_admitted": False,
                "source_claim": "explicit_model_version_change_plus_verified_legacy_replay_not_old_recheck_relaxation"}
    atomic_write_json(output / "manifest.json", manifest)
    report = {"schema": 1, "manifest_sha256": sha256_file(output / "manifest.json"), "status": "running",
              "runs": [], "cases": []}
    atomic_write_json(output / "results.json", report)
    try:
        for name, command, budget, timeout in commands(root, output):
            execute(root, output, report, name, command, budget, timeout)
            if name == "compiler" and (output / "raw/compiler.stdout.txt").read_text() != reports["numerical"]["compiler_version"]:
                raise ValueError("compiler differs from frozen numerical basis")
        report["executors"] = {name: identity(path) for name, path in binary_paths(output).items()}
        build_files = {path for path in binary_paths(output).values()}
        build_files.update(output / "build" / name for name in ("CMakeCache.txt", "compile_commands.json"))
        report["build_files"] = [{"relative": str(path.relative_to(output)), "sha256": sha256_file(path)}
                                 for path in sorted(build_files)]
        for mode, latency, reverse, arm in run_specs():
            name = label(mode, latency, reverse, arm)
            state = output / "states" / name
            state.mkdir(parents=True)
            raw = execute(root, output, report, name, case_command(output, mode, latency, reverse, arm),
                          LIMITS["run_tree_gib"], LIMITS["run_timeout_seconds"])
            if raw.with_name(raw.name.replace("stdout", "stderr")).read_bytes():
                raise ValueError("model control emitted stderr: " + name)
            geometry = next(item for item in frozen["inputs"] if item["mode"] == mode)
            previous = next(item for item in reports["partition"]["cases"]
                            if (item["mode"], item["latency"], item["reverse"]) == (mode, latency, reverse))
            skip = next(item for item in reports["sensitivity"]["cases"]
                        if (item["mode"], item["latency"], item["reverse"], item["empty_exit"]) == (mode, latency, reverse, 0))
            row = admit(raw.read_text(), state, geometry, previous, skip, arm, frozen["layout_audit"])
            report["cases"].append({"mode": mode, "latency": latency, "reverse": reverse, "arm": arm, **row})
            atomic_write_json(output / "results.json", report)
            print(name, "FULL_STATE_AND_TRAFFIC_PASS", flush=True)
        require_executors(report["executors"])
        if (pins(root, reports) != frozen["sources"] or sha256_file(plugin) != manifest["default_plugin_sha256_before"]
                or any(identity(Path(item["path"])) != item for item in manifest["tools"])):
            raise ValueError("sources or default plugin changed during experiment")
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
    parser.add_argument("--pre-extraction", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[5]
    output, extraction = args.output.resolve(), args.pre_extraction.resolve()
    if args.worker:
        print(json.dumps(run(root, output, extraction)["admission"], sort_keys=True), flush=True)
        return
    if output.exists() or list(output.parent.glob(output.name + "_watchdog.*")):
        raise FileExistsError("fresh model control and watchdog paths required")
    command = [sys.executable, "-m", __package__ + ".study", "--worker", "--output", str(output),
               "--pre-extraction", str(extraction)]
    record = run_link(command, root, output.with_name(output.name + "_watchdog"),
                      timeout=LIMITS["outer_timeout_seconds"], tree_memory_gib=LIMITS["outer_tree_gib"],
                      reserve_gib=LIMITS["reserve_gib"], poll_seconds=1)
    print(json.dumps(record, sort_keys=True))
    if record["exit_code"] or record["stop_reason"] != "process_exit" or record["cleanup_snapshot_error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
