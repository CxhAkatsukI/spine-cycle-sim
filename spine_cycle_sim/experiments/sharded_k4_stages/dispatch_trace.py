"""Opt-in runtime tracing of the frozen WK board path, never a timing fit."""

import argparse
import json
import os
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import analyze_log
from .board import board_lease, hardware_command, require_idle_board
from .dispatch_delivery import validate_sweep
from .dispatch_sweep import dispatch_metrics
from .execution import identity


def run_trace(*, root: Path, integration: Path, reference: Path, output: Path) -> dict:
    _, _ = validate_sweep(reference)
    manifest = json.loads((reference / "manifest.json").read_text())
    baseline = json.loads((reference / "summary.json").read_text())["attempts"][0]
    if os.environ.get("XRT_INI_PATH"):
        raise ValueError("inherited XRT_INI_PATH must not alter the unprofiled control")
    host = Path(manifest["pins"][2]["path"])
    if (host.parent / "xrt.ini").exists() or (integration / "xrt.ini").exists():
        raise ValueError("unexpected default XRT settings beside host or in integration directory")
    gate = json.loads(Path(manifest["pins"][3]["path"]).read_text())
    xclbin = Path(gate["candidate"]["path"])
    config = root / "configs/experiments/sharded_k4_dispatch_trace_v1.ini"
    pins = manifest["pins"] + [identity(config), identity(Path(__file__))]
    xrt = Path("/opt/xilinx/xrt")
    for leaf in ("lib/libxilinxopencl.so.2.18.179", "lib/libxrt_core.so.2.18.179",
                 "lib/libxrt_coreutil.so.2.18.179"):
        pins.append(identity(xrt / leaf))
    output.mkdir(parents=True, exist_ok=False)
    version = subprocess.run([str(xrt / "bin/xbutil"), "--version"],
                             capture_output=True, text=True, check=True, timeout=10)
    atomic_write_json(output / "manifest.json", {
        "pins": pins, "reference": str(reference), "device_index": manifest["device_index"],
        "cpus": manifest["affinities"][0], "case": manifest["case"],
        "runtime_version": {"stdout": version.stdout, "stderr": version.stderr},
        "arms": ["unprofiled", "profiled"], "memory_limit_gib": 8, "reserve_gib": 16,
        "timeout_seconds": 600, "claim": "perturbed_runtime_diagnostic_not_performance_measurement"})
    attempts = []
    with board_lease(manifest["device_index"]) as render:
        for arm in ("unprofiled", "profiled"):
            require_idle_board(render)
            directory = output / arm
            directory.mkdir()
            command = ["taskset", "--cpu-list", ",".join(map(str, manifest["affinities"][0]))]
            if arm == "profiled":
                command += ["env", f"XRT_INI_PATH={config}"]
            command += hardware_command(integration, manifest["case"], host, xclbin,
                                        directory / "board", manifest["device_index"], 600, "1")
            resources = run_bounded(command, directory, directory / "process",
                                    timeout=600, memory_gib=8, reserve_gib=16)
            attempt = {"arm": arm, "resources": resources}
            attempts.append(attempt)
            atomic_write_json(output / "attempts.json", attempts)
            if resources["exit_code"] or resources["timed_out"]:
                raise RuntimeError("trace diagnostic failed; partial attempt retained")
            board = analyze_log((directory / "board/run.log").read_text(), require_trace=True)
            result = identity(directory / "board/result.txt")
            if (board["result"] != baseline["analysis"]["result"]
                    or result["sha256"] != baseline["result"]["sha256"]):
                raise ValueError("trace changed the full result or resident round count")
            traces = [identity(p) for p in sorted(directory.glob("*.csv"))]
            if arm == "profiled" and not traces:
                raise ValueError("no runtime trace was emitted")
            attempt.update(analysis=board, result=result, dispatch=dispatch_metrics(board), traces=traces)
            atomic_write_json(output / "attempts.json", attempts)
            print(f"{arm} PASS compute_span_ms={board['compute_span_ms']:.6f} csv_files={len(traces)}", flush=True)
    if not all(identity(Path(pin["path"])) == pin for pin in pins):
        raise ValueError("trace source/input/binary/runtime identity changed")
    summary = {"status": "RUNTIME_TRACE_FUNCTIONAL_PASS", "attempts": attempts,
               "hardware_timing_admitted": False, "root_cause_proven": False,
               "timing_fit_performed": False,
               "limits": ["profiler perturbs scheduling; not a new performance measurement",
                          "host API/HAL trace does not expose exclusive hardware stages or AXI stalls",
                          "one execution per arm; only a dispatch diagnostic"]}
    atomic_write_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_trace(root=Path(__file__).resolve().parents[3], integration=args.integration.resolve(),
              reference=args.reference.resolve(), output=args.output.resolve())
