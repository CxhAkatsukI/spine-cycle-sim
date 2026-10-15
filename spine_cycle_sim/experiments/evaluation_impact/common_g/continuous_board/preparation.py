"""Freeze the production preparation contract and the small XRT G-only host."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..complete_pipeline.host_prepared.preparation import prepare as prepare_real
from ..study import ROOT


def prepare(output, upstream, integration):
    pins, original = prepare_real(output, upstream, integration)
    source = output / "source"
    groups = {
        "continuous_board": sorted((ROOT / "cpp/tests/evaluation_impact/common_g/continuous_board").glob("*.?pp")),
        "runner/continuous_board": sorted(Path(__file__).parent.glob("*.py")),
        "host": [integration / "include/weighted_pma_update_reference.hpp"],
    }
    for group, paths in groups.items():
        (source / group).mkdir(parents=True, exist_ok=True)
        for path in paths:
            frozen = source / group / path.name
            shutil.copy2(path, frozen)
            digest = sha256_file(frozen)
            if sha256_file(path) != digest:
                raise ValueError("source changed during freeze")
            pins.append({"original": str(path), "path": str(frozen), "sha256": digest})
    contract = {**original, "cases": [row for row in original["cases"] if row["partition_vertices"] == 65536],
                "scope": "G only; three resident batches; same BO addresses; no PMA restoration",
                "timing_boundary": "per-batch lowering/packing through update DMA, G completion and publication barrier",
                "diagnostic_costs_separate": ["one-time builder/reservation/program/upload", "independent oracle",
                                              "full PMA and metadata verification readback", "event/report formatting"],
                "excludes": ["adapter and ReGraph", "algorithm convergence", "original-G performance match",
                             "unseen future capacity growth", "cold real-trace updates"]}
    # The inherited real-input contract remains immutable, with a separate board contract.
    atomic_write_json(output / "continuous_contract.json", contract)
    pins.append({"path": str(output / "continuous_contract.json"),
                 "sha256": sha256_file(output / "continuous_contract.json")})
    return pins, contract


def command(source, xrt, compiler, binary):
    return [compiler, "-std=c++20", "-O2", "-g0", "-Wall", "-Wextra", "-Werror",
            "-D_GLIBCXX_ASSERTIONS", "-MD", "-MF", str(binary.with_suffix(".d")), "-MT", "probe",
            f"-I{source}", "-isystem", str(xrt / "include"),
            str(source / "continuous_board/control.cpp"), f"-L{xrt / 'lib'}",
            f"-Wl,-rpath,{xrt / 'lib'}", "-lxilinxopencl", "-pthread", "-o", str(binary)]
