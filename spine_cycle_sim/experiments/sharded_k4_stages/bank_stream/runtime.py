"""Explicit execution relocation without changing compiled model identities."""

import os
from pathlib import Path
import socket

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.sst_library import forced_sst_library_binding
from ..execution import identity


def select(sst: Path, plugin: Path, cpus: tuple[int, ...], dramsim3: Path,
           expected_dram_sha256: str) -> tuple[dict, dict]:
    if not cpus or len(set(cpus)) != len(cpus) or not set(cpus) <= os.sched_getaffinity(0):
        raise ValueError("CPU selection must be nonempty, unique and available")
    binding = forced_sst_library_binding(sst, plugin)
    dram = dramsim3.resolve() / "libdramsim3.so"
    if sha256_file(dram) != expected_dram_sha256:
        raise ValueError("relocated DRAMSim3 differs from the tested plugin build")
    executable = sst.resolve()
    files = [identity(executable), identity(dram),
             identity(Path(binding["sst_element_path"]) / "libmemHierarchy.so")]
    simulator = executable.parent.parent / "libexec/sstsim.x"
    if simulator.is_file():
        files.append(identity(simulator))
    return binding, {"host": socket.gethostname(), "cpus": list(cpus),
                     "files": files, "dramsim3_root": str(dramsim3.resolve()),
                     "environment": {key: os.environ.get(key) for key in
                                     ("SST_ROOT", "PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "LD_PRELOAD")}}
