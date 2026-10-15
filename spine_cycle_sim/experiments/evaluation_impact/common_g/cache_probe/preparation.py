"""Freeze the probe and unchanged original update implementation."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..study import ROOT

ARMS = ("original", "lane_wiring", "registered_wiring")
FULL_ARM = "original_full"
FULL_ARMS = (FULL_ARM, "registered_full")


def prepare(output: Path, upstream: Path):
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    source.mkdir()
    (source / "upstream").mkdir()
    for name in ("cache_bank.cpp", "cache_bank.hpp", "cache_bank_control.cpp",
                 "cache_lane.hpp", "cache_pipeline.hpp", "cache_full.cpp", "cache_full_control.cpp"):
        shutil.copy2(ROOT / "cpp/tests/evaluation_impact/common_g/hls" / name, source / name)
    for name in ("kernel_process_cache.cpp", "kernel_config.h"):
        shutil.copy2(upstream / name, source / "upstream" / name)
    runner = source / "runner"
    runner.mkdir()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        shutil.copy2(path, runner / path.name)
    for path in (ROOT / "spine_cycle_sim/experiments/upstream_controls/execution.py",
                 ROOT / "spine_cycle_sim/experiments/campaign_runtime.py"):
        shutil.copy2(path, runner / path.name)
    return [{"path": str(path), "sha256": sha256_file(path)}
            for path in sorted(source.rglob("*")) if path.is_file()]


def tcl(arm: str):
    if arm not in (*ARMS, *FULL_ARMS):
        raise ValueError("unknown cache-bank arm")
    flags = "-D_GTHREAD_USE_COND_INIT_FUNC -I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc"
    if arm == "lane_wiring":
        flags += " -DCACHE_BANK_CANDIDATE"
    elif arm in ("registered_wiring", "registered_full"):
        flags += " -DCACHE_BANK_REGISTERED"
    top = "cache_full_probe" if arm in FULL_ARMS else "cache_bank_probe"
    kernel = "cache_full.cpp" if arm in FULL_ARMS else "cache_bank.cpp"
    control = "cache_full_control.cpp" if arm in FULL_ARMS else "cache_bank_control.cpp"
    return f'''open_project -reset project
set_top {top}
add_files ../source/{kernel} -cflags {{{flags}}}
add_files -tb ../source/{control} -cflags {{{flags}}}
open_solution -reset solution -flow_target vitis
set_part {{xcu55c-fsvh2892-2L-e}}
create_clock -period 5 -name default
config_rtl -deadlock_detection sim
csim_design
csynth_design
cosim_design -rtl verilog -tool xsim
exit
'''
