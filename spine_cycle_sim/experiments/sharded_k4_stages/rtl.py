"""Bounded RTL/C co-simulation gates for the unchanged adapter interface."""

from pathlib import Path
import re

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .execution import identity


def parse_cosim_report(path: Path) -> dict:
    text = path.read_text()
    lines = [line for line in text.splitlines() if "Verilog" in line and "Pass" in line]
    if len(lines) != 1:
        raise ValueError("one passing Verilog co-simulation summary required")
    columns = [column.strip() for column in lines[0].split("|") if column.strip()]
    if columns[:2] != ["Verilog", "Pass"]:
        raise ValueError("unexpected co-simulation report format")
    numbers = [int(value) for value in columns[2:] if re.fullmatch(r"[0-9]+", value)]
    if len(numbers) < 3:
        raise ValueError("latency columns missing")
    return {"status": "RTL_COSIM_PASS", "latency_min_cycles": numbers[0],
            "latency_avg_cycles": numbers[1], "latency_max_cycles": numbers[2],
            "raw_report": identity(path)}


def cosimulate(integration: Path, output: Path, *, mode: str = "weighted") -> dict:
    if mode not in ("weighted", "destination", "unit"):
        raise ValueError("unknown adapter ABI mode")
    output.mkdir(parents=True, exist_ok=False)
    names = ["kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp",
             "kernels/pma_to_regraph_adapter/row_prefetch.hpp",
             "tests/pma_adapter_cosim_tb.cpp", "tests/pma_adapter_cosim.tcl"]
    pins = [identity(integration / name) for name in names]
    atomic_write_json(output / "manifest.json", {"mode": mode, "source": pins,
                      "clock_mhz": 150, "target": "xcu55c-fsvh2892-2L-e",
                      "memory_limit_gib": 8, "reserve_gib": 16,
                      "claim": "RTL_C_simulation_under_HLS_memory_model_not_FPGA"})
    runs = {}
    for name, prefetch, stop in (("original", 0, 0), ("combined", 1, 1)):
        directory = output / name
        directory.mkdir()
        command = ["env", f"PMA_COSIM_OUT={directory}", f"PMA_COSIM_MODE={mode}",
                   f"PMA_COSIM_PREFETCH={prefetch}", f"PMA_COSIM_STOP={stop}",
                   "/data/yxx/tools/xilinx/Vitis_HLS/2024.1/bin/vitis_hls", "-f",
                   str(integration / "tests/pma_adapter_cosim.tcl")]
        resources = run_bounded(command, directory, directory / "cosim", timeout=1200,
                                memory_gib=8, reserve_gib=16)
        runs[name] = {"execution": resources}
        atomic_write_json(output / "attempts.json", runs)
        if resources["exit_code"] != 0:
            raise RuntimeError(f"{name} RTL gate failed; logs retained at {directory}")
        report = directory / "project/solution/sim/report/pma_to_regraph_adapter_cosim.rpt"
        runs[name]["analysis"] = parse_cosim_report(report)
        atomic_write_json(output / "attempts.json", runs)
        print(f"{mode} {name} RTL COSIM PASS", flush=True)
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise RuntimeError("co-simulation source changed during execution")
    summary = {"status": "RTL_COSIM_PASS_NOT_BOARD", "mode": mode, "source": pins, "runs": runs}
    atomic_write_json(output / "summary.json", summary)
    return summary
