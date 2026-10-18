"""Admit true-convergence G+R FullPR without reusing the legacy three-round result."""

import json
import math
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from spine_cycle_sim.experiments.sharded_k4_stages.analysis import analyze_log
from .. import analysis, board_preparation, board_protocol, preparation
from ..board_analysis import BOUNDARY, single
from . import gr_preparation, inputs

PASS = "GR_FULLPR_RESIDENT_CONVERGENCE_PASS_NOT_PAIRED_OR_PUBLICATION_MATCH"


def prepare(preflight, admission, algorithm):
    if algorithm != inputs.ALGORITHM:
        raise ValueError("FullPR-only protocol")
    report_path = preflight / "results.json"
    report = json.loads(report_path.read_text())
    cohort = gr_preparation.replay(report, preflight)
    checked = json.loads(admission.read_text())
    if checked.get("status") != "ALGORITHM_ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD" or \
            checked.get("algorithm") != inputs.ALGORITHM or checked.get("errors", []) or \
            any(checked.get(key, False) is not False for key in ("board_admitted", "publication_match", "rtl_admitted")):
        raise ValueError("strict new-production FullPR routed admission required")
    # The FullPR fork changes host convergence, not kernels. Prove that against
    # the routed revision instead of requiring equal host and kernel commit IDs.
    subprocess.run(["git", "diff", "--exit-code", checked["integration_revision"], report["source_revision"],
                    "--", "kernels", "include"], cwd=report["source_root"], check=True, capture_output=True)
    guard = preflight / "source/tools/weighted_pma_native_host.cpp"
    code = guard.read_text()
    if 'std::getenv("GRASU_REGRAPH_EXPECT_BDF")' not in code or "CL_DEVICE_PCIE_BDF" not in code or \
            code.index("CL_DEVICE_PCIE_BDF") > code.index("return device;", code.index("select_xilinx_device()")):
        raise ValueError("pre-context FullPR PCIe lease guard required")
    binary = preflight / inputs.ALGORITHM
    if not any(pin["path"] == str(binary) for pin in report["pins"]):
        raise ValueError("FullPR preflight binary not frozen")
    pins = board_preparation.stamp_pins([*report["pins"], *checked["pins"], checked["candidate"],
            checked["timing"]["report"], preparation.identity(report_path), preparation.identity(admission)])
    if bitstream.parse_routed_timing(Path(checked["timing"]["report"]["path"])) != checked["timing"]:
        raise ValueError("FullPR routed timing changed")
    return {"algorithm": algorithm, "binary": str(binary), "candidate": checked["candidate"],
            "host_revision": report["source_revision"], "kernel_revision": checked["integration_revision"],
            "rows": cohort["rows"], "smoke": cohort["smoke"], "pins": pins, "artifact_admission": checked}


def command(plan, row, result):
    return [plan["binary"], plan["candidate"]["path"], row["graph"], str(result), "--resident-fullpr"]


def analyze(row, stdout, stderr, *, bdf):
    if stderr.strip():
        raise ValueError("unexpected FullPR runtime diagnostic")
    lines = stdout.splitlines()
    prefix = gr_preparation.PREFIX
    initial, result, timing = (single(lines, prefix + suffix) for suffix in ("_INPUT", "_RESULT", "_TIMING"))
    if single(lines, "GRASU_REGRAPH_DEVICE") != {"bdf": bdf} or \
            single(lines, "GRASU_SHARDED_UPDATE_REPEAT_CONFIG") != {
                "repeats": "1", "restore_pma_between_repeats": "1"}:
        raise ValueError("FullPR leased device or one-batch scope differs")
    gr_preparation.geometry(row, initial)
    expected = {"status": "PASS", "rank_mismatches": "0", "degree_mismatches": "0",
        "hardware_converged": "1", "convergence": "global_l1", "resident_state": "old_graph_converged",
        "boundary": BOUNDARY, "conversion_cost": "absent", "k4_frontends": "4", "shared_regraph_downstream": "1"}
    if any(result.get(key) != value for key, value in expected.items()) or float(result["epsilon"]) != 1e-6:
        raise ValueError("true-convergence FullPR old-state, result or timing boundary differs")
    for key in ("vertices", "logical_updates", "physical_updates", "destination_partitions", "final_edges", "pma_slots_total"):
        if int(result[key]) != int(initial[key]):
            raise ValueError("FullPR result workload differs")
    if int(result["processed_edge_slots_per_execution"]) != int(initial["pma_slots_total"]):
        raise ValueError("FullPR complete PMA scan conservation failed")
    rounds = int(result["pipeline_executions"])
    if not 1 <= rounds <= 256 or int(result["rounds"]) != rounds or (row["dataset"] == "SMOKE" and rounds <= 3):
        raise ValueError("FullPR rounds invalid; smoke must exceed legacy three-round limit")
    error, total, mass = (float(result[key]) for key in ("max_abs_error", "final_l1_error", "probability_mass"))
    if any(not math.isfinite(value) for value in (error, total, mass)) or \
            not 0 <= error <= 2e-5 or not 0 <= total <= 2e-4 or abs(mass - 1) > 1e-3:
        raise ValueError("FullPR final CPU-reference or probability-mass gate failed")
    sweeps = [analysis.fields(line) for line in lines if line.startswith(prefix + "_ROUND ")]
    if len(sweeps) != rounds:
        raise ValueError("one FullPR convergence record per sweep required")
    for index, sweep in enumerate(sweeps):
        delta, dangling = float(sweep["l1_error"]), float(sweep["dangling"])
        if set(sweep) != {"round", "l1_error", "dangling", "active_vertices"} or \
                int(sweep["round"]) != index + 1 or not 0 <= int(sweep["active_vertices"]) <= row["vertices"] or \
                not math.isfinite(delta) or delta < 0 or not math.isfinite(dangling) or dangling < 0 or \
                ((delta <= 1e-6) != (index == rounds - 1)):
            raise ValueError("FullPR sweep order or first-convergence rule failed")
    values = {key: float(value) for key, value in timing.items()}
    if any(not math.isfinite(value) or value < 0 for value in values.values()) or \
            not 0 < values["device_e2e_ms"] <= values["setup_inclusive_ms"] + .001:
        raise ValueError("FullPR finite device/wall timing required")
    for line in lines:
        if line.startswith("SHARDED_DEVICE_EVENT ") and set(analysis.fields(line)) != {
                "stage", "round", "shard", "worker", "queued_ns", "submit_ns", "start_ns", "end_ns"}:
            raise ValueError("exact FullPR device-event fields required")
    traced = analyze_log(stdout, require_trace=True)
    if traced["compute_span_ms"] > values["device_e2e_ms"] + .001:
        raise ValueError("FullPR compute events exceed device span")
    return {"status": "PASS", "dataset": row["dataset"], "algorithm": inputs.ALGORITHM, "boundary": BOUNDARY,
            "resident_wall_ms": values["setup_inclusive_ms"], "iterations": rounds,
            "last_iteration_l1_delta": float(sweeps[-1]["l1_error"]), "final_cpu_reference_l1_error": total,
            "input": initial, "result": result, "timing_ms": values, "compute_timeline": traced,
            "limits": ["kernel event spans include stalls/overlap; not exclusive ten-stage counters",
                       "three complete inputs, not compact FPGA or the eight-graph differential matrix",
                       "not a paired speedup or original-publication performance match"]}


def experiment():
    return board_protocol.Experiment("new_production_gr_fullpr_resident", BOUNDARY, PASS,
        prepare, command, analyze, board_protocol.gr_environment)
