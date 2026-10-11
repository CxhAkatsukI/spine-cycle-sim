"""Bounded real-input control; input layout, execution and admission stay separate."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.shared_workloads import load_slice
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from spine_cycle_sim.experiments.original_regraph_inputs.analysis import STATUS, analyze_topology
from spine_cycle_sim.experiments.original_regraph_inputs.preparation import inspect_graph
from ..regression import verify_legacy
from ..sssp_control import LEGACY_TARGETS, SSSP_TARGETS, source_identities
from .analysis import MODES, LATENCIES, admit_matrix, admit_round
from .evidence import apply_schedule
from .preparation import overlay

TARGETS = (*LEGACY_TARGETS, *SSSP_TARGETS, "original_regraph_a4_execution", "original_regraph_sssp_real_round")


def identities(root: Path) -> list[dict]:
    rows = {item["path"]: item for item in source_identities(root)}
    helpers = ("original_regraph_inputs/analysis.py", "original_regraph_inputs/preparation.py",
               "original_regraph_execution/regression.py", "shared_workloads.py",
               "upstream_controls/execution.py", "campaign_runtime.py")
    paths = [*Path(__file__).parent.glob("*.py"),
             *(root / "spine_cycle_sim/experiments" / helper for helper in helpers)]
    for path in paths:
        rows[str(path.relative_to(root))] = {"path": str(path.relative_to(root)), "sha256": sha256_file(path)}
    return sorted(rows.values(), key=lambda row: row["path"])


def admitted_probe(root: Path, report_path: Path, probe: Path) -> dict:
    report = json.loads(report_path.read_text())
    if report["status"] != STATUS:
        raise ValueError("original author-layout study did not pass")
    row, = [item for item in report["topologies"] if item["id"] == "a4"]
    if (row["little"], row["big"]) != (4, 0) or sha256_file(probe) != row["binary_sha256"]:
        raise ValueError("author A4 layout probe identity differs")
    for dependency in row["dependencies"]:
        if sha256_file(Path(dependency["path"])) != dependency["sha256"]:
            raise ValueError("author-layout dependency changed: " + dependency["path"])
    return {"report": str(report_path), "report_sha256": sha256_file(report_path),
            "binary": str(probe), **row, "source_revision": report["source_revision"]}


def whole_regression(build: Path, baseline: Path, output: Path, execute) -> dict:
    frozen = json.loads((baseline / "baseline.json").read_text())
    checked = []
    for old in frozen["runs"]:
        command = old["command"]
        if old["exit_code"] or old["timed_out"]:
            raise ValueError("whole-A4 baseline contains failed case")
        old_output = Path(command[2])
        new_output = output / "legacy_whole" / old_output.name
        new_output.mkdir(parents=True)
        new = execute("whole_" + old_output.name, [str(build / "cpp/original_regraph_a4_execution"),
                      command[1], str(new_output), *command[3:]], 180)
        for stream in ("stdout", "stderr"):
            if Path(old[stream]).read_bytes() != Path(new[stream]).read_bytes():
                raise ValueError("whole-A4 cycles/counters changed: " + old_output.name)
        old_files = sorted(path.name for path in old_output.iterdir() if path.is_file())
        if old_files != sorted(path.name for path in new_output.iterdir() if path.is_file()) or not old_files:
            raise ValueError("whole-A4 full output file set changed")
        files = []
        for name in old_files:
            digest = sha256_file(old_output / name)
            if digest != sha256_file(new_output / name):
                raise ValueError("whole-A4 full output changed: " + name)
            files.append({"path": str(new_output / name), "sha256": digest})
        checked.append({"case": old_output.name, "outputs": files, "stdout_sha256": sha256_file(Path(new["stdout"])),
                        "full_outputs_cycles_counters_identical": True})
    if [item["case"] for item in checked] != ["skewed_sources", "boundary_ring", "amazon"]:
        raise ValueError("whole-A4 legacy case set changed")
    return {"baseline_sha256": sha256_file(baseline / "baseline.json"), "cases": checked}


def run(root: Path, build: Path, output: Path, component_baseline: Path,
        whole_baseline: Path, reference: Path, probe_report: Path, probe: Path, apply_solution: Path) -> dict:
    if build.exists() or output.exists():
        raise ValueError("use unique build and output directories")
    probe_identity = admitted_probe(root, probe_report, probe)
    output.mkdir(parents=True)
    sources = identities(root)
    plugin = root / "build/sst/libspine_cycle.so"
    before = sha256_file(plugin)
    graph_path = root / "tests/data/shared_comparison/real_amazon_2008_compact.slice"
    report = {"schema_version": 1, "status": "running", "sources": sources, "runs": [], "cases": [],
        "graph": {"path": str(graph_path), "sha256": sha256_file(graph_path)},
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)), "probe": probe_identity,
        "hls_udf": {"path": str(reference), "sha256": sha256_file(reference)},
        "sssp_apply_schedule": apply_schedule(apply_solution),
        "memory": {"backend": "MockMemoryBackend_not_DRAMSim3_or_FPGA", "clock_mhz": 150,
            "outstanding_per_channel": 32, "response_credits_per_channel": 32, "issue_interval": 1,
            "latencies": list(LATENCIES)},
        "boundary": "resident_input_first_component_tick_to_all_state_write_acknowledgements_one_round",
        "model": {"a4_apply_post_read": [1, 1, 2], "a4_apply_response_anchored": True,
            "a4_axi_independent_read_write": False, "k4_axi_independent_read_write": True,
            "k4_profile_reference": "configs/architectures/grasu_regraph_routed_sssp_compute_v4.json",
            "k4_profile_sha256": sha256_file(root / "configs/architectures/grasu_regraph_routed_sssp_compute_v4.json")},
        "default_plugin_sha256_before": before,
        "not_claimed": ["published_speed_match", "FPGA_timing_match", "convergence_comparison",
            "equal_AXI_ports_or_state_copies_or_read_write_credits", "four_K4_workers_busy_on_single_partition"]}

    def execute(name: str, command: list[str], timeout: int = 180, expected_exit: int = 0) -> dict:
        row = run_bounded(command, cwd=root, prefix=output / "raw" / name,
                          timeout=timeout, memory_gib=8, reserve_gib=16)
        report["runs"].append(row)
        atomic_write_json(output / "results.json", report)
        if row["exit_code"] != expected_exit or row["timed_out"]:
            raise RuntimeError("bounded real-round control failed: " + name)
        return row

    try:
        execute("configure", ["cmake", "-S", str(root), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
                              "-DSPINE_SSSP_UDF_REFERENCE=" + str(reference)])
        report["cmake_cache"] = (build / "CMakeCache.txt").read_text()
        compiler = execute("compiler", ["g++", "--version"])
        report["compiler_version"] = Path(compiler["stdout"]).read_text()
        execute("build", ["cmake", "--build", str(build), "--target", *TARGETS, "-j", "2"], 900)
        report["binaries"] = [{"path": str(build / "cpp" / name), "sha256": sha256_file(build / "cpp" / name)}
                              for name in TARGETS]
        for name in SSSP_TARGETS:
            execute(name, [str(build / "cpp" / name)])
        report["legacy_components"] = verify_legacy(root, build, component_baseline,
            {"run_timeout_seconds": 180}, execute)
        report["legacy_whole"] = whole_regression(build, whole_baseline, output, execute)
        graph = load_slice(graph_path)
        topology_file = output / "topology.txt"
        with topology_file.open("x", encoding="ascii") as stream:
            for edge in graph.records:
                stream.write(f"{edge.src} {edge.dst}\n")
        inspected = inspect_graph(topology_file)
        contract = json.loads((root / "configs/experiments/original_regraph_inputs_v1.json").read_text())
        capture = output / "author_capture"
        capture.mkdir()
        row = execute("author_layout", [str(probe), str(topology_file), str(capture), str(contract["seed"]), "1"])
        layout = analyze_topology(Path(row["stdout"]).read_text(), capture, probe_identity, inspected, contract)
        report["layout"] = layout
        for mode in MODES:
            inputs = output / "inputs" / mode
            geometry = overlay(graph, capture, layout, inputs, mode)
            report.setdefault("inputs", []).append({**geometry, "path": str(inputs),
                "files": [{"path": str(p), "sha256": sha256_file(p)} for p in sorted(inputs.iterdir())]})
            if mode == "cold":
                rejected = output / "pr_rejection"
                rejected.mkdir()
                row = execute("pr_arithmetic_rejection", [str(build / "cpp/original_regraph_a4_execution"),
                    str(inputs), str(rejected), "2", "64", "0", "10000000"], expected_exit=1)
                diagnostic = "initial PR iteration exceeds original signed arithmetic domain"
                if diagnostic not in Path(row["stderr"]).read_text() or list(rejected.iterdir()):
                    raise ValueError("original PR arithmetic rejection no longer holds")
                report["pr_arithmetic_negative_control"] = {"diagnostic": diagnostic,
                    "original_pr_rejected_unchanged_capture": True, "sssp_has_separate_oracle": True}
            for latency in LATENCIES:
                for reverse in (0, 1):
                    label = f"{mode}_lat{latency}_reverse{reverse}"
                    states = output / "states" / label
                    states.mkdir(parents=True)
                    row = execute(label, [str(build / "cpp/original_regraph_sssp_real_round"),
                                  str(inputs), str(states), str(latency), str(reverse), "10000000"])
                    report["cases"].append({"mode": mode, "latency": latency, "reverse": reverse,
                        **admit_round(Path(row["stdout"]).read_text(), states, geometry)})
        report["admission"] = admit_matrix(report["cases"])
        if identities(root) != sources or sha256_file(plugin) != before:
            raise ValueError("source or frozen default plugin changed during study")
        if sha256_file(reference) != report["hls_udf"]["sha256"]:
            raise ValueError("HLS UDF changed during study")
        if admitted_probe(root, probe_report, probe) != probe_identity:
            raise ValueError("author-layout probe or dependency changed during study")
        if sha256_file(graph_path) != report["graph"]["sha256"]:
            raise ValueError("source graph changed during study")
        if apply_schedule(apply_solution) != report["sssp_apply_schedule"]:
            raise ValueError("local SSSP Apply schedule changed during study")
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
    for flag in ("build", "output", "component-baseline", "whole-baseline", "hls-udf", "probe-report", "probe", "apply-solution"):
        parser.add_argument("--" + flag, type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    report = run(root, args.build.resolve(), args.output.resolve(), args.component_baseline.resolve(),
                 args.whole_baseline.resolve(), args.hls_udf.resolve(), args.probe_report.resolve(), args.probe.resolve(),
                 args.apply_solution.resolve())
    print(json.dumps({"status": report["status"], "admission": report["admission"]}, sort_keys=True))


if __name__ == "__main__":
    main()
