"""Live-memory supervision with cleanup restricted to an owned process group."""

import os
import signal
import subprocess
import time

from . import memory_policy


def stop(process):
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            break
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            continue
        # The group may still contain a descendant after the parent exited.
        if signum == signal.SIGTERM:
            continue
    process.wait()


def _remember(receipt, observation):
    receipt["checks"] += 1
    receipt["last_observation"] = observation
    receipt["minimum_effective_available_bytes"] = min(
        receipt["minimum_effective_available_bytes"], observation["effective_available_bytes"])
    receipt["maximum_pressure_avg10"] = {
        key: max(value, observation["pressure_avg10"][key])
        for key, value in receipt["maximum_pressure_avg10"].items()}


def run(command, *, timeout, **kwargs):
    before = memory_policy.live()
    receipt = dict(profile=memory_policy.selected(), admission=before, status="RUNNING",
                   minimum_effective_available_bytes=before["effective_available_bytes"],
                   maximum_pressure_avg10=dict(before["pressure_avg10"]), checks=0)
    _remember(receipt, before)
    settle = memory_policy.selected() == memory_policy.ARC_SETTLE
    pressure = memory_policy.PressureWindow()
    deadline = time.monotonic() + timeout
    with subprocess.Popen(command, start_new_session=True, **kwargs) as process:
        try:
            while True:
                observed = (memory_policy.live(allow_transient_pressure=True) if settle
                            else memory_policy.live())
                _remember(receipt, observed)
                if settle:
                    pressure.check(observed, time.monotonic())
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    code = process.wait(timeout=min(1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    pass
        except BaseException as error:
            failed = getattr(error, "observation", None)
            if failed is not None and failed is not receipt["last_observation"]:
                _remember(receipt, failed)
            receipt.update(status="ABORTED", error=repr(error))
            error.memory_guard = receipt
            stop(process)
            raise
        finally:
            if settle:
                receipt.update(pressure_grace_seconds=memory_policy.PRESSURE_GRACE_SECONDS,
                               maximum_consecutive_pressure_seconds=pressure.maximum_seconds,
                               pressured_checks=pressure.pressured_checks)
    receipt["status"] = "COMPLETED"
    return code, receipt
