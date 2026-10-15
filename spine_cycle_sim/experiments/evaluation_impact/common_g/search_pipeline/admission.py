"""Admit independent bounded component tools when their full budgets fit."""

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


def decision(previous, route, available, background_memory_gib=0):
    if type(background_memory_gib) is not int or not 0 <= background_memory_gib <= 40:
        raise ValueError("background workload reserve must be between zero and 40 GiB")
    reservations = {}
    for name, state, bound in (("previous_hls", previous, 6), ("route", route, 40)):
        ended = terminal(state)
        if not ended and not 0 < int(state.get("MemoryMax", "0")) <= bound * GIB:
            raise ValueError("competing build exceeds declared finite cgroup bound")
        # The cache supervisor and its separate tool scope share this declared budget.
        reservations[name] = 0 if ended else bound * GIB
    required = (8 + 24 + background_memory_gib) * GIB + sum(reservations.values())
    return {"previous_hls_terminal": terminal(previous),
            "previous_hls_reservation_bytes": reservations["previous_hls"],
            "route_reservation_bytes": reservations["route"],
            "background_reservation_bytes": background_memory_gib * GIB,
            "required_bytes": required, "available_bytes": available,
            "admitted": available >= required}


def wait(record, save, previous_unit, route_unit, maximum_wait, background_memory_gib=0):
    if not math.isfinite(maximum_wait) or maximum_wait < 0:
        raise ValueError("admission wait must be finite and nonnegative")
    started = time.monotonic()
    record["admission"] = {"previous_unit": previous_unit, "route_unit": route_unit,
                           "background_memory_gib": background_memory_gib,
                           "maximum_wait_seconds": maximum_wait, "samples": []}
    while True:
        previous, route = unit_state(previous_unit), unit_state(route_unit)
        elapsed = time.monotonic() - started
        sample = {**decision(previous, route, available_memory_bytes(), background_memory_gib),
                  "elapsed_seconds": elapsed, "previous": previous, "route": route}
        record["admission"]["samples"].append(sample)
        record["status"] = "ADMITTED_FOR_ISOLATED_HLS" if sample["admitted"] else "WAITING_FOR_MEMORY"
        save()
        if sample["admitted"]:
            return sample["required_bytes"] // GIB - 8
        if elapsed >= maximum_wait:
            raise RuntimeError("memory admission expired; no HLS tool launched")
        time.sleep(min(30, maximum_wait - elapsed))
