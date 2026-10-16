"""Freeze the shared XRT bindings and native synthetic layout, without vendor HLS headers."""

from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..continuous_board.preparation import command as host_command, prepare as host_prepare
from ..study import ROOT

CASE = {"case": "native-five-shard-hot-cold", "input": "native-five-shard-hot-cold",
        "vertices": 262148, "shards": 5, "partition_vertices": 65536,
        "cache_segments_per_half": 131072, "checked_words": 29360352, "hbm_bytes": 140673024,
        "reserved_operations": 1048592, "populated_shards": [0, 4], "empty_shards": [1, 2, 3],
        "ports_nonempty_batch": [6, 4, 6, 4], "dma_lanes_per_populated_shard": 4,
        "batches": [{"batch": batch, "updates": 20 if batch else 0, "edges": edges}
                    for batch, edges in enumerate((524296, 524276, 524296))]}


def prepare(output, upstream, integration):
    pins, old = host_prepare(output, upstream, integration)
    groups = {"native_geometry": [ROOT / "cpp/tests/evaluation_impact/common_g/complete_pipeline/native_geometry/layout.hpp"],
              "native_board": sorted((ROOT / "cpp/tests/evaluation_impact/common_g/native_board").glob("*.?pp")),
              "runner/native_board": sorted(Path(__file__).parent.glob("*.py"))}
    for group, paths in groups.items():
        target = output / "source" / group
        target.mkdir(parents=True)
        for path in paths:
            frozen = target / path.name
            shutil.copy2(path, frozen)
            digest = sha256_file(frozen)
            if sha256_file(path) != digest:
                raise ValueError("native board source changed during freeze")
            pins.append({"original": str(path), "path": str(frozen), "sha256": digest})
    contract = {"cases": [CASE], "regression_cases": old["cases"],
                "scope": "synthetic native full-cache G; resident empty/delete/insert; same BOs, no PMA restore",
                "timing_boundary": old["timing_boundary"], "diagnostic_costs_separate": old["diagnostic_costs_separate"],
                "excludes": ["original-G performance", "ReGraph or adapter compute", "algorithm convergence",
                             "full reservation trace execution", "real-trace performance"]}
    atomic_write_json(output / "native_board_contract.json", contract)
    pins.append({"path": str(output / "native_board_contract.json"),
                 "sha256": sha256_file(output / "native_board_contract.json")})
    return pins, contract


def command(source, xrt, compiler, binary):
    argv = host_command(source, xrt, compiler, binary)
    argv[argv.index(str(source / "continuous_board/control.cpp"))] = str(source / "native_board/control.cpp")
    return argv
