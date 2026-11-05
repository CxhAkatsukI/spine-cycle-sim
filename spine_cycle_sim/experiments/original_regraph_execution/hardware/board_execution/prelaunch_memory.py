"""Bounded strict re-admission after clock preparation, before a child exists."""

import math
import subprocess
import time

from . import memory_policy


MAX_WAIT_SECONDS = 60


def admit(timeout):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("positive finite child timeout required")
    receipt = dict(status="NOT_STARTED", child_started=False, checks=0,
                   waited_seconds=0, pressure_checks=0)
    started = None
    while True:
        receipt["checks"] += 1
        try:
            observation = memory_policy.live()
        except memory_policy.ObservationError as error:
            observation = error.observation
            receipt["last_observation"] = observation
            if started is not None:
                receipt["waited_seconds"] = time.monotonic() - started
            retry = (memory_policy.selected() == memory_policy.ARC_SETTLE
                     and observation["effective_available_bytes"] >= memory_policy.RESERVE_BYTES
                     and not observation["pressure_ok"])
            if retry:
                receipt["pressure_checks"] += 1
                if started is None:
                    started = time.monotonic()
                remaining = min(MAX_WAIT_SECONDS, timeout) - receipt["waited_seconds"]
                if remaining > 0:
                    time.sleep(min(1, remaining))
                    continue
            error.memory_guard = dict(status="NOT_STARTED", child_started=False,
                                      prelaunch=receipt, error=repr(error))
            raise
        receipt["last_observation"] = observation
        if started is not None:
            receipt["waited_seconds"] = time.monotonic() - started
            if receipt["waited_seconds"] >= min(MAX_WAIT_SECONDS, timeout):
                error = subprocess.TimeoutExpired("board prelaunch memory admission",
                                                  min(MAX_WAIT_SECONDS, timeout))
                error.memory_guard = dict(status="NOT_STARTED", child_started=False,
                                          prelaunch=receipt, error=repr(error))
                raise error
        receipt["status"] = "ADMITTED"
        return observation, receipt
