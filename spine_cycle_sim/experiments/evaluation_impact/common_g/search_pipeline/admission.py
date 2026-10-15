"""Serialize component tools and reserve for the already queued route."""

import math
import subprocess
import time

from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes

GIB = 1024**3


def terminal(state):
    if state.get("LoadState") == "not-found":
        if (state.get("ActiveState"), state.get("SubState")) == ("inactive", "dead"):
            return True
        raise ValueError("absent competing unit has inconsistent runtime state")
    if state.get("LoadState") != "loaded" or state.get("ActiveState") not in (
            "active", "activating", "deactivating", "inactive", "failed"):
        raise ValueError("cannot establish competing build state")
    return state["ActiveState"] in ("inactive", "failed")


def unit_state(unit):
    completed = subprocess.run(["systemctl", "--user", "show", unit,
        "--property=LoadState,ActiveState,SubState,Result,MemoryMax"],
        capture_output=True, text=True, check=True, timeout=10)
    state = dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)
    terminal(state)
    return state


def decision(previous, route, available):
    serial_ready = terminal(previous)
    pending = not terminal(route)
    route_max = int(route["MemoryMax"]) if pending else 0
    if (pending and route_max <= 0) or route_max > 251 * GIB:
        raise ValueError("invalid competing route cgroup bound")
    required = 8 * GIB + 24 * GIB + route_max
    return {"previous_hls_terminal": serial_ready, "route_reservation_bytes": route_max,
            "required_bytes": required, "available_bytes": available,
            "admitted": serial_ready and available >= required}


def wait(record, save, previous_unit, route_unit, maximum_wait):
    if not math.isfinite(maximum_wait) or maximum_wait < 0:
        raise ValueError("admission wait must be finite and nonnegative")
    started = time.monotonic()
    record["admission"] = {"previous_unit": previous_unit, "route_unit": route_unit,
                           "maximum_wait_seconds": maximum_wait, "samples": []}
    while True:
        previous, route = unit_state(previous_unit), unit_state(route_unit)
        elapsed = time.monotonic() - started
        sample = {**decision(previous, route, available_memory_bytes()),
                  "elapsed_seconds": elapsed, "previous": previous, "route": route}
        record["admission"]["samples"].append(sample)
        record["status"] = ("ADMITTED_FOR_ISOLATED_HLS" if sample["admitted"] else
                            "WAITING_FOR_MEMORY" if sample["previous_hls_terminal"] else
                            "WAITING_FOR_PREVIOUS_HLS")
        save()
        if sample["admitted"]:
            return sample["required_bytes"] // GIB - 8
        if elapsed >= maximum_wait:
            raise RuntimeError("serial/memory admission expired; no HLS tool launched")
        time.sleep(min(30, maximum_wait - elapsed))
