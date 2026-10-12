"""Freeze, synthesize and test a bounded production directory cache."""

import argparse
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...empty_segment.production import require_report
from ...empty_segment.production import COMPILER, PLATFORM
from ...execution import identity
from ...routing import adapter_interface
from ..continuous_directory.study import ROOT, checked, verify_pins
from ..cross_row.study import compile_command
from ..cross_row.validation import FLAGS as V3_FLAGS
from ..probe import probe
from .contract import TILE_ROWS
from .validation import ALL_TRIALS, compare, functional, schedules

BENCH = "cpp/tests/routed_regraph/directory_tile_axi_tb.sv"


def run(integration, reference, output, vivado_bin, packet_pipeline=False, bank_stream=False, bank_lines=128):
    if bank_lines not in (128, 256) or (bank_lines != 128 and not bank_stream):
        raise ValueError("explicit bank-stream storage required")
    if bank_stream:
        packet_pipeline = True
    tile_rows = 1024 if packet_pipeline else TILE_ROWS
    bench = "cpp/tests/routed_regraph/packet_pipeline_axi_tb.sv" if packet_pipeline else BENCH
    trials = ALL_TRIALS + ([(1023, 1, 1, 64, 0), (1024, 2, 1, 64, 0),
                           (1025, 1, 1, 128, 1000)] if packet_pipeline else [])
    if bank_stream:
        bench = "cpp/tests/routed_regraph/bank_stream_axi_tb.sv"
        trials += [(257, 0, 3, 64, 0), (129, 0, 3, 128, 1000)]
    output.mkdir(parents=True, exist_ok=False)
    paths = [*sorted((integration / "kernels/pma_to_regraph_adapter").glob("*")),
             integration / "tests/pma_adapter_row_prefetch_tb.cpp",
             integration / "scripts/check_pma_adapter_cross_row.sh", integration / "scripts/env.sh",
             ROOT / bench, ROOT / "cpp/tests/routed_regraph/adapter_axi_tb.sv",
             *sorted(Path(__file__).parent.glob("*.py"))]
    owner = Path(__file__).parent.parents[1]
    for directory in (owner, owner / "adapter_axi", owner / "empty_segment",
                      owner / "row_line", owner / "row_line/cross_row",
                      owner / "row_line/continuous_directory"):
        paths.extend(sorted(directory.glob("*.py")))
    paths.append(ROOT / "spine_cycle_sim/experiments/campaign_runtime.py")
    paths = list(dict.fromkeys(paths))
    tools = [COMPILER, PLATFORM, *(vivado_bin / name for name in ("xvlog", "xelab", "xsim"))]
    pins = [identity(path) for path in (*paths, reference, *tools)]
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for path in paths:
            owner = "integration" if path.is_relative_to(integration) else "simulator"
            archive.add(path, arcname=str(Path(owner) / path.relative_to(integration if owner == "integration" else ROOT)))
    flags = V3_FLAGS | {"GRASU_REGRAPH_DIRECTORY_TILE_ROWS": str(tile_rows)}
    if packet_pipeline:
        flags["GRASU_REGRAPH_PACKET_PIPELINE"] = "1"
    if bank_stream:
        flags["GRASU_REGRAPH_BANK_STREAM"] = "1"
        if bank_lines != 128:
            flags["GRASU_REGRAPH_BANK_FIFO_LINES"] = str(bank_lines)
    build = output / "production"
    build.mkdir()
    command = compile_command(integration, build)
    for key, value in flags.items():
        if key not in V3_FLAGS:
            command.insert(command.index("-D_GTHREAD_USE_COND_INIT_FUNC"), f"-D{key}={value}")
    atomic_write_json(output / "manifest.json", {"pins": pins, "flags": flags, "command": command,
                      "claim": "production_HLS_extended_synthetic_AXI_RTL_not_FPGA"})
    checked(["bash", "scripts/check_pma_adapter_cross_row.sh", "--out-dir", str(output / "functional"),
             "--bank-stream-wide" if bank_lines == 256 else "--bank-stream" if bank_stream
             else "--packet-pipeline" if packet_pipeline else "--directory-tile"],
            integration, output / "functional", timeout=240)
    functional((output / "functional.stdout.txt").read_text(), packet_pipeline, bank_stream)
    verify_pins(pins)
    checked(command, build, build / "compile", timeout=1200, budget=8)
    candidate = build / "adapter.hw.xo"
    old_interface, old_flags = adapter_interface(reference)
    interface, observed = adapter_interface(candidate)
    if (old_interface != interface or {k: v for k, v in old_flags.items() if k.startswith("GRASU_")} != V3_FLAGS
            or {k: v for k, v in observed.items() if k.startswith("GRASU_")} != flags):
        raise ValueError("unchanged external ABI and exact candidate flags required")
    schedule = schedules(build / "build", packet_pipeline, bank_stream)
    arms = {arm: probe(ROOT, xo, output / arm, vivado_bin, bench=bench, trials=trials)
            for arm, xo in (("reference", reference), ("candidate", candidate))}
    comparison = compare(arms["reference"], arms["candidate"], tile_rows, trials, bank_stream)
    verify_pins(pins)
    reasons = [name for name, row in schedule.items() if row["ii"] != 1 or row["estimated_ns"] > row["target_ns"]]
    result = {"status": "SCHEDULE_REJECTED" if reasons else "HLS_SCHEDULE_PASS_NOT_BOARD",
              "tile_rows": tile_rows, "packet_pipeline": packet_pipeline,
              "reasons": reasons, "schedule": schedule, "hls": require_report(build),
              "arms": arms, "comparison": comparison, "xo": identity(candidate),
              "hardware_timing_admitted": False, "production_promotion": False}
    if bank_stream:
        result["bank_stream"] = True
        if bank_lines != 128:
            result["bank_fifo_lines"] = bank_lines
    atomic_write_json(output / "results.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "reference", "output", "vivado-bin"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--packet-pipeline", action="store_true")
    parser.add_argument("--bank-stream", action="store_true")
    parser.add_argument("--bank-lines", type=int, choices=(128, 256), default=128)
    args = parser.parse_args()
    try:
        result = run(**{name: path.resolve() if isinstance(path, Path) else path
                        for name, path in vars(args).items()})
        print(json.dumps({"status": result["status"]}), flush=True)
    except BaseException as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
