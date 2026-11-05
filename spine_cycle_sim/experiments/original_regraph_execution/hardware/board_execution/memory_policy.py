"""Explicit board-only admission using a discounted clean ZFS ARC estimate."""

from contextlib import contextmanager
from contextvars import ContextVar
import math
from pathlib import Path

from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes


DEFAULT = "memavailable-v1"
ARC = "zfs-arc-clean-half-v1"
PROFILES = (DEFAULT, ARC)
RESERVE_BYTES = 32 * 2**30
_profile = ContextVar("board_memory_profile", default=DEFAULT)


def selected():
    return _profile.get()


@contextmanager
def scope(profile):
    if profile not in PROFILES:
        raise ValueError("unknown board memory profile")
    token = _profile.set(profile)
    try:
        yield
    finally:
        _profile.reset(token)


def estimate(meminfo, arcstats, pressure):
    memory = dict(line.split(":", 1) for line in meminfo.splitlines())
    values = {}
    for key in ("MemTotal", "MemAvailable", "MemFree"):
        amount, unit = memory[key].split()
        values[key] = int(amount) * 1024
        if unit != "kB" or not 0 <= values[key] <= int(memory["MemTotal"].split()[0]) * 1024:
            raise ValueError("invalid physical memory observation")
    if not values["MemTotal"]:
        raise ValueError("positive physical memory size required")
    arc = {}
    required = {"size", "c_min", "mru_evictable_data", "mfu_evictable_data"}
    for line in arcstats.splitlines():
        fields = line.split()
        if fields and fields[0] in required:
            if len(fields) != 3 or fields[0] in arc:
                raise ValueError("invalid or duplicate ARC counter")
            arc[fields[0]] = int(fields[2])
    if set(arc) != required or any(not 0 <= v <= values["MemTotal"] for v in arc.values()):
        raise ValueError("complete nonnegative ARC counters required")
    clean = min(arc["mru_evictable_data"] + arc["mfu_evictable_data"],
                max(0, arc["size"] - arc["c_min"]))
    psi = {}
    for line in pressure.splitlines():
        fields = line.split()
        if not fields or fields[0] not in ("some", "full") or fields[0] in psi:
            raise ValueError("complete memory PSI observation required")
        psi[fields[0]] = float(dict(item.split("=", 1) for item in fields[1:])["avg10"])
    if set(psi) != {"some", "full"} or any(not math.isfinite(v) or not 0 <= v <= 100 for v in psi.values()):
        raise ValueError("invalid memory PSI average")
    # MemFree, not MemAvailable: the latter may already count reclaimable pages.
    effective = max(values["MemAvailable"], min(values["MemTotal"], values["MemFree"] + clean // 2))
    return dict(profile=ARC, mem_available_bytes=values["MemAvailable"],
                mem_free_bytes=values["MemFree"], arc=arc, clean_evictable_bytes=clean,
                discount_denominator=2, effective_available_bytes=effective,
                pressure_avg10=psi, pressure_ok=psi["some"] < 10 and psi["full"] < 1)


def sample(proc=Path("/proc")):
    if selected() == DEFAULT:
        return dict(profile=DEFAULT, effective_available_bytes=available_memory_bytes(), pressure_ok=True)
    return estimate((proc / "meminfo").read_text(),
                    (proc / "spl/kstat/zfs/arcstats").read_text(),
                    (proc / "pressure/memory").read_text())


def live():
    observation = sample()
    if observation["effective_available_bytes"] < RESERVE_BYTES or not observation["pressure_ok"]:
        raise MemoryError("32-GiB live reserve and low memory PSI required: " + repr(observation))
    return observation
