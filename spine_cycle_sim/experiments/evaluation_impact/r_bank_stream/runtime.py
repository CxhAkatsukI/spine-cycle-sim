"""Exact high-memory lease and live containment for this remote study."""

from contextlib import contextmanager
from pathlib import Path
import threading
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...upstream_controls.execution import available_memory_bytes
from ...sharded_k4_stages.row_line.directory_tile.hardware import high_memory, memory_profiles
from ...sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify


@contextmanager
def reservation(output):
    group = current()
    guard = verify(group)
    if any(guard["limits"][key] != str(gib * 1024**3)
           for key, gib in (("memory.max", 40), ("memory.high", 36))):
        raise ValueError("exact 40/36-GiB containment required")
    policy = memory_profiles.select(dict(tree_memory_gib=40, reserve_gib=32,
        background_memory_gib=8, allow_bounded_builds=True), memory_profiles.SEELE)
    lease = high_memory.lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group, policy)
    stopped = threading.Event()
    try:
        deadline = time.monotonic() + 600
        while True:
            admission = lease.sample(available_memory_bytes(), other_builds(), policy, commit=True)
            atomic_write_json(output / "admission.json", admission)
            if admission["admitted"]:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("finite-budget admission timeout")
            time.sleep(5)

        def watch():
            while not stopped.wait(5):
                try:
                    verify(group)
                    available = available_memory_bytes()
                    atomic_write_json(output / "live_memory.json", {"available_bytes": available,
                        "peak_bytes": int((group / "memory.peak").read_text()),
                        "swap_bytes": int((group / "memory.swap.current").read_text())})
                    if available < 128 * 1024**3:
                        raise MemoryError("128-GiB live reserve breached")
                except Exception as error:
                    atomic_write_json(output / "reserve_failure.json", {"error": repr(error)})
                    (group / "cgroup.kill").write_text("1")
        threading.Thread(target=watch, daemon=True).start()
        yield {"policy": policy, "cgroup": guard}
    finally:
        stopped.set()
        lease.release()
