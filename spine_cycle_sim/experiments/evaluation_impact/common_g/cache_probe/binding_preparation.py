"""Freeze the shared full cache core, production wrapper and old routed ABI."""

import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..study import ROOT
from ..complete_pipeline.delivery import PASS, validate


def prepare(output: Path, basis: Path, production: Path, reference: Path):
    report_path = basis / "results.json"
    report = json.loads(report_path.read_text())
    if report["status"] != PASS:
        raise ValueError("passing full-capacity source composition required")
    validate(basis, report)
    hls = ROOT / "cpp/tests/evaluation_impact/common_g/hls"
    shared = ("cache_pipeline.hpp", "cache_lane.hpp", "cache_bank.hpp")
    for name in shared:
        if sha256_file(hls / name) != sha256_file(basis / "source/hls" / name):
            raise ValueError("shared cache implementation differs from source controls")
    if sha256_file(production / "kernel_config.h") != sha256_file(basis / "source/integration/kernel_config.h"):
        raise ValueError("production cache configuration changed")
    output.mkdir(parents=True, exist_ok=False)
    groups = {"source": [*(hls / name for name in shared), hls / "cache_binding.cpp",
                          hls / "cache_full_control.cpp"],
              "source/upstream": [production / "kernel_config.h"],
              "reference": [reference / "impl/kernel/kernel.xml", reference / "impl/ip/component.xml"]}
    runner = sorted(Path(__file__).parent.glob("*.py")) + [
        ROOT / "spine_cycle_sim/experiments/campaign_runtime.py",
        ROOT / "spine_cycle_sim/experiments/upstream_controls/execution.py",
        *(Path(__file__).parent.parent / "search_pipeline").glob("*.py"),
        Path(__file__).parent.parent / "search_binding/abi.py",
        *(Path(__file__).parent.parent / "complete_pipeline").glob("*.py"),
    ]
    for path in runner:
        groups.setdefault("runner/" + path.parent.relative_to(ROOT).as_posix(), []).append(path)
    pins = []
    for group, paths in groups.items():
        target = output / group
        target.mkdir(parents=True, exist_ok=True)
        for path in paths:
            frozen = target / path.name
            shutil.copy2(path, frozen)
            digest = sha256_file(frozen)
            if sha256_file(path) != digest:
                raise ValueError("cache binding input changed during freeze")
            pins.append({"original_path": str(path), "path": str(frozen), "sha256": digest})
    frozen_report = output / "basis.json"
    shutil.copy2(report_path, frozen_report)
    if sha256_file(frozen_report) != sha256_file(report_path):
        raise ValueError("source composition report changed during freeze")
    pins.append({"original_path": str(report_path), "path": str(frozen_report),
                 "sha256": sha256_file(frozen_report)})
    return pins


def tcl():
    flags = ("-DCACHE_BANK_REGISTERED -DCACHE_PRODUCTION_BINDING -DGRASU_ENABLE_COMPLETION_TOKEN "
             "-D_GTHREAD_USE_COND_INIT_FUNC -I/data/yxx/tools/xilinx/Vitis_HLS/2024.1/include/etc")
    return f'''open_project -reset project
set_top process_cache
add_files ../source/cache_binding.cpp -cflags {{{flags}}}
add_files -tb ../source/cache_full_control.cpp -cflags {{{flags}}}
open_solution -reset solution -flow_target vitis
set_part {{xcu55c-fsvh2892-2L-e}}
create_clock -period 5 -name default
config_rtl -deadlock_detection sim
csim_design
csynth_design
cosim_design -rtl verilog -tool xsim
export_design -format xo -output process_cache.hw.xo
exit
'''
