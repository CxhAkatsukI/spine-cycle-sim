"""Freeze real upstream, integration and candidate sources before execution."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..study import ROOT
from .analysis import SEARCH_MODES

ADAPTERS = ("resident", "bank_stream")
BANK_FLAGS = ("ROW_PREFETCH", "ROW_LINE_READ", "STOP_AFTER_LAST", "SKIP_EMPTY_SEGMENT",
              "CROSS_ROW_PIPELINE", "PACKET_PIPELINE", "BANK_STREAM")


def prepare(output: Path, upstream: Path, integration: Path, *, search_mode="pristine"):
    if search_mode not in SEARCH_MODES:
        raise ValueError("undeclared search mode")
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    groups = {
        "upstream": [upstream / name for name in
                     ("kernel_config.h", "kernel_bin_search.cpp", "kernel_process_cache.cpp")],
        "integration": [integration / "include/weighted_pma_graph.hpp",
                        integration / "repos/GraSU/GraSU/GraSU_kernels/src/kernel_config.h",
                        integration / "repos/GraSU/GraSU/GraSU_kernels/src/kernel_dispatch.cpp"],
        "adapter": sorted((integration / "kernels/pma_to_regraph_adapter").glob("*.hpp")) +
                   [integration / "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp"],
        "": list((ROOT / "cpp/tests/evaluation_impact/common_g/weighted_abi").glob("*.*")) +
            [ROOT / "cpp/tests/evaluation_impact/common_g/hls" / name for name in
             ("cache_bank.hpp", "cache_lane.hpp")],
        "runner": list(Path(__file__).parent.glob("*.py")) +
                  [ROOT / "spine_cycle_sim/experiments/upstream_controls/execution.py",
                   ROOT / "spine_cycle_sim/experiments/campaign_runtime.py"],
    }
    if search_mode == "finite_pipeline":
        groups["search_pipeline"] = sorted(
            (ROOT / "cpp/tests/evaluation_impact/common_g/hls/search_pipeline").glob("*.hpp")) + [
                ROOT / "cpp/tests/evaluation_impact/common_g/hls/search_pipeline/top.cpp"]
    pins = []
    for group, paths in groups.items():
        target = source / group
        target.mkdir(parents=True, exist_ok=True)
        for path in paths:
            frozen = target / path.name
            shutil.copy2(path, frozen)
            pins.append({"original": str(path), "path": str(frozen), "sha256": sha256_file(frozen)})
    return pins


def command(source: Path, include: Path, adapter: str, compiler: str, binary: Path,
            *, search_mode="pristine"):
    if adapter not in ADAPTERS:
        raise ValueError("undeclared adapter")
    if search_mode not in SEARCH_MODES:
        raise ValueError("undeclared search mode")
    flags = []
    if adapter == "bank_stream":
        flags = [f"-DGRASU_REGRAPH_{name}=1" for name in BANK_FLAGS]
        flags += ["-DGRASU_REGRAPH_DIRECTORY_TILE_ROWS=1024", "-DGRASU_REGRAPH_BANK_FIFO_LINES=256"]
    if search_mode == "finite_pipeline":
        flags += ["-DWEIGHTED_FINITE_SEARCH", "-D_GTHREAD_USE_COND_INIT_FUNC"]
    return [compiler, "-std=c++20", "-O1", "-g0", "-D_GLIBCXX_ASSERTIONS",
            "-DDISABLE_MAX_HLS_STREAM_DEPTH_PRINT",
            "-Wno-unknown-pragmas", "-Wno-deprecated-declarations", "-ffunction-sections",
            "-fdata-sections", *flags, f"-I{source}", f"-I{include}", f"-I{include / 'etc'}",
            "-MMD", "-MF", str(binary.with_suffix(".d")), "-MT", "probe",
            str(source / "control.cpp"), "-Wl,--gc-sections", "-lgmp", "-pthread", "-o", str(binary)]
