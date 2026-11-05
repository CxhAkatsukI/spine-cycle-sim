"""Explicit board-only admission using a discounted clean ZFS ARC estimate."""

from contextlib import contextmanager
from contextvars import ContextVar
import math
from pathlib import Path

from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes


DEFAULT = "memavailable-v1"
ARC = "zfs-arc-clean-half-v1"
ARC_SETTLE = "zfs-arc-clean-half-settle10-v1"
ARC_BACKGROUND = "zfs-arc-clean-half-background5-v1"
PROFILES = (DEFAULT, ARC, ARC_SETTLE, ARC_BACKGROUND)
RESERVE_BYTES = 32 * 2**30
PRESSURE_GRACE_SECONDS = 10
_profile = ContextVar("board_memory_profile", default=DEFAULT)


class ObservationError(MemoryError):
    """Retain the observation that caused a safety stop, without changing it."""

    def __init__(self, message, observation):
        super().__init__(message + ": " + repr(observation))
        self.observation = observation


def selected():
    return _profile.get()


def settling():
    return selected() in (ARC_SETTLE, ARC_BACKGROUND)


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
    observation = estimate((proc / "meminfo").read_text(),
                           (proc / "spl/kstat/zfs/arcstats").read_text(),
                           (proc / "pressure/memory").read_text())
    observation["profile"] = selected()
    if selected() == ARC_BACKGROUND:
        observation["pressure_limits_avg10"] = dict(some=10, full=5)
        observation["pressure_ok"] = all(
            observation["pressure_avg10"][key] < limit
            for key, limit in observation["pressure_limits_avg10"].items())
    return observation


def live(*, allow_transient_pressure=False):
    if allow_transient_pressure and not settling():
        raise ValueError("transient pressure requires the explicit settle profile")
    observation = sample()
    if (observation["effective_available_bytes"] < RESERVE_BYTES
            or not allow_transient_pressure and not observation["pressure_ok"]):
        raise ObservationError("32-GiB live reserve and low memory PSI required", observation)
    return observation


class PressureWindow:
    """Bound consecutive high-PSI observations without relaxing physical reserve."""

    def __init__(self):
        self.started = None
        self.maximum_seconds = 0
        self.pressured_checks = 0

    def check(self, observation, now):
        if self.started is not None:
            self.maximum_seconds = max(self.maximum_seconds, now - self.started)
        if observation["pressure_ok"]:
            self.started = None
            return
        self.pressured_checks += 1
        if self.started is None:
            self.started = now
        if now - self.started >= PRESSURE_GRACE_SECONDS:
            raise ObservationError("memory PSI remained high for ten seconds", observation)
