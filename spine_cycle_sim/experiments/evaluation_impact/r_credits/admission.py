"""Keep the resident-R reserve and account for pending bounded FPGA jobs."""

import math
import time

from ...upstream_controls.execution import available_memory_bytes
from ..common_g.search_pipeline.admission import unit_state

GIB = 1024**3
COMPETITORS = {"spine-sharded-k4-bank-sssp-20261012-v2.service": 40,
               "spine-grasu-full-cache-20261013-v3.service": 6,
               "spine-grasu-search-pipeline-20261013-v1.service": 8}


def decision(states, available):
    if set(states) != set(COMPETITORS):
        raise ValueError("complete competing build states required")
    reservations = {}
    for unit, bound in COMPETITORS.items():
        state = states[unit]
        if state.get("LoadState") != "loaded" or state.get("ActiveState") not in (
                "active", "activating", "deactivating", "inactive", "failed"):
            raise ValueError("unknown competing build state")
        if state["ActiveState"] not in ("inactive", "failed"):
            limit = int(state.get("MemoryMax", "0"))
            if not 0 < limit <= bound * GIB:
                raise ValueError("competing build exceeds declared reservation")
        reservations[unit] = 0 if state["ActiveState"] in ("inactive", "failed") else bound * GIB
    required = (4 + 24) * GIB + sum(reservations.values())
    return {"available_bytes": available, "required_bytes": required,
            "reservations": reservations, "admitted": available >= required}


def wait(report, save, maximum_wait):
    if not math.isfinite(maximum_wait) or maximum_wait < 0:
        raise ValueError("admission wait must be finite and nonnegative")
    started = time.monotonic()
    while True:
        states = {unit: unit_state(unit) for unit in COMPETITORS}
        sample = decision(states, available_memory_bytes())
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
