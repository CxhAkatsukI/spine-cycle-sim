"""Run a predeclared four-partition matrix with the unchanged validated model."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.original_regraph_inputs.analysis import analyze_topology
from spine_cycle_sim.experiments.original_regraph_inputs.preparation import inspect_graph
from ..sssp_real_round.preparation import overlay
from ..sssp_real_round.study import admitted_probe
from .analysis import MATRIX, admit, coverage, matrix
from .preparation import select
from .contract import MAX_CYCLES, SCOPE, TIMEOUT, worker_command
from .layout_audit import audit, bind_traffic


def frozen_executor(root: Path, baseline: Path) -> tuple[dict, Path]:
    published = root / "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/matched_a4/sssp_real_round/evidence/results.json"
    if sha256_file(baseline) != sha256_file(published):
        raise ValueError("basis differs from the committed validated real-round checkpoint")
    basis = json.loads(baseline.read_text())
    if not basis["admission"]["complete_state_and_traffic"] or basis["status"] != basis["admission"]["status"]:
        raise ValueError("basis not admitted")
    for item in [*basis["sources"], *basis["binaries"], basis["hls_udf"]]:
        path = root / item["path"]
        if path.is_symlink() or sha256_file(path) != item["sha256"]:
            raise ValueError("frozen numerical source or executable changed: " + str(path))
    model = basis["model"]
    if sha256_file(root / model["k4_profile_reference"]) != model["k4_profile_sha256"]:
        raise ValueError("frozen profile changed")
    probe = basis["probe"]
    if admitted_probe(root, Path(probe["report"]), Path(probe["binary"])) != probe:
        raise ValueError("author probe changed")
    executables = [Path(item["path"]) for item in basis["binaries"]
                   if Path(item["path"]).name == "original_regraph_sssp_real_round"]
    binary, = executables
    return basis, binary


def sources(root: Path) -> list[dict]:
    paths = [*Path(__file__).parent.glob("*.py"),
             root / "spine_cycle_sim/experiments/sharded_k4_stages/link_runtime.py",
             root / "spine_cycle_sim/experiments/sharded_k4_stages/process_cleanup.py",
             root / "configs/experiments/original_regraph_inputs_v1.json"]
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)}
            for path in sorted(paths)]


def run(root: Path, output: Path, source: Path, baseline: Path, maximum_cycles: int = MAX_CYCLES) -> dict:
    if output.exists():
        raise ValueError("use a unique four-partition output directory")
    if not 0 < maximum_cycles <= MAX_CYCLES:
        raise ValueError("invalid bounded cycle budget")
    basis, binary = frozen_executor(root, baseline)
    output.mkdir(parents=True)
    plugin = root / "build/sst/libspine_cycle.so"
    plugin_hash = sha256_file(plugin)
    if plugin_hash != basis["default_plugin_sha256_after"]:
        raise ValueError("default plugin changed from the validated checkpoint")
    report = {"schema_version": 2, "status": "running", "sources": sources(root), "runs": [], "cases": [],
        "python_executable": sys.executable,
        "basis": {"path": str(baseline), "sha256": sha256_file(baseline)},
        "basis_git_head": basis["git_head"],
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "executor": {"path": str(binary), "sha256": sha256_file(binary)},
        "cpu_affinity": sorted(os.sched_getaffinity(0)), "memory": basis["memory"], "model": basis["model"],
        "compiler_version": basis["compiler_version"], "cmake_cache": basis["cmake_cache"],
        "boundary": basis["boundary"], "declared_matrix": list(MATRIX),
        "maximum_cycles_per_path": maximum_cycles, "subprocess_timeout_seconds": TIMEOUT,
        "default_plugin_sha256_before": plugin_hash,
        "scope": SCOPE}

    def execute(label: str, command: list[str], timeout: int = TIMEOUT) -> dict:
        record = run_bounded(command, root, output / "raw" / label,
                             timeout=timeout, memory_gib=8, reserve_gib=16)
        report["runs"].append({"label": label, **record})
        atomic_write_json(output / "results.json", report)
        if record["exit_code"] or record["timed_out"]:
            raise RuntimeError("four-partition control failed: " + label)
        return record

    try:
        graph, selection = select(source, output / "topology.txt")
        report["selection"] = selection
        probe = basis["probe"]
        contract = json.loads((root / "configs/experiments/original_regraph_inputs_v1.json").read_text())
        capture = output / "author_capture"
        capture.mkdir()
        raw = execute("author_layout", [probe["binary"], str(output / "topology.txt"), str(capture), str(contract["seed"]), "1"])
        layout = analyze_topology(Path(raw["stdout"]).read_text(), capture, probe,
                                  inspect_graph(output / "topology.txt"), contract)
        report["layout"], report["coverage"] = layout, coverage(layout, capture)
        report["layout_audit"] = audit(capture, graph.vertices)
        report["inputs"] = []
        for mode in ("cold", "warm_update"):
            directory = output / "inputs" / mode
            geometry = overlay(graph, capture, layout, directory, mode)
            if geometry["active_initial"] != 1 or (mode == "warm_update" and not geometry["changed_weights"]):
                raise ValueError("source scenario does not exercise any outgoing update")
            report["inputs"].append({**geometry, "path": str(directory),
                "files": [{"path": str(path), "sha256": sha256_file(path)} for path in sorted(directory.iterdir())]})
        # Release the Python graph before cycle simulation; overlays are frozen on disk.
        del graph
        for mode, latency, reverse in MATRIX:
            label = f"{mode}_lat{latency}_reverse{reverse}"
            states = output / "states" / label
            states.mkdir(parents=True)
            geometry = next(row for row in report["inputs"] if row["mode"] == mode)
            raw = execute(label, [str(binary), geometry["path"], str(states), str(latency), str(reverse), str(maximum_cycles)])
            report["cases"].append({"mode": mode, "latency": latency, "reverse": reverse,
                **admit(Path(raw["stdout"]).read_text(), states, geometry)})
        report["admission"] = matrix(report["cases"])
        bind_traffic(report["layout_audit"], report["cases"])
        if sources(root) != report["sources"] or sha256_file(plugin) != plugin_hash:
            raise ValueError("study source or default plugin changed during execution")
        frozen_executor(root, baseline)
        if sha256_file(source) != selection["source"]["sha256"]:
            raise ValueError("source topology changed during execution")
        report["default_plugin_sha256_after"] = sha256_file(plugin)
        report["status"] = report["admission"]["status"]
    except (OSError, ValueError, RuntimeError) as error:
        report["status"], report["error"] = "failed", str(error)
        raise
    finally:
        atomic_write_json(output / "results.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("output", "source", "baseline"):
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--max-cycles", type=int, default=MAX_CYCLES)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    if args.worker:
        report = run(root, args.output.resolve(), args.source.resolve(), args.baseline.resolve(), args.max_cycles)
        print(json.dumps({"status": report["status"], "admission": report["admission"]}, sort_keys=True))
        return
    prefix = args.output.resolve().with_name(args.output.name + "_watchdog")
    command = worker_command(sys.executable, args.output.resolve(), args.source.resolve(),
                             args.baseline.resolve(), args.max_cycles)
    record = run_link(command, root, prefix, timeout=1500, tree_memory_gib=8, reserve_gib=16, poll_seconds=1)
    print(json.dumps(record, sort_keys=True))
    if record["exit_code"] or record["stop_reason"] != "process_exit":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
