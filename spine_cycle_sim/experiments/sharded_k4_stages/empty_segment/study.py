"""Bounded paired production-HLS gates; no route or timing-model changes."""

import argparse
import json
from pathlib import Path
import shutil
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from ..execution import identity
from ..link_runtime import run_link
from .analysis import analyze

HLS_FILES = ("kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp",
             "kernels/pma_to_regraph_adapter/row_prefetch.hpp",
             "tests/pma_adapter_cosim_tb.cpp", "tests/pma_adapter_cosim.tcl")


def study(integration: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[4]
    sources = [(integration / name, "integration/" + name) for name in HLS_FILES]
    sources += [(path, "simulator/" + str(path.relative_to(root)))
                for path in sorted(Path(__file__).parent.glob("*.py"))]
    sources += [(root / name, "simulator/" + name) for name in (
        "spine_cycle_sim/experiments/sharded_k4_stages/link_runtime.py",
        "spine_cycle_sim/experiments/sharded_k4_stages/process_cleanup.py",
        "spine_cycle_sim/experiments/sharded_k4_stages/execution.py",
        "spine_cycle_sim/experiments/sharded_k4_stages/rtl.py",
        "spine_cycle_sim/experiments/campaign_runtime.py",
        "spine_cycle_sim/experiments/upstream_controls/execution.py")]
    pins = [{"archive_path": name, **identity(path)} for path, name in sources]
    for path, name in sources:
        destination = output / "sources" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    manifest = {"source": pins, "clock_mhz": 150, "part": "xcu55c-fsvh2892-2L-e",
                "variants": {"combined": 0, "skip_empty": 1},
                "row_prefetch": 1, "stop_after_last": 1,
                "claim": "paired_C_RTL_scheduling_control_not_FPGA_or_original_A4_matching"}
    atomic_write_json(output / "manifest.json", manifest)
    report = {"status": "running", "manifest": manifest, "runs": {}}
    atomic_write_json(output / "results.json", report)
    try:
        for name, skip in manifest["variants"].items():
            directory = output / name
            directory.mkdir()
            command = ["env", f"PMA_COSIM_OUT={directory}", "PMA_COSIM_MODE=weighted",
                       "PMA_COSIM_PREFETCH=1", "PMA_COSIM_STOP=1",
                       f"PMA_COSIM_SKIP_EMPTY={skip}",
                       "/data/yxx/tools/xilinx/Vitis_HLS/2024.1/bin/vitis_hls", "-f",
                       str(integration / "tests/pma_adapter_cosim.tcl")]
            execution = run_bounded(command, directory, directory / "cosim", timeout=1200,
                                    memory_gib=8, reserve_gib=16)
            report["runs"][name] = {"execution": execution}
            atomic_write_json(output / "results.json", report)
            if execution["exit_code"] or execution["timed_out"]:
                raise RuntimeError(f"{name} C/RTL process gate failed; raw evidence retained")
            report["runs"][name]["analysis"] = analyze(directory)
            atomic_write_json(output / "results.json", report)
            print(name, "C_RTL_PASS", flush=True)
        if any(identity(Path(pin["path"])) != {k: v for k, v in pin.items() if k != "archive_path"}
               for pin in pins):
            raise ValueError("source changed during paired study")
        report.update({"status": "passed_paired_C_RTL_not_board",
                       "timing_fit_performed": False, "simulator_modified": False,
                       "hardware_timing_admitted": False, "original_A4_match_admitted": False})
    except Exception as error:
        report.update({"status": "failed", "error": str(error)})
        atomic_write_json(output / "results.json", report)
        raise
    atomic_write_json(output / "results.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    integration, output = args.integration.resolve(), args.output.resolve()
    if args.worker:
        print(json.dumps({"status": study(integration, output)["status"]}))
        return
    if output.exists():
        raise FileExistsError("use a fresh paired-study output")
    command = [sys.executable, "-m", __package__ + ".study", "--worker",
               "--integration", str(integration), "--output", str(output)]
    resource = run_link(command, Path.cwd(), output.with_name(output.name + "_watchdog"),
                        timeout=2700, tree_memory_gib=8, reserve_gib=16)
    print(json.dumps(resource, sort_keys=True))
    if resource["exit_code"] or resource["stop_reason"] != "process_exit":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
