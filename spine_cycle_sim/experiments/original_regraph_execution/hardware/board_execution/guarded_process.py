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


def run(command, *, timeout, **kwargs):
    before = memory_policy.live()
    minimum = before["effective_available_bytes"]
    maximum_psi = dict(before["pressure_avg10"])
    checks = 1
    settle = memory_policy.selected() == memory_policy.ARC_SETTLE
    pressure = memory_policy.PressureWindow()
    deadline = time.monotonic() + timeout
    with subprocess.Popen(command, start_new_session=True, **kwargs) as process:
        try:
            while True:
                observed = (memory_policy.live(allow_transient_pressure=True) if settle
                            else memory_policy.live())
                if settle:
                    pressure.check(observed, time.monotonic())
                checks += 1
                minimum = min(minimum, observed["effective_available_bytes"])
                maximum_psi = {key: max(maximum_psi[key], value)
                               for key, value in observed["pressure_avg10"].items()}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    code = process.wait(timeout=min(1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            stop(process)
            raise
    receipt = dict(profile=memory_policy.selected(), admission=before,
                   minimum_effective_available_bytes=minimum,
                   maximum_pressure_avg10=maximum_psi, checks=checks)
    if settle:
        receipt.update(pressure_grace_seconds=memory_policy.PRESSURE_GRACE_SECONDS,
                       maximum_consecutive_pressure_seconds=pressure.maximum_seconds,
                       pressured_checks=pressure.pressured_checks)
    return code, receipt
