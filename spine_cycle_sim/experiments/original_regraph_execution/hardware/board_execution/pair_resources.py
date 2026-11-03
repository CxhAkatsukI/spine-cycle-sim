"""Bounded admission for queued one-shot R pairs, before either arm starts."""

from contextlib import ExitStack, contextmanager
from pathlib import Path
import subprocess
import time

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import concurrent, containment
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from ..source_retention.runtime import lease


@contextmanager
def admit(device, bdf, group, seconds, record):
    if not 1 <= seconds <= 21600:
        raise ValueError("paired board admission must be bounded to six hours")
    limits = containment.verify(group, memory_gib=8)["limits"]
    if int(limits["memory.max"]) != 8 * 2**30:
        raise ValueError("queued R pair requires an exact 8-GiB reservation")
    memory = concurrent.Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
    policy = {"tree_memory_gib": 8, "reserve_gib": 32, "allow_bounded_builds": True}
    deadline = time.monotonic() + seconds
    while True:
        with ExitStack() as resources:
            resources.callback(memory.release)
            memory_state = memory.sample(available_memory_bytes(), containment.other_builds(), policy, commit=True)
            if memory.held:
                try:
                    node, fd = resources.enter_context(lease(device, bdf))
                except BlockingIOError:
                    pass
                else:
                    users = subprocess.run(["fuser", str(node)], capture_output=True, timeout=10)
                    if users.returncode == 1 and not (users.stdout or users.stderr):
                        record("BOARD_ADMITTED", memory_state)
                        yield node, fd
                        return
                    if users.returncode != 0 or users.stderr:
                        raise RuntimeError("board occupancy check failed")
            record("WAITING_FOR_BOARD" if memory.held else "WAITING_FOR_MEMORY", memory_state)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("paired board admission expired before any measured arm")
        time.sleep(min(10, remaining))
