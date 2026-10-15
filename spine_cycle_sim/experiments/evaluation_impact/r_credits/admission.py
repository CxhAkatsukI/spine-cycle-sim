"""Keep the resident-R reserve and account for pending bounded FPGA jobs."""

import math
import time

from ...upstream_controls.execution import available_memory_bytes
from ..common_g.search_pipeline.admission import terminal, unit_state

GIB = 1024**3
COMPETITORS = {"spine-sharded-k4-bank-sssp-20261012-v2.service": 40,
               "spine-grasu-full-cache-20261013-v3.service": 6,
               "spine-grasu-search-pipeline-20261013-v1.service": 8}


def competitors(route, cache, search):
    units = (route, cache, search)
    if len(set(units)) != 3 or any(not unit.endswith(".service") or
            not unit or any(c.isspace() for c in unit) for unit in units):
        raise ValueError("three distinct bounded service names required")
    return dict(zip(units, (40, 6, 8)))


def decision(states, available, reservations=None):
    bounds = COMPETITORS if reservations is None else reservations
    if not bounds or any(type(bound) is not int or not 0 < bound <= 40 for bound in bounds.values()):
        raise ValueError("finite positive competing build bounds required")
    if set(states) != set(bounds):
        raise ValueError("complete competing build states required")
    reserved = {}
    for unit, bound in bounds.items():
        state = states[unit]
        ended = terminal(state)
        if not ended:
            limit = int(state.get("MemoryMax", "0"))
            if not 0 < limit <= bound * GIB:
                raise ValueError("competing build exceeds declared reservation")
        reserved[unit] = 0 if ended else bound * GIB
    required = (4 + 24) * GIB + sum(reserved.values())
    return {"available_bytes": available, "required_bytes": required,
            "reservations": reserved, "admitted": available >= required}


def wait(report, save, maximum_wait, reservations=None):
    if not math.isfinite(maximum_wait) or maximum_wait < 0:
        raise ValueError("admission wait must be finite and nonnegative")
    started = time.monotonic()
    bounds = COMPETITORS if reservations is None else reservations
    while True:
        states = {unit: unit_state(unit) for unit in bounds}
        sample = decision(states, available_memory_bytes(), bounds)
        sample["states"] = states
        sample["elapsed_seconds"] = time.monotonic() - started
        report["admission"] = sample
        if sample["admitted"]:
            return sample["elapsed_seconds"]
        report["status"] = "WAITING_FOR_SAFE_MEMORY"
        save()
        if sample["elapsed_seconds"] >= maximum_wait:
            raise RuntimeError("safe memory admission expired; no timing case launched")
        time.sleep(min(30, maximum_wait - sample["elapsed_seconds"]))
