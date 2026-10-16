"""Freeze only the shared host bindings, layout and generation-lifecycle control."""

import copy
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..continuous_board.preparation import command as host_command
from ..native_board.preparation import CASE as NATIVE_CASE
from ..study import ROOT

CASE = {**copy.deepcopy(NATIVE_CASE), "case": "native-metadata-refresh", "input": "native-metadata-refresh",
        "ports_nonempty_batch": [4, 2, 4, 2],
        "batches": [{"batch": batch, "updates": 12 if batch else 0, "edges": edges}
                    for batch, edges in enumerate((524296, 524284, 524296))]}
CLAIMS = ("fpga_measured", "device_metadata_refresh_verified", "integrated_rtl_verified",
          "original_g_performance_matched", "complete_gr_admitted", "publication_matched")


def prepare(output, integration):
    output.mkdir(parents=True, exist_ok=False)
    groups = {
        "host": [integration / "include" / name for name in (
            "weighted_pma_graph.hpp", "weighted_pma_runtime_plan.hpp", "weighted_pma_update_reference.hpp")],
        "host_prepared": [ROOT / "cpp/tests/evaluation_impact/common_g/complete_pipeline/host_prepared/input.hpp"],
        "native_geometry": [ROOT / "cpp/tests/evaluation_impact/common_g/complete_pipeline/native_geometry/layout.hpp"],
        "continuous_board": sorted((ROOT / "cpp/tests/evaluation_impact/common_g/continuous_board").glob("*.?pp")),
        "metadata_refresh": sorted((ROOT / "cpp/tests/evaluation_impact/common_g/metadata_refresh").glob("*.?pp")),
        "runner/metadata_refresh": sorted(Path(__file__).parent.glob("*.py")),
    }
    pins = []
    for group, paths in groups.items():
        target = output / "source" / group
        target.mkdir(parents=True)
        for path in paths:
            frozen = target / path.name
            shutil.copy2(path, frozen)
            digest = sha256_file(frozen)
            if sha256_file(path) != digest:
                raise ValueError("metadata lifecycle source changed while freezing")
            pins.append({"original": str(path), "path": str(frozen), "sha256": digest})
    contract = {"case": CASE, "generations": 2, "same_bos": True, "restored_pma": False,
                "source_pairs": [[source, source + 262144] for source in range(4)],
                "updated_sources": [0, 1, 262142, 262143, 262146, 262147],
                "scope": "synthetic directory remap after exact reinsertion; fixed full-cache production layout",
                "not_claimed": ["real-trace capacity growth", "production host rebin policy",
                                "ReGraph compute", "original-G speed", "algorithm convergence"],
                "timing_boundary": "metadata preparation/DMA separate; per-batch pack/DMA/launch-wait to publication",
                "cpu_negative": "retain generation-zero directory; reject at generation one batch one"}
    atomic_write_json(output / "contract.json", contract)
    pins.append({"path": str(output / "contract.json"), "sha256": sha256_file(output / "contract.json")})
    return pins, contract


def command(source, xrt, compiler, binary):
    argv = host_command(source, xrt, compiler, binary)
    argv[argv.index(str(source / "continuous_board/control.cpp"))] = str(source / "metadata_refresh/control.cpp")
    return argv
