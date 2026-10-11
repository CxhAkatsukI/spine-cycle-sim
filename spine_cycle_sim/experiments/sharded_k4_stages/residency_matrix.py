"""Repeat every fixed v4 model row on FPGA with explicit initial residency."""

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
from .input_residency import residency_record


def matrix_order() -> list[tuple[int, str, str]]:
    rows = [(graph, arm) for graph in ("au", "su", "wk") for arm in ("candidate", "original")]
    return [(r, *rows[(offset + r) % 6]) for r in range(3) for offset in range(6)]


def summarize_matrix(attempts: list[dict], predictions: dict) -> dict:
    if [(a["repeat"], a["graph"], a["arm"]) for a in attempts] != matrix_order():
        raise ValueError("resident matrix has missing or reordered rows")
    rows = []
    for graph in ("au", "su", "wk"):
        for arm in ("candidate", "original"):
            selected = [a for a in attempts if (a["graph"], a["arm"]) == (graph, arm)]
            spans = [a["analysis"]["compute_span_ms"] for a in selected]
            measured = statistics.median(spans)
            predicted = predictions[f"{graph}_{arm}"]
            rows.append({"id": f"{graph}_{arm}", "predicted_no_host_ms": predicted,
                         "median_board_compute_span_ms": measured, "range_ms": [min(spans), max(spans)],
                         "nominal_signed_error_percent": 100 * (predicted / measured - 1),
                         "median_initial_residency_ms": statistics.median(a["residency"]["wall_ms"] for a in selected)})
    return {"status": "RESIDENT_MATRIX_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC", "rows": rows,
            "attempts": attempts, "timing_fit_performed": False, "hardware_timing_admitted": False,
            "original_A4_match_admitted": False,
            "limits": ["model unchanged; dispatch/relaunch/inter-round gaps still absent from predictions",
                       "actual physical DRAM mapping and exclusive stages are not calibrated",
                       "initial whole-graph migration is separately timed, not free per-batch work",
                       "three warm-SSSP graph cases do not establish other-algorithm or A4 matches"]}


def run_matrix(*, root: Path, integration: Path, control: Path, output: Path) -> dict:
    prior = json.loads((control / "summary.json").read_text())
    control_manifest = json.loads((control / "manifest.json").read_text())
    if prior["status"] != "INPUT_RESIDENCY_FUNCTIONAL_PASS":
        raise ValueError("passing WK intervention required")
    host = control.parent / "host/sharded_k4_sssp_native_host"
    config = root / "configs/experiments/sharded_k4_routed_sssp_timing_v1.json"
    frozen = root / ("docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/"
                     "model_sync/sst/empty_exit_matrix/matrix.json")
    model = json.loads(frozen.read_text())
    predictions = {r["id"]: r["timing"]["predicted_no_host_ms"] for r in model["rows"]}
    pins = control_manifest["pins"] + [identity(config), identity(frozen), identity(Path(__file__))]
    pins += [identity(control / name) for name in ("manifest.json", "summary.json")]
    cases = {}
    for case in json.loads(config.read_text())["cases"]:
        directory = Path(case["board_pair"])
        for leaf in ("manifest.json", "summary.json"):
            pins.append(identity(directory / leaf))
        manifest = json.loads((directory / "manifest.json").read_text())
        baseline = json.loads((directory / "summary.json").read_text())
        gate = json.loads(Path(manifest["pins"][3]["path"]).read_text())
        if baseline["status"] != "PAIRED_BOARD_PASS" or not all(baseline["checks"].values()):
            raise ValueError("admitted paired graph reference required")
        pins += manifest["pins"]
        cases[case["id"]] = {"case": manifest["case"], "gate": gate, "baseline": baseline}
    if not all(identity(Path(p["path"])) == p for p in pins):
        raise ValueError("resident matrix pinned identity changed")
    if any(key in os.environ for key in ("XRT_INI_PATH", "GRASU_SHARDED_PREMIGRATE_INPUTS")):
        raise ValueError("runtime settings must not be inherited")
    if any((p / "xrt.ini").exists() for p in (host.parent, integration)):
        raise ValueError("unexpected default runtime settings")
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "manifest.json", {
        "pins": pins, "predictions_ms": predictions, "order": matrix_order(), "repeats": 3,
        "device_index": 1, "cpus": control_manifest["cpus"], "cases": cases,
        "memory_limit_gib": 8, "reserve_gib": 16, "timeout_seconds": 600,
        "claim": "all_six_fixed_model_rows_after_initial_residency_no_fit"})
    attempts = []
    with board_lease(1) as render:
        for repeat, graph, arm in matrix_order():
            require_idle_board(render)
            case = cases[graph]
            directory = output / f"r{repeat}_{graph}_{arm}"
            directory.mkdir()
            command = ["taskset", "--cpu-list", ",".join(map(str, control_manifest["cpus"])),
                       "env", "GRASU_SHARDED_PREMIGRATE_INPUTS=1"]
            command += hardware_command(integration, case["case"], host, Path(case["gate"][arm]["path"]),
                                        directory / "board", 1, 600, "1")
            resources = run_bounded(command, directory, directory / "process",
                                    timeout=600, memory_gib=8, reserve_gib=16)
            attempt = {"repeat": repeat, "graph": graph, "arm": arm, "resources": resources}
            attempts.append(attempt)
            atomic_write_json(output / "attempts.json", attempts)
            if resources["exit_code"] or resources["timed_out"]:
                raise RuntimeError("resident matrix failed; raw attempt retained")
            log = (directory / "board/run.log").read_text()
            board = analyze_log(log, require_trace=True)
            result = identity(directory / "board/result.txt")
            expected = next(a for a in case["baseline"]["attempts"] if a["arm"] == arm)
            if board["result"] != expected["analysis"]["result"] or result["sha256"] != expected["result"]["sha256"]:
                raise ValueError("resident matrix full result or round geometry changed")
            initial = residency_record(log, enabled=True, partitions=int(board["result"]["destination_partitions"]))
            attempt.update(analysis=board, result=result, residency=initial)
            atomic_write_json(output / "attempts.json", attempts)
            print(f"r{repeat}_{graph}_{arm} PASS compute_span_ms={board['compute_span_ms']:.6f}", flush=True)
    if not all(identity(Path(p["path"])) == p for p in pins):
        raise ValueError("pinned identity changed during resident matrix")
    summary = summarize_matrix(attempts, predictions)
    atomic_write_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_matrix(root=Path(__file__).resolve().parents[3], integration=args.integration.resolve(),
               control=args.control.resolve(), output=args.output.resolve())
