"""Explicit finite local or named high-memory admission; no timing changes."""

from contextlib import contextmanager
from pathlib import Path
import threading
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...upstream_controls.execution import available_memory_bytes
from ...sharded_k4_stages.row_line.directory_tile.hardware import high_memory, memory_profiles
from ...sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from ...sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify


LOCAL = "local-finite-6g-v1"
LOCAL_PARALLEL = "local-finite-20g-v1"
CPU_ONLY = "cpu-only-cached-core-4g-v1"
CACHED_LOCAL = "local-cached-core-4g-reserve24-v1"
FRESH_CPU = "cpu-fresh-core-6g-reserve24-v1"
# The small cached profile is private to runners that validate the core first.
PROFILES = (memory_profiles.SEELE, LOCAL, LOCAL_PARALLEL, CPU_ONLY)


class AdmissionUnavailable(TimeoutError):
    """No experiment work started within the declared admission window."""


def wait_budget(seconds):
    if type(seconds) is not int or not 0 <= seconds <= 86400:
        raise ValueError("admission wait must be an integer from zero to 86400 seconds")
    return seconds


def settings(profile, workers):
    if type(workers) is not int or workers < 1:
        raise ValueError("positive integer worker count required")
    if profile == memory_profiles.SEELE:
        if workers > 4:
            raise ValueError("remote profile permits at most four workers")
        policy = memory_profiles.select(dict(tree_memory_gib=40, reserve_gib=32,
            background_memory_gib=8, allow_bounded_builds=True), profile)
        return {"profile": profile, "high_gib": 36, "policy": policy}
    if profile == LOCAL:
        if workers != 1:
            raise ValueError("local profile requires one worker")
        return {"profile": profile, "high_gib": 5, "policy": dict(tree_memory_gib=6,
            reserve_gib=24, background_memory_gib=8, allow_bounded_builds=True)}
    if profile == LOCAL_PARALLEL:
        if not 2 <= workers <= 4:
            raise ValueError("parallel local profile requires two to four workers")
        return {"profile": profile, "high_gib": 18, "policy": dict(tree_memory_gib=20,
            reserve_gib=24, background_memory_gib=8, allow_bounded_builds=True)}
    if profile == CPU_ONLY:
        if workers > 4:
            raise ValueError("CPU-only profile permits at most four workers")
        return {"profile": profile, "high_gib": 3, "policy": dict(tree_memory_gib=4,
            reserve_gib=8, background_memory_gib=4, allow_bounded_builds=True)}
    if profile == CACHED_LOCAL:
        if workers > 4:
            raise ValueError("cached local profile permits at most four workers")
        return {"profile": profile, "high_gib": 3, "policy": dict(tree_memory_gib=4,
            reserve_gib=24, background_memory_gib=8, allow_bounded_builds=True)}
    if profile == FRESH_CPU:
        if workers > 4:
            raise ValueError("fresh CPU profile permits at most four workers")
        return {"profile": profile, "high_gib": 5, "policy": dict(tree_memory_gib=6,
            reserve_gib=24, background_memory_gib=8, allow_bounded_builds=True)}
    raise ValueError("unknown execution memory profile")


def containment(group, selected):
    policy = selected["policy"]
    guard = verify(group, memory_gib=policy["tree_memory_gib"])
    expected = (("memory.max", policy["tree_memory_gib"]), ("memory.high", selected["high_gib"]))
    if any(guard["limits"][key] != str(gib * 1024**3) for key, gib in expected):
        raise ValueError("exact max/high containment required for " + selected["profile"])
    return guard


@contextmanager
def reservation(output, selected, wait_seconds=600):
    wait_budget(wait_seconds)
    group = current()
    guard = containment(group, selected)
    policy = selected["policy"]
    directory = Path.home() / ".cache/spine-cycle-sim/compiler-reservations"
    swapless_host = selected["profile"] in (CPU_ONLY, CACHED_LOCAL, FRESH_CPU)
    lease = (Lease(directory, group, host_swap_disabled=True) if swapless_host
             else high_memory.lease(directory, group, policy))
    stopped = threading.Event()
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            admission = lease.sample(available_memory_bytes(), other_builds(), policy, commit=True)
            atomic_write_json(output / "admission.json", admission)
            if admission["admitted"]:
                break
            if time.monotonic() >= deadline:
                raise AdmissionUnavailable("finite-budget admission timeout")
            time.sleep(5)

        def watch():
            while not stopped.wait(5):
                try:
                    containment(group, selected)
                    if swapless_host:
                        fields = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
                        if fields.get("SwapTotal", "").split() != ["0", "kB"]:
                            raise MemoryError("CPU-only host swap condition changed")
                    available = available_memory_bytes()
                    atomic_write_json(output / "live_memory.json", {"available_bytes": available,
                        "peak_bytes": int((group / "memory.peak").read_text()),
                        "swap_bytes": int((group / "memory.swap.current").read_text())})
                    if available < policy["reserve_gib"] * 1024**3:
                        raise MemoryError("declared live memory reserve breached")
                except Exception as error:
                    atomic_write_json(output / "reserve_failure.json", {"error": repr(error)})
                    (group / "cgroup.kill").write_text("1")
        threading.Thread(target=watch, daemon=True).start()
        yield {"profile": selected["profile"], "policy": policy, "cgroup": guard}
    finally:
        stopped.set()
        lease.release()
