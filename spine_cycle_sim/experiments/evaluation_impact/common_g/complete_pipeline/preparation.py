"""Freeze the shared candidate and production components in one source tree."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..study import ROOT
from ..weighted_abi.preparation import BANK_FLAGS


def prepare(output: Path, upstream: Path, integration: Path):
    output.mkdir(parents=True, exist_ok=False)
    tests = ROOT / "cpp/tests/evaluation_impact/common_g"
    production = integration / "repos/GraSU/GraSU/GraSU_kernels/src"
    groups = {
        "": sorted((tests / "complete_pipeline").glob("*.*")),
        "upstream": [upstream / name for name in ("kernel_config.h", "kernel_process_cache.cpp")],
        "integration": [production / name for name in
                        ("kernel_config.h", "kernel_dispatch.cpp", "kernel_process_ddr.cpp")],
        "adapter": sorted((integration / "kernels/pma_to_regraph_adapter").glob("*.hpp")) +
                   [integration / "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp"],
        "hls": [tests / "hls" / name for name in
                ("cache_full.cpp", "cache_bank.hpp", "cache_lane.hpp", "cache_pipeline.hpp")],
        "hls/search_binding": [tests / "hls/search_binding" / name for name in ("top.cpp", "top.hpp")],
        "hls/search_pipeline": sorted((tests / "hls/search_pipeline").glob("*.hpp")),
        "runner/complete_pipeline": sorted(Path(__file__).parent.glob("*.py")),
        "runner/upstream_controls": [ROOT / "spine_cycle_sim/experiments/upstream_controls/execution.py"],
        "runner/shared": [ROOT / "spine_cycle_sim/experiments/campaign_runtime.py"],
        "runner/weighted_abi": [ROOT /
            "spine_cycle_sim/experiments/evaluation_impact/common_g/weighted_abi/preparation.py"],
        "runner/search_pipeline": [ROOT /
            "spine_cycle_sim/experiments/evaluation_impact/common_g/search_pipeline/synthesis.py"],
    }
    pins = []
    for group, paths in groups.items():
        target = output / "source" / group
        target.mkdir(parents=True, exist_ok=True)
        for path in paths:
            frozen = target / path.name
            shutil.copy2(path, frozen)
            digest = sha256_file(frozen)
            if sha256_file(path) != digest:
                raise ValueError("source changed during freeze")
            pins.append({"original": str(path), "path": str(frozen), "sha256": digest})
    return pins


def command(source: Path, include: Path, compiler: str, binary: Path):
    flags = [f"-DGRASU_REGRAPH_{name}=1" for name in BANK_FLAGS]
    return [compiler, "-std=c++20", "-O1", "-g0", "-D_GLIBCXX_ASSERTIONS",
            "-D_GTHREAD_USE_COND_INIT_FUNC", "-DDISABLE_MAX_HLS_STREAM_DEPTH_PRINT",
            "-DCACHE_BANK_REGISTERED", "-DGRASU_REGRAPH_DIRECTORY_TILE_ROWS=1024",
            "-DGRASU_REGRAPH_BANK_FIFO_LINES=256", *flags,
            "-Wno-unknown-pragmas", "-Wno-deprecated-declarations", f"-I{source}",
            f"-I{include}", f"-I{include / 'etc'}", "-MMD", "-MF", str(binary.with_suffix(".d")),
            "-MT", "probe", str(source / "control.cpp"), "-lgmp", "-pthread", "-o", str(binary)]
