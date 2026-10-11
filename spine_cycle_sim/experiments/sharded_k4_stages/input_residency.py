"""Bounded opt-in initial-residency intervention; HLS and timing model unchanged."""

import argparse
import json
import math
import os
from pathlib import Path
import statistics

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import analyze_log, fields
from .board import board_lease, hardware_command, require_idle_board
from .dispatch_delivery import validate_sweep
from .dispatch_sweep import dispatch_metrics
from .execution import identity


ARMS = ("frozen", "off", "on")


def residency_record(log: str, *, enabled: bool, partitions: int) -> dict | None:
    records = [fields(line) for line in log.splitlines()
               if line.startswith("SHARDED_INPUT_RESIDENCY ")]
    if len(records) != int(enabled):
        raise ValueError("initial-residency record does not match the requested arm")
    if not enabled:
        return None
    record = records[0]
    if (set(record) != {"policy", "buffers", "bytes", "wall_ms", "event_ms", "boundary"}
            or record["policy"] != "premigrate"
            or record["boundary"] != "initial_setup_before_updates"
            or int(record["buffers"]) != partitions * 10 or int(record["bytes"]) <= 0):
        raise ValueError("invalid initial-residency scope or buffer geometry")
    result = {**record, "buffers": int(record["buffers"]), "bytes": int(record["bytes"])}
    for key in ("wall_ms", "event_ms"):
        result[key] = float(record[key])
        if not math.isfinite(result[key]) or result[key] <= 0:
            raise ValueError("invalid residency duration")
    return result


def summarize(attempts: list[dict]) -> dict:
    order = [(r, ARMS[(r + offset) % 3], False) for r in range(3) for offset in range(3)]
    order.append((3, "on", True))
    if [(a["repeat"], a["arm"], a["profiled"]) for a in attempts] != order:
        raise ValueError("residency control is incomplete or reordered")
    medians = []
    for arm in ARMS:
        rows = [a for a in attempts if a["arm"] == arm and not a["profiled"]]
        spans = [a["analysis"]["compute_span_ms"] for a in rows]
        setup = [a["residency"]["wall_ms"] for a in rows if a["residency"]]
        medians.append({"arm": arm, "compute_span_ms": statistics.median(spans),
                        "range_ms": [min(spans), max(spans)],
                        "initial_residency_wall_ms": statistics.median(setup) if setup else None})
    return {"status": "INPUT_RESIDENCY_FUNCTIONAL_PASS", "attempts": attempts, "medians": medians,
            "timing_fit_performed": False, "hardware_timing_admitted": False,
            "original_A4_match_admitted": False,
            "boundary": "resident_compute_kernel_span; initial residency separately recorded",
            "limits": ["initial migration is not free or a per-batch architectural speedup",
                       "three unprofiled repetitions per arm; profile is a separate diagnostic",
                       "kernel lifetimes include stream waits, not exclusive stage cycles"]}


def run_control(*, root: Path, integration: Path, reference: Path, campaign: Path) -> dict:
    validate_sweep(reference)
    manifest = json.loads((reference / "manifest.json").read_text())
    expected = json.loads((reference / "summary.json").read_text())["attempts"][0]
    pins = manifest["pins"] + json.loads((campaign / "build_sources.json").read_text())
    host = campaign / "host/sharded_k4_sssp_native_host"
    frozen = Path(manifest["pins"][2]["path"])
    gate = json.loads(Path(manifest["pins"][3]["path"]).read_text())
    xclbin = Path(gate["candidate"]["path"])
    config = root / "configs/experiments/sharded_k4_dispatch_trace_v1.ini"
    pins += [identity(host), identity(config), identity(Path(__file__))]
    if identity(xclbin) != gate["candidate"] or not all(identity(Path(p["path"])) == p for p in pins):
        raise ValueError("changed source, input or admitted bitstream")
    if any(key in os.environ for key in ("XRT_INI_PATH", "GRASU_SHARDED_PREMIGRATE_INPUTS")):
        raise ValueError("runtime intervention must not be inherited")
    if any((p / "xrt.ini").exists() for p in (integration, frozen.parent, host.parent)):
        raise ValueError("unexpected default runtime configuration")
    output = campaign / "control"
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "manifest.json", {
        "pins": pins, "reference": str(reference), "device_index": manifest["device_index"],
        "case": manifest["case"], "cpus": manifest["affinities"][0], "repeats": 3,
        "arms": list(ARMS), "profiled_arm": "on", "memory_limit_gib": 8, "reserve_gib": 16,
        "timeout_seconds": 600, "claim": "initial_residency_intervention_not_model_fit"})
    order = [(r, ARMS[(r + offset) % 3], False) for r in range(3) for offset in range(3)]
    order.append((3, "on", True))
    attempts = []
    with board_lease(manifest["device_index"]) as render:
        for repeat, arm, profiled in order:
            require_idle_board(render)
            name = "profiled_on" if profiled else f"r{repeat}_{arm}"
            directory = output / name
            directory.mkdir()
            command = ["taskset", "--cpu-list", ",".join(map(str, manifest["affinities"][0])),
                       "env", f"GRASU_SHARDED_PREMIGRATE_INPUTS={int(arm == 'on')}"]
            if profiled:
                command.append(f"XRT_INI_PATH={config}")
            command += hardware_command(integration, manifest["case"], frozen if arm == "frozen" else host,
                                        xclbin, directory / "board", manifest["device_index"], 600, "1")
            resources = run_bounded(command, directory, directory / "process",
                                    timeout=600, memory_gib=8, reserve_gib=16)
            attempt = {"repeat": repeat, "arm": arm, "profiled": profiled, "resources": resources}
            attempts.append(attempt)
            atomic_write_json(output / "attempts.json", attempts)
            if resources["exit_code"] or resources["timed_out"]:
                raise RuntimeError("residency intervention failed; partial attempt retained")
            log = (directory / "board/run.log").read_text()
            board = analyze_log(log, require_trace=True)
            result = identity(directory / "board/result.txt")
            if board["result"] != expected["analysis"]["result"] or result["sha256"] != expected["result"]["sha256"]:
                raise ValueError("intervention changed the full result or round geometry")
            initial = residency_record(log, enabled=arm == "on",
                                       partitions=int(board["result"]["destination_partitions"]))
            traces = [identity(p) for p in sorted(directory.glob("*.csv"))]
            if profiled and len(traces) < 2:
                raise ValueError("missing diagnostic runtime traces")
            attempt.update(analysis=board, result=result, residency=initial,
                           dispatch=dispatch_metrics(board), traces=traces)
            atomic_write_json(output / "attempts.json", attempts)
            print(f"{name} PASS compute_span_ms={board['compute_span_ms']:.6f} initial={initial}", flush=True)
    if not all(identity(Path(p["path"])) == p for p in pins):
        raise ValueError("pinned identity changed during intervention")
    summary = summarize(attempts)
    atomic_write_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    args = parser.parse_args()
    run_control(root=Path(__file__).resolve().parents[3], integration=args.integration.resolve(),
                reference=args.reference.resolve(), campaign=args.campaign.resolve())
