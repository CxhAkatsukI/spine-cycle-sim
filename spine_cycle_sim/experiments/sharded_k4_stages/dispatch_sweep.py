"""Bounded CPU-affinity control of an unchanged, admitted FPGA compute path."""

import argparse
import json
import os
from pathlib import Path
import statistics

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import analyze_log
from .board import board_lease, hardware_command, require_idle_board
from .execution import identity


def dispatch_metrics(board: dict) -> dict:
    groups = []
    for stage in ("adapter", "gather"):
        keys = sorted({(e["round"], e["worker"]) for e in board["events"] if e["stage"] == stage})
        for round_id, worker in keys:
            events = sorted((e for e in board["events"] if
                             (e["stage"], e["round"], e["worker"]) == (stage, round_id, worker)),
                            key=lambda e: e["shard"])
            gaps = []
            for previous, current in zip(events, events[1:]):
                if current["start_ns"] < previous["end_ns"]:
                    raise ValueError("same-CU overlap in dispatch control")
                gaps.append({"partition": current["shard"],
                             "gap_ms": (current["start_ns"] - previous["end_ns"]) / 1e6,
                             "queued_before_previous_end": current["queued_ns"] <= previous["end_ns"],
                             "submit_after_previous_end_ms": max(0, current["submit_ns"] - previous["end_ns"]) / 1e6})
            groups.append({"stage": stage, "round": round_id, "worker": worker,
                           "first_duration_ms": (events[0]["end_ns"] - events[0]["start_ns"]) / 1e6,
                           "same_worker_gap_sum_ms": sum(g["gap_ms"] for g in gaps), "gaps": gaps})
    return {"compute_span_ms": board["compute_span_ms"], "groups": groups}


def validate_affinities(affinities: list[list[int]], allowed: set[int]) -> None:
    if len(affinities) != 3 or not all(affinities):
        raise ValueError("three nonempty CPU-affinity arms required")
    for cpus in affinities:
        if len(set(cpus)) != len(cpus) or not set(cpus) <= allowed:
            raise ValueError("CPU-affinity arm contains duplicate or unavailable CPUs")
    if not set(affinities[0]) < set(affinities[1]) < set(affinities[2]):
        raise ValueError("CPU-affinity arms must be strictly nested")


def run_sweep(*, integration: Path, reference: Path, output: Path,
              affinities: list[list[int]], device: int = 1) -> dict:
    validate_affinities(affinities, os.sched_getaffinity(0))
    manifest = json.loads((reference / "manifest.json").read_text())
    baseline = json.loads((reference / "summary.json").read_text())
    if (baseline["status"] != "PAIRED_BOARD_PASS" or not all(baseline["checks"].values())
            or manifest["case"]["algorithm"] != "weighted_sssp"
            or device != manifest["device_index"]):
        raise ValueError("same-board admitted paired SSSP reference required")
    pins = manifest["pins"] + [identity(reference / name) for name in ("manifest.json", "summary.json")]
    if not all(identity(Path(p["path"])) == p for p in pins):
        raise ValueError("frozen paired source/input/binary identity changed")
    expected = baseline["attempts"][0]
    host = Path(manifest["pins"][2]["path"])
    gate = json.loads(Path(manifest["pins"][3]["path"]).read_text())
    xclbin = Path(gate["candidate"]["path"])
    if identity(xclbin) != gate["candidate"]:
        raise ValueError("admitted candidate bitstream changed")
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "manifest.json", {
        "affinities": affinities, "pins": pins + [identity(Path(__file__))],
        "device_index": device, "case": manifest["case"], "repeats": 3,
        "order": "three_rotating_arms_each_repetition", "memory_limit_gib": 8,
        "reserve_gib": 16, "timeout_seconds": 600,
        "claim": "CPU_affinity_sensitivity_not_exclusive_stage_timing_or_model_calibration"})
    attempts = []
    with board_lease(device) as render:
        for repeat in range(3):
            for arm in [(repeat + offset) % 3 for offset in range(3)]:
                require_idle_board(render)
                name = f"r{repeat}_arm{arm}"
                command = ["taskset", "--cpu-list", ",".join(map(str, affinities[arm]))]
                command += hardware_command(integration, manifest["case"], host, xclbin,
                                            output / name, device, 600, "1")
                resources = run_bounded(command, integration, output / f"{name}_process",
                                        timeout=600, memory_gib=8, reserve_gib=16)
                attempt = {"repeat": repeat, "arm": arm, "resources": resources}
                attempts.append(attempt)
                atomic_write_json(output / "attempts.json", attempts)
                if resources["exit_code"] != 0:
                    raise RuntimeError("dispatch control failed; raw attempt retained")
                board = analyze_log((output / name / "run.log").read_text(), require_trace=True)
                result = identity(output / name / "result.txt")
                if board["result"] != expected["analysis"]["result"] or result["sha256"] != expected["result"]["sha256"]:
                    raise ValueError("dispatch control changed complete result or round geometry")
                attempt.update(analysis=board, result=result, dispatch=dispatch_metrics(board))
                atomic_write_json(output / "attempts.json", attempts)
                print(f"{name} PASS compute_span_ms={board['compute_span_ms']:.6f}", flush=True)
    if not all(identity(Path(p["path"])) == p for p in pins):
        raise ValueError("frozen identity changed during dispatch control")
    summary = {"status": "DISPATCH_AFFINITY_CONTROL_FUNCTIONAL_PASS", "attempts": attempts,
               "medians_ms": [{"arm": arm, "cpus": cpus, "compute_span_ms": statistics.median(
                   a["analysis"]["compute_span_ms"] for a in attempts if a["arm"] == arm)}
                   for arm, cpus in enumerate(affinities)],
               "root_cause_proven": False, "hardware_timing_admitted": False,
               "timing_fit_performed": False}
    atomic_write_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpus", action="append", required=True)
    parser.add_argument("--device", type=int, default=1)
    args = parser.parse_args()
    run_sweep(integration=args.integration.resolve(), reference=args.reference.resolve(),
              output=args.output.resolve(), affinities=[list(map(int, arm.split(","))) for arm in args.cpus],
              device=args.device)
