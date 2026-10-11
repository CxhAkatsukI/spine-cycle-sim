"""Build an isolated K4 harness and replay a fixed twelve-case sensitivity matrix."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.delivery import recheck as recheck_basis
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from ..production_validation import recheck as recheck_production
from .analysis import ARMS, MATRIX, admit, matrix

DOC = Path("docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4")
HARNESS = Path("cpp/tests/routed_regraph/empty_segment")


def pins(root: Path, basis: dict) -> list[dict]:
    previous = json.loads(Path(basis["basis"]["path"]).read_text())
    paths = {root / item["path"] for item in previous["sources"]}
    paths.update(root / item["path"] for item in basis["sources"])
    paths.update(Path(__file__).parent.glob("*.py"))
    paths.update((root / HARNESS).glob("*"))
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if filename:
            path = Path(filename).resolve()
            if path.suffix == ".py" and path.is_relative_to(root / "spine_cycle_sim"):
                paths.add(path)
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)}
            for path in sorted(paths) if path.is_file()]


def command(python: str, output: Path, basis: Path, production: Path) -> list[str]:
    return [python, "-m", __package__ + ".study", "--worker", "--output", str(output),
            "--basis", str(basis), "--production", str(production)]


def run(root: Path, output: Path, basis_run: Path, production: Path) -> dict:
    if output.exists():
        raise FileExistsError("fresh sensitivity output required")
    published = root / DOC / "matched_a4/sssp_partition_round/evidence/results.json"
    if sha256_file(basis_run / "results.json") != sha256_file(published):
        raise ValueError("four-partition basis differs from committed evidence")
    basis = recheck_basis(root, basis_run)
    production_gate = recheck_production(production, current_inputs=True)
    output.mkdir(parents=True)
    plugin = root / "build/sst/libspine_cycle.so"
    report = {"schema_version": 2, "status": "running", "sources": pins(root, basis),
              "basis": {"path": str(basis_run / "results.json"), "sha256": sha256_file(published)},
              "production": {"path": str(production / "results.json"),
                             "sha256": sha256_file(production / "results.json"),
                             "xo": production_gate["report"]["xo"]},
              "runs": [], "cases": [], "inputs": basis["inputs"],
              "model": basis["model"], "memory": basis["memory"], "boundary": basis["boundary"],
              "python_executable": sys.executable, "cpu_affinity": sorted(os.sched_getaffinity(0)),
              "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
              "default_plugin_sha256_before": sha256_file(plugin),
              "scope": "single_parameter_sensitivity_not_routed_timing_or_production_calibration"}
    for item in report["sources"]:
        destination = output / "sources" / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / item["path"], destination)
        if sha256_file(destination) != item["sha256"]:
            raise ValueError("pre-execution source snapshot differs")
    atomic_write_json(output / "results.json", report)

    def execute(label: str, argv: list[str], budget: int, timeout: int) -> Path:
        if "executor" in report:
            require_executor(report["executor"])
        prefix = output / "raw" / label
        record = run_link(argv, root, prefix, timeout=timeout, tree_memory_gib=budget,
                          reserve_gib=16, poll_seconds=0.5)
        report["runs"].append({"label": label, **record})
        atomic_write_json(output / "results.json", report)
        if record["exit_code"] or record["stop_reason"] != "process_exit" or record["cleanup_snapshot_error"]:
            raise RuntimeError("sensitivity execution failed: " + label)
        return prefix.with_suffix(".stdout.txt")

    try:
        execute("configure", ["cmake", "-S", str(root / HARNESS), "-B", str(output / "build"),
                              "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTING=OFF"], 6, 300)
        execute("build", ["cmake", "--build", str(output / "build"), "--target",
                          "routed_regraph_empty_segment_round", "-j2"], 6, 600)
        binary = output / "build/routed_regraph_empty_segment_round"
        report["executor"] = {"path": str(binary), "sha256": sha256_file(binary)}
        execute("compiler", ["c++", "--version"], 1, 30)
        report["cmake_cache_sha256"] = sha256_file(output / "build/CMakeCache.txt")
        for frozen in basis["cases"]:
            mode, latency, reverse = (frozen[k] for k in ("mode", "latency", "reverse"))
            geometry = next(item for item in basis["inputs"] if item["mode"] == mode)
            for arm in ARMS:
                label = f"{mode}_lat{latency}_reverse{reverse}_empty{arm}"
                state = output / "states" / label
                state.mkdir(parents=True)
                raw = execute(label, [str(binary), geometry["path"], str(state), str(latency),
                                      str(reverse), "100000000", str(arm)], 3, 180)
                if raw.with_name(raw.name.replace("stdout", "stderr")).read_bytes():
                    raise ValueError("sensitivity emitted stderr: " + label)
                report["cases"].append({"mode": mode, "latency": latency, "reverse": reverse,
                    "empty_exit": arm, **admit(raw.read_text(), state, geometry, frozen, arm)})
                atomic_write_json(output / "results.json", report)
        report["admission"] = matrix(report["cases"])
        require_executor(report["executor"])
        recheck_basis(root, basis_run)
        recheck_production(production, current_inputs=True)
        if (pins(root, basis) != report["sources"]
                or sha256_file(plugin) != report["default_plugin_sha256_before"]
                or sha256_file(basis_run / "results.json") != report["basis"]["sha256"]
                or sha256_file(production / "results.json") != report["production"]["sha256"]
                or sha256_file(output / "build/CMakeCache.txt") != report["cmake_cache_sha256"]):
            raise ValueError("source, plugin or frozen basis changed during sensitivity")
        for geometry in basis["inputs"]:
            for item in geometry["files"]:
                if sha256_file(Path(item["path"])) != item["sha256"]:
                    raise ValueError("frozen input changed during sensitivity")
        report["default_plugin_sha256_after"] = sha256_file(plugin)
        report["status"] = report["admission"]["status"]
    except (OSError, ValueError, RuntimeError) as error:
        report["status"], report["error"] = "failed", str(error)
        raise
    finally:
        atomic_write_json(output / "results.json", report)
    return report


def require_executor(pin: dict) -> None:
    path = Path(pin["path"])
    if path.is_symlink() or sha256_file(path) != pin["sha256"]:
        raise ValueError("standalone executable changed before launch or completion")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("output", "basis", "production"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[5]
    output, basis, production = (getattr(args, key).resolve() for key in ("output", "basis", "production"))
    if args.worker:
        report = run(root, output, basis, production)
        print(json.dumps(report["admission"], sort_keys=True))
        return
    if output.exists() or list(output.parent.glob(output.name + "_watchdog.*")):
        raise FileExistsError("fresh run and watchdog paths required")
    record = run_link(command(sys.executable, output, basis, production), root,
                      output.with_name(output.name + "_watchdog"), timeout=1800,
                      tree_memory_gib=8, reserve_gib=16, poll_seconds=1)
    print(json.dumps(record, sort_keys=True))
    if record["exit_code"] or record["stop_reason"] != "process_exit" or record["cleanup_snapshot_error"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
